#!/usr/bin/env python3
"""
ROS2 机器人数据模拟器
用于 Ubuntu 22.04 + ROS2 Humble + rosbridge
- 摄像头: 使用电脑自带摄像头 (OpenCV)
- 点云: 从 test.pcd 文件读取
- 发布/订阅话题与前端的 inspection-platform 一致

用法:
  pip install opencv-python Pillow
  python3 robot_simulator.py
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, DurabilityPolicy

import math
import struct
import random
import os
import cv2
import numpy as np
from threading import Lock, Thread, Event

from geometry_msgs.msg import Pose, Twist, PoseStamped
from sensor_msgs.msg import BatteryState, CompressedImage, PointCloud2, PointField
from std_msgs.msg import String, Bool, Header
from nav_msgs.msg import OccupancyGrid, MapMetaData
from std_srvs.srv import Trigger

PCD_PATH = 'test.pcd'


class RobotSimulator(Node):
    """模拟机器人数据，使前端能完整展示"""

    def __init__(self):
        super().__init__('robot_simulator')

        # ============================================================
        # 机器人状态变量
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

        # 多线程点云发布
        self._pcd_thread_running = Event()
        self._pcd_thread_running.set()
        self._latest_pose = (5.0, 3.0, 0.0)  # (x, y, theta) 供工作线程读取
        self._pcd_thread = Thread(target=self._pcd_worker, daemon=True, name='pcd_worker')

        # ============================================================
        # 摄像头 (电脑自带)
        # ============================================================
        self.cap = None
        self._init_camera()

        # ============================================================
        # 点云数据 (从 test.pcd 加载)
        # ============================================================
        self.pcd_points = self._load_pcd(PCD_PATH)
        self.get_logger().info(f'加载点云: {len(self.pcd_points)} 个点 ({PCD_PATH})')

        # ============================================================
        # 模拟地图参数
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

        qos_map = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            depth=1
        )
        self.pub_map = self.create_publisher(OccupancyGrid, '/map', qos_map)
        self.pub_pointcloud = self.create_publisher(PointCloud2, '/terrain_points_downsampled', 10)
        self.pub_camera = self.create_publisher(CompressedImage, '/camera/image_raw', 10)

        # ============================================================
        # 订阅器
        # ============================================================
        self.sub_cmd_vel = self.create_subscription(Twist, '/cmd_vel', self.on_cmd_vel, 10)
        self.sub_safety = self.create_subscription(Bool, '/safety_status', self.on_safety, 10)
        self.sub_cruise = self.create_subscription(Bool, '/cruise_cmd', self.on_cruise, 10)
        self.sub_goal = self.create_subscription(PoseStamped, '/goal_pose', self.on_goal, 10)
        self.sub_waypoints = self.create_subscription(String, '/waypoints_json', self.on_waypoints_json, 10)

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
        self.timer = self.create_timer(0.05, self.update)        # 20Hz 主循环
        self.timer_map = self.create_timer(3.0, self.publish_map)  # 每3秒地图
        self.timer_camera = self.create_timer(0.033, self.publish_camera)  # ~30fps

        self._pcd_thread.start()
        self.get_logger().info('机器人模拟器启动完成')

        self.publish_map()

    # ================================================================
    # 摄像头初始化
    # ================================================================
    def _init_camera(self):
        self.cap = None
        devices = [0, 1, 2]
        for dev in devices:
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
        
        self.get_logger().warn('无法打开摄像头，将发布空帧')

    # ================================================================
    # PCD 文件加载
    # ================================================================
    def _load_pcd(self, path):
        """加载 PCD 文件（支持 ASCII 和 binary 格式），返回 [(x, y, z, intensity), ...]"""
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
                                x, y, z, intensity = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
                                points.append((x, y, z, intensity))
                            elif len(parts) >= 3:
                                x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                                points.append((x, y, z, 0.0))
                        except:
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
                            intensity = struct.unpack_from('<f', data, offset + intensity_idx * 4)[0] if intensity_idx >= 0 else 0.0
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
            self._update_motion()
            self._update_battery()
            self._publish_pose()
            self._publish_battery()
            self._publish_mode()
            # 点云发布已移到独立线程 _pcd_worker
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
    # 发布: /turtle1/pose
    # ================================================================
    def _publish_pose(self):
        msg = Pose()
        msg.position.x = self.x
        msg.position.y = self.y
        msg.position.z = 0.0
        qz = math.sin(self.theta / 2.0)
        qw = math.cos(self.theta / 2.0)
        msg.orientation.x = 0.0
        msg.orientation.y = 0.0
        msg.orientation.z = qz
        msg.orientation.w = qw
        self.pub_pose.publish(msg)

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
    # 多线程工作: 独立线程发布点云 (避免阻塞主循环)
    # ================================================================
    def _pcd_worker(self):
        """在独立线程中持续发布点云，释放主循环压力"""
        while self._pcd_thread_running.is_set():
            try:
                with self.lock:
                    px, py, ptheta = self._latest_pose
                self._publish_pointcloud_at(px, py, ptheta)
            except Exception as e:
                self.get_logger().error(f'点云线程异常: {e}')
            self._pcd_thread_running.wait(0.05)  # 20Hz

    def _publish_pointcloud_at(self, px, py, ptheta):
        """使用指定位姿发布点云（供工作线程调用，省去重复加锁）"""
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
    # 发布: /camera/image_raw (从电脑摄像头读取)
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
                # 在画面叠加 HUD 信息
                h, w = frame.shape[:2]
                cv2.putText(frame, f'ROBOT SIM {self.frame_count:06d}', (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 255), 2)
                # 十字准心
                cx, cy = w // 2, h // 2
                cv2.line(frame, (cx - 30, cy), (cx + 30, cy), (0, 255, 0), 2)
                cv2.line(frame, (cx, cy - 30), (cx, cy + 30), (0, 255, 0), 2)
                # 位姿
                info = f'X:{self.x:.2f} Y:{self.y:.2f} TH:{math.degrees(self.theta):.1f}'
                cv2.putText(frame, info, (10, h - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                vel_text = f'V:{self.linear_vel:.2f} W:{self.angular_vel:.2f}'
                cv2.putText(frame, vel_text, (10, h - 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                # 编码为 JPEG
                _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                msg.data = jpeg.tobytes()
            else:
                self._fallback_jpeg(msg)
        else:
            self._fallback_jpeg(msg)

        self.pub_camera.publish(msg)

    def _fallback_jpeg(self, msg):
        """摄像头不可用时生成占位图"""
        w, h = 320, 240
        img = np.zeros((h, w, 3), dtype=np.uint8)
        cv2.putText(img, 'Camera Unavailable', (30, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        _, jpeg = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 50])
        msg.data = jpeg.tobytes()

    # ================================================================
    # 回调: /cmd_vel
    # ================================================================
    def on_cmd_vel(self, msg: Twist):
        with self.lock:
            if not self.safety_stopped:
                self.linear_vel = msg.linear.x
                self.angular_vel = msg.angular.z
                self.get_logger().info(f'速度指令: V={msg.linear.x:.2f} W={msg.angular.z:.2f}')

    # ================================================================
    # 回调: /safety_status
    # ================================================================
    def on_safety(self, msg: Bool):
        with self.lock:
            self.safety_stopped = msg.data
            if self.safety_stopped:
                self.linear_vel = 0.0
                self.angular_vel = 0.0
            self.get_logger().warn(f'急停: {"已触发" if self.safety_stopped else "已解除"}')

    # ================================================================
    # 回调: /cruise_cmd
    # ================================================================
    def on_cruise(self, msg: Bool):
        with self.lock:
            self.cruise_enabled = msg.data
            self.get_logger().info(f'巡航: {"开启" if self.cruise_enabled else "关闭"}')

    # ================================================================
    # 回调: /goal_pose
    # ================================================================
    def on_goal(self, msg: PoseStamped):
        self.get_logger().info(
            f'导航目标: ({msg.pose.position.x:.2f}, {msg.pose.position.y:.2f})'
        )

    # ================================================================
    # 回调: /waypoints_json
    # ================================================================
    def on_waypoints_json(self, msg: String):
        try:
            import json
            data = json.loads(msg.data)
            waypoints = data.get('waypoints', [])
            count = data.get('count', 0)
            path_name = data.get('path', {}).get('name', '未知')
            
            self.get_logger().info(f'收到航点数据: {count} 个航点, 路线: {path_name}')
            
            for i, wp in enumerate(waypoints):
                self.get_logger().info(f'  航点 {i+1}: {wp.get("name", "")} ({wp.get("x", 0):.2f}, {wp.get("y", 0):.2f})')
            
            output_path = f'/home/xysh/waypoints_{data.get("timestamp", "unknown")}.json'
            with open(output_path, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.get_logger().info(f'航点数据已保存到: {output_path}')
            
        except Exception as e:
            self.get_logger().error(f'解析航点JSON失败: {e}')

    # ================================================================
    # 服务
    # ================================================================
    def on_start_mapping(self, request, response):
        self.mapping_active = True
        response.success = True
        response.message = '建图已开始'
        self.get_logger().info('服务: 开始建图')
        return response

    def on_save_map(self, request, response):
        response.success = True
        response.message = '地图已保存'
        self.get_logger().info('服务: 保存地图')
        return response

    def on_start_localization(self, request, response):
        self.localization_active = True
        response.success = True
        response.message = '定位已启动'
        self.get_logger().info('服务: 开始定位')
        return response

    def on_navigate_to_pose(self, request, response):
        self.navigation_active = True
        response.success = True
        response.message = '导航已启动'
        self.get_logger().info('服务: 开始导航')
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
