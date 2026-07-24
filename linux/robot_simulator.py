#!/usr/bin/env python3
"""
ROS2 机器人数据模拟器 — 大疆风格焦点跟随版
==========================================
用于 Ubuntu 22.04 + ROS2 Humble + rosbridge 前端联调。

新增功能（配合 FollowCameraPopup.vue 升级）:
  - /yolo_detections 话题发布（10Hz 模拟 YOLO 检测框 + 绿色锁定点）
  - Flask API: /api/follow/start|stop|lock|config|roi
  - 三种跟随模式闭环模拟（平行/尾随/环绕），小车在地图上真实移动
  - /odom 里程计话题（配合前端 MapCanvas 小车图标移动）

架构：
  ROS 2 主循环（rclpy.spin）  — 所有话题发布/订阅/定时器
  Flask HTTP 服务（Thread）    — 接收前端 REST API 调用
  点云发布（独立 Thread）      — 避免阻塞主循环

用法:
  pip install opencv-python Pillow flask flask-cors
  python3 robot_simulator.py                    # 标准启动
  python3 robot_simulator.py --follow-debug     # 调试模式（详细日志）
  python3 robot_simulator.py --port 5000        # 指定 Flask 端口
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, DurabilityPolicy

import math
import struct
import random
import os
import sys
import json
import time
import argparse
import cv2
import numpy as np
from threading import Lock, Thread, Event

from geometry_msgs.msg import Pose, Twist, PoseStamped, PoseWithCovarianceStamped
from sensor_msgs.msg import (
    BatteryState, CompressedImage, PointCloud2, PointField, RegionOfInterest,
)
from nav_msgs.msg import Odometry
from std_msgs.msg import String, Bool, Header, Int32MultiArray
from nav_msgs.msg import OccupancyGrid, MapMetaData
from std_srvs.srv import Trigger

PCD_PATH = 'test.pcd'

# ================================================================
# 全局命令行参数
# ================================================================
_parser = argparse.ArgumentParser(description='ROS2 机器人模拟器（大疆跟随版）')
_parser.add_argument('--follow-debug', action='store_true', help='开启跟随调试日志')
_parser.add_argument('--port', type=int, default=5000, help='Flask HTTP 端口 (默认 5000)')
_parser.add_argument('--no-camera', action='store_true', help='跳过摄像头初始化')
_args, _ = _parser.parse_known_args()

# ================================================================
# Flask HTTP 服务（独立线程，供前端 /api/follow/* 调用）
# ================================================================
try:
    from flask import Flask, request as flask_request, jsonify
    from flask_cors import CORS
    _FLASK_OK = True
except ImportError:
    _FLASK_OK = False
    print('[WARN] flask / flask-cors 未安装，Flask API 不可用。'
          '请执行: pip install flask flask-cors')

flask_app = None
if _FLASK_OK:
    flask_app = Flask(__name__)
    CORS(flask_app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# ================================================================
# 全局跟随状态（Flask 线程 ↔ ROS 节点共享）
# ================================================================
_follow_lock = Lock()
_follow_state = {
    'active': False,           # 跟随模式是否已启动
    'scan_enabled': True,      # 目标扫描开关
    'target_locked': False,    # 目标是否已锁定
    'follow_mode': 'trace',    # parallel / trace / orbit
    'locked_class_id': 0,      # 锁定目标类别 ID
    'locked_class_name': '',   # 锁定目标类别名
    'locked_confidence': 0.0,  # 锁定目标置信度
    'locked_bbox': None,       # {x_min, y_min, x_max, y_max}
    'roi': None,               # 框选 ROI {x_min, y_min, x_max, y_max}
}


def _follow_set(**kwargs):
    """线程安全地更新跟随状态"""
    with _follow_lock:
        _follow_state.update(kwargs)


def _follow_get(key):
    """线程安全地读取跟随状态"""
    with _follow_lock:
        return _follow_state.get(key)


# ================================================================
# Flask 路由（前端 useFollowMode.ts 调用这些接口）
# ================================================================
def _register_flask_routes():
    """注册所有路由到 flask_app"""

    @flask_app.route('/')
    def index():
        return jsonify({
            'status': 'online',
            'message': 'SparkCar Robot Simulator API Node is Running!',
            'endpoints': [
                'POST /api/follow/start',
                'POST /api/follow/stop',
                'POST /api/follow/lock',
                'POST /api/follow/config',
                'POST /api/follow/roi',
                'GET  /api/follow/status',
            ],
        }), 200

    @flask_app.route('/api/follow/start', methods=['POST', 'OPTIONS'])
    def api_follow_start():
        if flask_request.method == 'OPTIONS':
            return '', 204
        _follow_set(active=True, scan_enabled=True, target_locked=False)
        print('[Follow] 跟随模式已启动（模拟器）')
        return jsonify({'ok': True, 'detail': '跟随模式已启动（模拟器）', 'pid': os.getpid()})

    @flask_app.route('/api/follow/stop', methods=['POST', 'OPTIONS'])
    def api_follow_stop():
        if flask_request.method == 'OPTIONS':
            return '', 204
        _follow_set(
            active=False, scan_enabled=False, target_locked=False,
            follow_mode='trace', locked_bbox=None, roi=None,
        )
        print('[Follow] 跟随模式已停止（模拟器）')
        return jsonify({'ok': True, 'detail': '跟随模式已停止（模拟器）'})

    @flask_app.route('/api/follow/lock', methods=['POST', 'OPTIONS'])
    def api_follow_lock():
        if flask_request.method == 'OPTIONS':
            return '', 204
        data = flask_request.get_json(force=True, silent=True) or {}
        target_id = data.get('target_id', -1)
        class_id = data.get('class_id', 0)
        class_name = data.get('class_name', 'person')
        bbox = data.get('bbox', {})
        confidence = data.get('confidence', 0.85)
        _follow_set(
            target_locked=True,
            locked_class_id=class_id,
            locked_class_name=class_name,
            locked_confidence=confidence,
            locked_bbox=bbox,
        )
        print(f'[Follow] 目标已锁定: {class_name} (id={target_id}, '
              f'conf={confidence:.2f}, bbox={bbox})')
        return jsonify({'ok': True, 'detail': f'目标已锁定: {class_name}'})

    @flask_app.route('/api/follow/config', methods=['POST', 'OPTIONS'])
    def api_follow_config():
        if flask_request.method == 'OPTIONS':
            return '', 204
        data = flask_request.get_json(force=True, silent=True) or {}
        mode = data.get('mode', 'trace')
        if mode not in ('parallel', 'trace', 'orbit'):
            return jsonify({'ok': False, 'detail': f'未知模式: {mode}'}), 400
        _follow_set(follow_mode=mode)
        labels = {'parallel': '平行跟随', 'trace': '尾随追踪', 'orbit': '环绕监视'}
        print(f'[Follow] 模式已切换: {labels.get(mode, mode)}')
        return jsonify({'ok': True, 'detail': f'模式已切换: {labels.get(mode, mode)}'})

    @flask_app.route('/api/follow/roi', methods=['POST', 'OPTIONS'])
    def api_follow_roi():
        if flask_request.method == 'OPTIONS':
            return '', 204
        data = flask_request.get_json(force=True, silent=True) or {}
        roi = {
            'x_min': data.get('x_min', 0),
            'y_min': data.get('y_min', 0),
            'x_max': data.get('x_max', 640),
            'y_max': data.get('y_max', 480),
        }
        img_w = data.get('image_width', 640)
        img_h = data.get('image_height', 480)
        _follow_set(roi=roi, target_locked=True,
                     locked_class_name='roi_selection',
                     locked_bbox=roi)
        print(f'[Follow] ROI 框选: {roi} (image={img_w}x{img_h})')
        return jsonify({'ok': True, 'detail': 'ROI 已接收'})

    @flask_app.route('/api/follow/status', methods=['GET', 'OPTIONS'])
    def api_follow_status():
        if flask_request.method == 'OPTIONS':
            return '', 204
        with _follow_lock:
            state = dict(_follow_state)
        return jsonify({'ok': True, **state})

    # 地图编辑接口（与 unified_backend 保持兼容）
    @flask_app.route('/api/map/save_edited', methods=['POST', 'OPTIONS'])
    def api_save_edited():
        if flask_request.method == 'OPTIONS':
            return '', 204
        return jsonify({'ok': True, 'detail': '模拟器不支持地图保存，请使用 unified_backend'})

    @flask_app.route('/api/map/save_edited/health', methods=['GET', 'OPTIONS'])
    def api_health():
        return jsonify({'ok': True})


class RobotSimulator(Node):
    """
    机器人数据模拟器（大疆风格焦点跟随版）
    =======================================
    职责：
      1. 发布传感器数据（/battery_state, /odom, /map, /camera, /pointcloud）
      2. 发布 YOLO 检测结果（/yolo_detections, 10Hz）
      3. 订阅前端控制指令（/cmd_vel, /follow/roi, /follow/lock, /follow/config）
      4. 运行 Flask HTTP 服务（/api/follow/*）
      5. 根据跟随模式闭环驱动小车运动
    """

    def __init__(self):
        super().__init__('robot_simulator')

        # ============================================================
        # 机器人基础状态
        # ============================================================
        self.x = 5.0
        self.y = 3.0
        self.theta = 0.0
        self.linear_vel = 0.0
        self.angular_vel = 0.0
        self.speed = 0.0

        self.battery_percentage = 85.0
        self.voltage = 24.2
        self.battery_drain_rate = 0.01

        self.mode = 'MANUAL'
        self.safety_stopped = False
        self.cruise_enabled = False

        self.mapping_active = False
        self.localization_active = False
        self.navigation_active = False

        self.frame_count = 0
        self.lock = Lock()

        # ============================================================
        # 跟随系统状态
        # ============================================================
        # 模拟目标在画面中的像素坐标（640×480 画面）
        self._target_x = 320.0      # 目标中心 X（像素）
        self._target_y = 240.0      # 目标中心 Y（像素）
        self._target_w = 80.0       # 目标宽度（像素）
        self._target_h = 160.0      # 目标高度（像素）
        self._target_vx = 25.0      # 目标水平移动速度（像素/秒）
        self._target_time = 0.0     # 目标运动累计时间
        self._img_w = 640           # 模拟画面宽度
        self._img_h = 480           # 模拟画面高度

        # 仿真世界中的"虚拟行人"位置（用于跟随运动计算）
        self._person_world_x = 3.0
        self._person_world_y = 0.0
        self._person_vx = 0.3       # 行人世界坐标速度 m/s
        self._person_direction = 1  # 1=向右，-1=向左

        # ============================================================
        # 多线程：点云发布 + Flask 服务
        # ============================================================
        self._pcd_thread_running = Event()
        self._pcd_thread_running.set()
        self._latest_pose = (5.0, 3.0, 0.0)
        self._pcd_thread = Thread(target=self._pcd_worker, daemon=True, name='pcd_worker')

        # ============================================================
        # 摄像头
        # ============================================================
        self.cap = None
        if not _args.no_camera:
            self._init_camera()

        # ============================================================
        # 点云数据
        # ============================================================
        self.pcd_points = self._load_pcd(PCD_PATH)
        self.get_logger().info(f'加载点云: {len(self.pcd_points)} 个点 ({PCD_PATH})')

        # ============================================================
        # 模拟地图
        # ============================================================
        self.map_width = 800
        self.map_height = 600
        self.map_resolution = 0.05
        self.map_origin_x = -20.0
        self.map_origin_y = -15.0

        self.get_logger().info('机器人模拟器启动中...')

        # ============================================================
        # 发布器
        # ============================================================
        self.pub_pose = self.create_publisher(Pose, '/turtle1/pose', 10)
        self.pub_battery = self.create_publisher(BatteryState, '/battery_state', 10)
        self.pub_mode = self.create_publisher(String, '/robot_mode', 10)
        self.pub_odom = self.create_publisher(Odometry, '/odom', 10)

        qos_map = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            depth=1,
        )
        self.pub_map = self.create_publisher(OccupancyGrid, '/map', qos_map)
        self.pub_pointcloud = self.create_publisher(PointCloud2, '/terrain_points_downsampled', 10)
        self.pub_camera = self.create_publisher(CompressedImage, '/camera/image_raw', 10)

        # ★ 新增：YOLO 检测结果发布器
        self.pub_yolo = self.create_publisher(String, '/yolo_detections', 10)

        # ============================================================
        # 订阅器（原有 + 新增跟随话题）
        # ============================================================
        self.sub_cmd_vel = self.create_subscription(Twist, '/cmd_vel', self.on_cmd_vel, 10)
        self.sub_safety = self.create_subscription(Bool, '/safety_status', self.on_safety, 10)
        self.sub_cruise = self.create_subscription(Bool, '/cruise_cmd', self.on_cruise, 10)
        self.sub_goal = self.create_subscription(PoseStamped, '/goal_pose', self.on_goal, 10)
        self.sub_waypoints = self.create_subscription(String, '/waypoints_json', self.on_waypoints_json, 10)

        # ★ 新增：跟随系统订阅器
        self.sub_follow_roi = self.create_subscription(RegionOfInterest, '/follow/roi', self.on_follow_roi, 10)
        self.sub_follow_lock = self.create_subscription(Int32MultiArray, '/follow/lock', self.on_follow_lock, 10)
        self.sub_follow_config = self.create_subscription(String, '/follow/config', self.on_follow_config, 10)

        # ============================================================
        # 服务端
        # ============================================================
        self.srv_start_mapping = self.create_service(Trigger, '/start_mapping', self.on_start_mapping)
        self.srv_save_map = self.create_service(Trigger, '/save_map', self.on_save_map)
        self.srv_start_localization = self.create_service(Trigger, '/start_localization', self.on_start_localization)
        self.srv_navigate_to_pose = self.create_service(Trigger, '/navigate_to_pose', self.on_navigate_to_pose)

        # ============================================================
        # 定时器
        # ============================================================
        self.timer = self.create_timer(0.05, self.update)            # 20Hz 主循环
        self.timer_map = self.create_timer(3.0, self.publish_map)    # 每3秒发布地图
        self.timer_camera = self.create_timer(0.033, self.publish_camera)  # ~30fps 摄像头
        self.timer_yolo = self.create_timer(0.1, self.publish_yolo)  # ★ 10Hz YOLO 检测

        # ============================================================
        # 启动工作线程
        # ============================================================
        self._pcd_thread.start()

        # ============================================================
        # 启动 Flask HTTP 服务（独立线程）
        # ============================================================
        if flask_app is not None:
            _register_flask_routes()
            self._flask_thread = Thread(
                target=lambda: flask_app.run(
                    host='0.0.0.0', port=_args.port, debug=False, use_reloader=False,
                ),
                daemon=True, name='flask-http',
            )
            self._flask_thread.start()
            self.get_logger().info(f'Flask HTTP 服务启动 → 0.0.0.0:{_args.port}')
        else:
            self.get_logger().warn('Flask 不可用，/api/follow/* 端点将无法访问')

        self.get_logger().info('机器人模拟器启动完成')
        if _args.follow_debug:
            self.get_logger().info('★ 跟随调试模式已开启（详细日志）')

        self.publish_map()

    # ================================================================
    # 摄像头初始化
    # ================================================================
    def _init_camera(self):
        self.cap = None
        for dev in [0, 1, 2]:
            try:
                cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
                if cap.isOpened():
                    ret, _ = cap.read()
                    if ret:
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        self.cap = cap
                        self.get_logger().info(f'摄像头已打开 (设备 {dev})')
                        return
                    else:
                        cap.release()
                else:
                    cap.release()
            except Exception as e:
                self.get_logger().warn(f'尝试打开设备 {dev} 失败: {e}')
        self.get_logger().warn('无法打开摄像头，将发布合成帧')

    # ================================================================
    # PCD 文件加载
    # ================================================================
    def _load_pcd(self, path):
        points = []
        try:
            with open(path, 'rb') as f:
                header = []
                while True:
                    line = f.readline()
                    if not line:
                        break
                    header.append(line.decode('utf-8', errors='ignore').strip())
                    if 'DATA' in header[-1]:
                        break

                data_format = 'ascii'
                point_count = 0
                point_step = 0
                fields = []

                for line in header:
                    if line.startswith('DATA'):
                        data_format = line.split()[1]
                    elif line.startswith('POINTS'):
                        point_count = int(line.split()[1])
                    elif line.startswith('POINT_STEP'):
                        point_step = int(line.split()[1])
                    elif line.startswith('FIELDS'):
                        fields = line.split()[1:]

                if data_format == 'ascii':
                    for line in f:
                        try:
                            parts = line.decode('utf-8', errors='ignore').strip().split()
                            if len(parts) >= 4:
                                points.append((float(parts[0]), float(parts[1]),
                                               float(parts[2]), float(parts[3])))
                            elif len(parts) >= 3:
                                points.append((float(parts[0]), float(parts[1]),
                                               float(parts[2]), 0.0))
                        except Exception:
                            continue
                else:
                    if point_count > 0 and point_step > 0:
                        data = f.read(point_count * point_step)
                        x_idx = fields.index('x') if 'x' in fields else 0
                        y_idx = fields.index('y') if 'y' in fields else 1
                        z_idx = fields.index('z') if 'z' in fields else 2
                        intensity_idx = fields.index('intensity') if 'intensity' in fields else -1
                        for i in range(point_count):
                            offset = i * point_step
                            x = struct.unpack_from('<f', data, offset + x_idx * 4)[0]
                            y = struct.unpack_from('<f', data, offset + y_idx * 4)[0]
                            z = struct.unpack_from('<f', data, offset + z_idx * 4)[0]
                            intensity = (struct.unpack_from('<f', data, offset + intensity_idx * 4)[0]
                                         if intensity_idx >= 0 else 0.0)
                            points.append((x, y, z, intensity))
                    else:
                        data = f.read()
                        num_points = len(data) // 16
                        for i in range(num_points):
                            offset = i * 16
                            x = struct.unpack_from('<f', data, offset)[0]
                            y = struct.unpack_from('<f', data, offset + 4)[0]
                            z = struct.unpack_from('<f', data, offset + 8)[0]
                            intensity = struct.unpack_from('<f', data, offset + 12)[0]
                            points.append((x, y, z, intensity))

                self.get_logger().info(f'PCD格式: {data_format}, 点数: {len(points)}')
        except Exception as e:
            self.get_logger().error(f'加载 PCD 失败: {e}')
        return points

    # ================================================================
    # 主更新循环 (20Hz)
    # ================================================================
    def update(self):
        with self.lock:
            self._update_follow_motion()    # ★ 跟随运动计算
            self._update_motion()
            self._update_battery()
            self._publish_pose()
            self._publish_odom()            # ★ 里程计发布
            self._publish_battery()
            self._publish_mode()
            self._latest_pose = (self.x, self.y, self.theta)

    def _update_motion(self):
        if self.safety_stopped:
            self.linear_vel = 0.0
            self.angular_vel = 0.0
        dt = 0.05
        self.theta += self.angular_vel * dt
        self.x += self.linear_vel * math.cos(self.theta) * dt
        self.y += self.linear_vel * math.sin(self.theta) * dt
        self.speed = abs(self.linear_vel)
        self.x = max(-18.0, min(18.0, self.x))
        self.y = max(-13.0, min(13.0, self.y))

    def _update_battery(self):
        if not self.safety_stopped and abs(self.linear_vel) > 0.01:
            self.battery_percentage -= self.battery_drain_rate
        if self.battery_percentage < 20:
            self.battery_percentage += 0.002
        self.battery_percentage = max(5.0, min(100.0, self.battery_percentage))
        self.voltage = 24.0 * (self.battery_percentage / 100.0) + 0.2

    # ================================================================
    # ★ 跟随运动闭环（20Hz 由 update() 调用）
    # ================================================================
    def _update_follow_motion(self):
        """
        根据当前跟随模式，自动驱动小车底盘速度。
        仅在跟随激活 且 目标已锁定 时生效。
        """
        if not _follow_get('active') or not _follow_get('target_locked'):
            return

        follow_mode = _follow_get('follow_mode')

        # 1. 更新虚拟行人在世界坐标系中的运动（简单左右来回）
        self._person_world_x += self._person_vx * 0.05 * self._person_direction
        if self._person_world_x > 10.0:
            self._person_direction = -1
        elif self._person_world_x < -10.0:
            self._person_direction = 1

        # 2. 根据跟随模式计算目标线速度
        target_vx = 0.0
        target_vy = 0.0
        target_wz = 0.0
        follow_speed = 0.35  # 跟随基准速度 (m/s)

        if follow_mode == 'trace':
            # ── 尾随追踪：保持在目标正后方 ──
            # 小车 X 追踪行人 X，小车 Y 保持在行人后方 (person_y - 2.0)
            dx = self._person_world_x - self.x
            dy = (self._person_world_y - 2.0) - self.y
            dist = math.hypot(dx, dy)
            if dist > 0.3:
                target_vx = follow_speed * (dx / dist)
                target_vy = follow_speed * (dy / dist)
            # 朝向：始终面向行人方向
            target_angle = math.atan2(
                self._person_world_y - self.y,
                self._person_world_x - self.x,
            )
            angle_diff = target_angle - self.theta
            while angle_diff > math.pi:
                angle_diff -= 2 * math.pi
            while angle_diff < -math.pi:
                angle_diff += 2 * math.pi
            target_wz = 1.5 * angle_diff  # 比例控制转向

        elif follow_mode == 'parallel':
            # ── 平行跟随：保持在目标侧方同速移动 ──
            dx = self._person_world_x - self.x
            dy = (self._person_world_y + 2.5) - self.y  # 目标右侧 2.5m
            dist = math.hypot(dx, dy)
            if dist > 0.3:
                target_vx = follow_speed * (dx / dist)
                target_vy = follow_speed * (dy / dist)
            # 朝向：与行人行进方向一致
            target_angle = 0.0 if self._person_direction > 0 else math.pi
            angle_diff = target_angle - self.theta
            while angle_diff > math.pi:
                angle_diff -= 2 * math.pi
            while angle_diff < -math.pi:
                angle_diff += 2 * math.pi
            target_wz = 1.5 * angle_diff

        elif follow_mode == 'orbit':
            # ── 环绕监视：以行人为中心做圆周运动 ──
            orbit_radius = 3.0
            orbit_speed = 0.6  # 角速度 rad/s
            # 行人当前位置
            person_x = self._person_world_x
            person_y = self._person_world_y
            # 小车当前角度（相对于行人）
            dx = self.x - person_x
            dy = self.y - person_y
            current_angle = math.atan2(dy, dx)
            current_dist = math.hypot(dx, dy)
            # 目标角度（沿圆周前进）
            target_angle = current_angle + orbit_speed * 0.05
            # 目标位置
            target_x = person_x + orbit_radius * math.cos(target_angle)
            target_y = person_y + orbit_radius * math.sin(target_angle)
            tdx = target_x - self.x
            tdy = target_y - self.y
            tdist = math.hypot(tdx, tdy)
            if tdist > 0.1:
                target_vx = follow_speed * 1.2 * (tdx / tdist)
                target_vy = follow_speed * 1.2 * (tdy / tdist)
            # 朝向：始终面向圆心（行人）
            look_angle = math.atan2(person_y - self.y, person_x - self.x)
            angle_diff = look_angle - self.theta
            while angle_diff > math.pi:
                angle_diff -= 2 * math.pi
            while angle_diff < -math.pi:
                angle_diff += 2 * math.pi
            target_wz = 2.0 * angle_diff

        # 3. 平滑过渡（一阶低通滤波，避免突变抖动）
        smooth = 0.15
        self.linear_vel = self.linear_vel * (1 - smooth) + target_vx * smooth
        self.angular_vel = self.angular_vel * (1 - smooth) + target_wz * smooth
        # Y 轴通过横向速度隐式实现（这里用侧向偏移模拟）
        self.y += target_vy * 0.05 * smooth

        if _args.follow_debug:
            self.get_logger().info(
                f'[Follow:{follow_mode}] 人=({self._person_world_x:.2f},{self._person_world_y:.2f}) '
                f'车=({self.x:.2f},{self.y:.2f}) vel=({self.linear_vel:.3f},{self.angular_vel:.3f})'
            )

    # ================================================================
    # ★ YOLO 检测目标运动模拟（10Hz 由 timer_yolo 调用）
    # ================================================================
    def _update_target_position(self, dt):
        """
        在 640×480 画面中模拟一个动态行人目标。
        运动轨迹：水平匀速 + 垂直正弦波 + 高斯抖动。
        """
        self._target_time += dt

        # 水平运动：从左到右匀速，到边界后反向
        self._target_x += self._target_vx * dt
        if self._target_x > self._img_w - self._target_w / 2:
            self._target_vx = -abs(self._target_vx)
        elif self._target_x < self._target_w / 2:
            self._target_vx = abs(self._target_vx)

        # 垂直运动：正弦波漂移
        self._target_y = (self._img_h / 2
                          + 60 * math.sin(self._target_time * 0.8)
                          + random.gauss(0, 3))

        # 高斯抖动（模拟检测框不稳定）
        self._target_x += random.gauss(0, 1.5)
        self._target_y += random.gauss(0, 1.5)

        # 边界裁剪
        half_w = self._target_w / 2
        half_h = self._target_h / 2
        self._target_x = max(half_w, min(self._img_w - half_w, self._target_x))
        self._target_y = max(half_h, min(self._img_h - half_h, self._target_y))

    # ================================================================
    # ★ 发布 /yolo_detections（10Hz 定时器回调）
    # ================================================================
    def publish_yolo(self):
        """
        发布模拟的 YOLO 检测结果。
        消息格式（JSON via std_msgs/String）：
        {
          "header": {"stamp": ..., "frame_id": "camera_link"},
          "detections": [{"x_min":..., "y_min":..., "x_max":..., "y_max":...}, ...],
          "confidences": [0.85, ...],
          "class_ids": [0, ...],
          "class_names": ["person", ...],
          "image_width": 640,
          "image_height": 480
        }
        """
        active = _follow_get('active')
        scan = _follow_get('scan_enabled')

        if not active or not scan:
            return

        dt = 0.1  # 10Hz
        self._update_target_position(dt)

        # 构造检测框
        x_min = self._target_x - self._target_w / 2
        y_min = self._target_y - self._target_h / 2
        x_max = self._target_x + self._target_w / 2
        y_max = self._target_y + self._target_h / 2

        # 基础置信度（锁定后置信度更高更稳定）
        locked = _follow_get('target_locked')
        base_conf = 0.92 if locked else 0.85
        confidence = base_conf + random.gauss(0, 0.02)
        confidence = max(0.35, min(0.99, confidence))

        # 构造消息 payload
        now = self.get_clock().now().to_msg()
        payload = {
            'header': {
                'stamp': {'sec': now.sec, 'nanosec': now.nanosec},
                'frame_id': 'camera_link',
            },
            'detections': [{
                'x_min': round(x_min, 1),
                'y_min': round(y_min, 1),
                'x_max': round(x_max, 1),
                'y_max': round(y_max, 1),
            }],
            'confidences': [round(confidence, 3)],
            'class_ids': [0],
            'class_names': ['person'],
            'image_width': self._img_w,
            'image_height': self._img_h,
        }

        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.pub_yolo.publish(msg)

        if _args.follow_debug:
            lock_info = ' [LOCKED]' if locked else ''
            self.get_logger().info(
                f'[YOLO] target=({self._target_x:.0f},{self._target_y:.0f}) '
                f'conf={confidence:.3f}{lock_info}'
            )

    # ================================================================
    # ★ /follow/roi 话题回调（接收前端框选 ROI）
    # ================================================================
    def on_follow_roi(self, msg: RegionOfInterest):
        """前端在画面上框选目标区域后，通过 ROS 话题发送 ROI"""
        roi = {
            'x_min': msg.x_offset,
            'y_min': msg.y_offset,
            'x_max': msg.x_offset + msg.width,
            'y_max': msg.y_offset + msg.height,
        }
        _follow_set(roi=roi, target_locked=True,
                     locked_class_name='roi_selection',
                     locked_bbox=roi)
        self.get_logger().info(f'[Follow] ROI 已接收: {roi}')

    # ================================================================
    # ★ /follow/lock 话题回调（接收前端点击锁定目标）
    # ================================================================
    def on_follow_lock(self, msg: Int32MultiArray):
        """
        前端点击绿色 YOLO 标记后，发送锁定指令。
        data = [class_id, target_id, x_min, y_min, x_max, y_max]
        """
        data = msg.data
        if len(data) < 6:
            return
        class_id = data[0]
        target_id = data[1]
        bbox = {
            'x_min': data[2], 'y_min': data[3],
            'x_max': data[4], 'y_max': data[5],
        }

        if class_id == -1:
            # 解除锁定
            _follow_set(target_locked=False, locked_bbox=None)
            self.get_logger().info('[Follow] 目标锁定已解除')
        else:
            _follow_set(
                target_locked=True,
                locked_class_id=class_id,
                locked_class_name='person',
                locked_confidence=0.92,
                locked_bbox=bbox,
            )
            self.get_logger().info(
                f'[Follow] 目标已锁定: class={class_id} id={target_id} bbox={bbox}'
            )

    # ================================================================
    # ★ /follow/config 话题回调（接收跟随模式切换）
    # ================================================================
    def on_follow_config(self, msg: String):
        """前端切换跟随模式时，通过 ROS 话题发送配置"""
        try:
            data = json.loads(msg.data)
            mode = data.get('mode', 'trace')
        except (json.JSONDecodeError, AttributeError):
            mode = msg.data.strip()

        if mode in ('parallel', 'trace', 'orbit'):
            _follow_set(follow_mode=mode)
            labels = {'parallel': '平行跟随', 'trace': '尾随追踪', 'orbit': '环绕监视'}
            self.get_logger().info(f'[Follow] 模式切换: {labels.get(mode, mode)}')

    # ================================================================
    # 发布: /turtle1/pose
    # ================================================================
    def _publish_pose(self):
        msg = Pose()
        msg.position.x = self.x
        msg.position.y = self.y
        msg.position.z = 0.0
        msg.orientation.z = math.sin(self.theta / 2.0)
        msg.orientation.w = math.cos(self.theta / 2.0)
        self.pub_pose.publish(msg)

    # ================================================================
    # ★ 发布: /odom（里程计，配合前端 MapCanvas 小车图标移动）
    # ================================================================
    def _publish_odom(self):
        msg = Odometry()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'odom'
        msg.child_frame_id = 'base_link'

        # 位姿
        msg.pose.pose.position.x = self.x
        msg.pose.pose.position.y = self.y
        msg.pose.pose.position.z = 0.0
        msg.pose.pose.orientation.z = math.sin(self.theta / 2.0)
        msg.pose.pose.orientation.w = math.cos(self.theta / 2.0)

        # 速度
        msg.twist.twist.linear.x = self.linear_vel
        msg.twist.twist.linear.y = 0.0
        msg.twist.twist.linear.z = 0.0
        msg.twist.twist.angular.x = 0.0
        msg.twist.twist.angular.y = 0.0
        msg.twist.twist.angular.z = self.angular_vel

        self.pub_odom.publish(msg)

    # ================================================================
    # 发布: /battery_state
    # ================================================================
    def _publish_battery(self):
        msg = BatteryState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.percentage = self.battery_percentage / 100.0
        msg.voltage = self.voltage
        msg.current = -0.5 if abs(self.linear_vel) > 0.01 else -0.05
        msg.design_capacity = 1.0
        self.pub_battery.publish(msg)

    # ================================================================
    # 发布: /robot_mode
    # ================================================================
    def _publish_mode(self):
        msg = String()
        if self.safety_stopped:
            msg.data = 'EMERGENCY'
        elif _follow_get('active') and _follow_get('target_locked'):
            msg.data = 'AUTO'       # 跟随锁定时显示 AUTO 模式
        elif self.navigation_active:
            msg.data = 'AUTO'
        else:
            msg.data = 'MANUAL'
        self.mode = msg.data
        self.pub_mode.publish(msg)

    # ================================================================
    # 发布: /map
    # ================================================================
    def publish_map(self):
        msg = OccupancyGrid()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'map'

        msg.info = MapMetaData()
        msg.info.resolution = self.map_resolution
        msg.info.width = self.map_width
        msg.info.height = self.map_height
        msg.info.origin.position.x = self.map_origin_x
        msg.info.origin.position.y = self.map_origin_y
        msg.info.origin.position.z = 0.0
        msg.info.origin.orientation.w = 1.0

        w, h = self.map_width, self.map_height
        data = [0] * (w * h)
        for i in range(w * h):
            x = i % w
            y = i // w
            if x == 0 or x == w - 1 or y == 0 or y == h - 1:
                data[i] = 100
            elif 100 < x < 120 and 100 < y < 400:
                data[i] = 100
            elif 200 < y < 220 and 200 < x < 500:
                data[i] = 100
            elif random.random() < 0.015 and x > 50 and y > 50:
                data[i] = 100
        msg.data = data
        self.pub_map.publish(msg)

    # ================================================================
    # 点云发布（独立线程）
    # ================================================================
    def _pcd_worker(self):
        while self._pcd_thread_running.is_set():
            try:
                with self.lock:
                    px, py, ptheta = self._latest_pose
                self._publish_pointcloud_at(px, py, ptheta)
            except Exception as e:
                self.get_logger().error(f'点云线程异常: {e}')
            self._pcd_thread_running.wait(0.05)

    def _publish_pointcloud_at(self, px, py, ptheta):
        if not self.pcd_points:
            return

        msg = PointCloud2()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'map'

        msg.height = 1
        msg.fields = [
            PointField(name='x', offset=0, datatype=PointField.FLOAT32, count=1),
            PointField(name='y', offset=4, datatype=PointField.FLOAT32, count=1),
            PointField(name='z', offset=8, datatype=PointField.FLOAT32, count=1),
            PointField(name='intensity', offset=12, datatype=PointField.FLOAT32, count=1),
        ]
        msg.is_bigendian = False
        msg.point_step = 16
        msg.row_step = 0

        cos_t = math.cos(ptheta)
        sin_t = math.sin(ptheta)

        flat = [0.0] * (len(self.pcd_points) * 4)
        for i, (x, y, z, intensity) in enumerate(self.pcd_points):
            base = i * 4
            flat[base] = px + x * cos_t - y * sin_t
            flat[base + 1] = py + x * sin_t + y * cos_t
            flat[base + 2] = z
            flat[base + 3] = intensity

        msg.width = len(self.pcd_points)
        msg.row_step = msg.point_step * msg.width
        msg.is_dense = True
        msg.data = struct.pack(f'<{len(flat)}f', *flat)
        self.pub_pointcloud.publish(msg)

    # ================================================================
    # 发布: /camera/image_raw（带跟随 HUD 叠加层）
    # ================================================================
    def publish_camera(self):
        self.frame_count += 1
        msg = CompressedImage()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'camera_link'
        msg.format = 'jpeg'

        if self.cap is not None and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                self._draw_camera_hud(frame)
                _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                msg.data = jpeg.tobytes()
            else:
                frame = self._generate_synthetic_frame()
                _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                msg.data = jpeg.tobytes()
        else:
            frame = self._generate_synthetic_frame()
            _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
            msg.data = jpeg.tobytes()

        self.pub_camera.publish(msg)

    def _generate_synthetic_frame(self):
        """无摄像头时生成合成画面（含跟随目标指示）"""
        h, w = self._img_h, self._img_w
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        # 深灰背景 + 网格线
        frame[:] = (30, 30, 30)
        for gx in range(0, w, 40):
            cv2.line(frame, (gx, 0), (gx, h), (50, 50, 50), 1)
        for gy in range(0, h, 40):
            cv2.line(frame, (0, gy), (w, gy), (50, 50, 50), 1)
        # 中心十字准心
        cx, cy = w // 2, h // 2
        cv2.line(frame, (cx - 30, cy), (cx + 30, cy), (0, 200, 0), 1)
        cv2.line(frame, (cx, cy - 30), (cx, cy + 30), (0, 200, 0), 1)
        # HUD 文字
        cv2.putText(frame, f'SIM {self.frame_count:06d}', (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 255), 2)
        info = f'X:{self.x:.2f} Y:{self.y:.2f}'
        cv2.putText(frame, info, (10, h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        return frame

    def _draw_camera_hud(self, frame):
        """在真实摄像头画面上叠加 HUD 信息 + 跟随目标框"""
        h, w = frame.shape[:2]
        self._img_w = w
        self._img_h = h

        # 基础 HUD
        cv2.putText(frame, f'SIM {self.frame_count:06d}', (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 255), 2)

        # 十字准心
        cx, cy = w // 2, h // 2
        cv2.line(frame, (cx - 30, cy), (cx + 30, cy), (0, 255, 0), 2)
        cv2.line(frame, (cx, cy - 30), (cx, cy + 30), (0, 255, 0), 2)

        # 位姿信息
        info = f'X:{self.x:.2f} Y:{self.y:.2f} TH:{math.degrees(self.theta):.1f}'
        cv2.putText(frame, info, (10, h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        vel_text = f'V:{self.linear_vel:.2f} W:{self.angular_vel:.2f}'
        cv2.putText(frame, vel_text, (10, h - 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # ★ 跟随模式指示
        if _follow_get('active'):
            mode = _follow_get('follow_mode')
            locked = _follow_get('target_locked')
            labels = {'parallel': 'PARALLEL', 'trace': 'TRACE', 'orbit': 'ORBIT'}
            mode_text = labels.get(mode, mode)
            color = (0, 255, 0) if locked else (0, 165, 255)
            status_text = f'FOLLOW: {mode_text}'
            if locked:
                status_text += ' [LOCKED]'
            cv2.putText(frame, status_text, (w - 280, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

            # 绘制模拟目标框
            tx = int(self._target_x)
            ty = int(self._target_y)
            tw = int(self._target_w)
            th = int(self._target_h)
            bx1 = max(0, tx - tw // 2)
            by1 = max(0, ty - th // 2)
            bx2 = min(w, tx + tw // 2)
            by2 = min(h, ty + th // 2)
            cv2.rectangle(frame, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
            # 绿色十字标记
            cv2.drawMarker(frame, (tx, ty), (0, 255, 0),
                           cv2.MARKER_CROSS, 16, 2)

    # ================================================================
    # 回调: /cmd_vel
    # ================================================================
    def on_cmd_vel(self, msg: Twist):
        with self.lock:
            if not self.safety_stopped:
                # 如果正在跟随锁定状态，忽略手动 cmd_vel（避免冲突）
                if _follow_get('active') and _follow_get('target_locked'):
                    return
                self.linear_vel = msg.linear.x
                self.angular_vel = msg.angular.z

        if not (_follow_get('active') and _follow_get('target_locked')):
            linear = msg.linear.x
            angular = msg.angular.z
            status = self._classify_cmd(linear, angular)
            self.get_logger().info(
                f'[控制] {status} | L:{linear:.2f} A:{angular:.2f}'
            )

    @staticmethod
    def _classify_cmd(linear, angular):
        DEAD = 0.05
        lin_ok = abs(linear) >= DEAD
        ang_ok = abs(angular) >= DEAD
        if lin_ok and not ang_ok:
            return '前进' if linear > 0 else '后退'
        if ang_ok and not lin_ok:
            return '左转' if angular > 0 else '右转'
        if lin_ok and angular > 0:
            return '左前弯'
        if lin_ok and angular < 0:
            return '右前弯'
        return '停止'

    # ================================================================
    # 回调: /safety_status, /cruise_cmd, /goal_pose, /waypoints_json
    # ================================================================
    def on_safety(self, msg: Bool):
        with self.lock:
            self.safety_stopped = msg.data
            if self.safety_stopped:
                self.linear_vel = 0.0
                self.angular_vel = 0.0
            self.get_logger().warn(f'急停: {"已触发" if self.safety_stopped else "已解除"}')

    def on_cruise(self, msg: Bool):
        with self.lock:
            self.cruise_enabled = msg.data
            self.get_logger().info(f'巡航: {"开启" if self.cruise_enabled else "关闭"}')

    def on_goal(self, msg: PoseStamped):
        self.get_logger().info(
            f'导航目标: ({msg.pose.position.x:.2f}, {msg.pose.position.y:.2f})'
        )

    def on_waypoints_json(self, msg: String):
        try:
            data = json.loads(msg.data)
            waypoints = data.get('waypoints', [])
            count = data.get('count', 0)
            path_name = data.get('path', {}).get('name', '未知')
            self.get_logger().info(f'收到航点数据: {count} 个航点, 路线: {path_name}')
            for i, wp in enumerate(waypoints):
                self.get_logger().info(
                    f'  航点 {i+1}: {wp.get("name", "")} '
                    f'({wp.get("x", 0):.2f}, {wp.get("y", 0):.2f})'
                )
        except Exception as e:
            self.get_logger().error(f'解析航点JSON失败: {e}')

    # ================================================================
    # 服务回调
    # ================================================================
    def on_start_mapping(self, request, response):
        self.mapping_active = True
        response.success = True
        response.message = '建图已开始'
        return response

    def on_save_map(self, request, response):
        response.success = True
        response.message = '地图已保存'
        return response

    def on_start_localization(self, request, response):
        self.localization_active = True
        response.success = True
        response.message = '定位已启动'
        return response

    def on_navigate_to_pose(self, request, response):
        self.navigation_active = True
        response.success = True
        response.message = '导航已启动'
        return response


def main(args=None):
    rclpy.init(args=args)
    node = RobotSimulator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._pcd_thread_running.clear()
        node._pcd_thread.join(timeout=2.0)
        if node.cap is not None:
            node.cap.release()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
