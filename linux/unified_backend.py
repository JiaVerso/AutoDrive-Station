#!/usr/bin/env python3
"""
unified_backend.py — 统一后端服务
===================================
合并 map_edit_server + inspection_controller + task_chain_manager 到一个进程。

线程架构：
  主线程          Flask HTTP 服务（端口 5000）+ 一键跟随子进程管理
  守护线程 A      InspectionController（ROS 2 巡检节点 + QoS 桥接 + TF 发布）
  守护线程 B      TaskChainManager（ROS 2 任务链状态机）

环境变量（与各原文件保持一致）：
  PORT               Flask 端口（默认 5000）
  MAPS_DIR           地图目录
  ROS_DISTRO         ROS 2 发行版（默认 humble）
  ROS_SETUP          ROS 2 setup.bash 路径
  WS_SETUP           小车工作区 install/setup.bash 路径
  MAP_SERVER_NODE    map_server 节点名（默认 /map_server）
  FOLLOW_SCRIPT_DIR  yolo_follow.sh 所在目录

启动：
  PORT=5000 MAPS_DIR=/path/to/maps python3 unified_backend.py
"""

# ================================================================
# 通用导入
# ================================================================
import os
import sys
import math
import json
import time
import signal
import subprocess
import threading
from datetime import datetime

# ================================================================
# 环境配置（所有模块共享）
# ================================================================
MAPS_DIR = os.environ.get("MAPS_DIR", "/maps")
PORT = int(os.environ.get("PORT", "5000"))

FOLLOW_SCRIPT_DIR = os.environ.get(
    "FOLLOW_SCRIPT_DIR",
    os.path.expanduser("~/Desktop/SparkCar_ROS2_WS/scripts"),
)
FOLLOW_SCRIPT = os.path.join(FOLLOW_SCRIPT_DIR, "yolo_follow.sh")

ROS_DISTRO = os.environ.get("ROS_DISTRO", "humble")
ROS_SETUP = os.environ.get(
    "ROS_SETUP",
    f"/opt/ros/{ROS_DISTRO}/setup.bash",
)
WS_SETUP = os.environ.get(
    "WS_SETUP",
    os.path.expanduser(
        "~/Desktop/SparkCar_ROS2_WS/SparkCar_Navigation/install/setup.bash"
    ),
)
MAP_SERVER_NODE = os.environ.get("MAP_SERVER_NODE", "/map_server")

_follow_proc: subprocess.Popen | None = None

# ================================================================
# Flask 应用
# ================================================================
from flask import Flask, request as flask_request, jsonify
from flask_cors import CORS
import numpy as np

app = Flask(__name__)
CORS(app)


def _ros2_source_prefix() -> str:
    parts = []
    if os.path.isfile(ROS_SETUP):
        parts.append(f"source {ROS_SETUP}")
    if os.path.isfile(WS_SETUP):
        parts.append(f"source {WS_SETUP}")
    return " && ".join(parts)


# ================================================================
# 地图编辑接口
# ================================================================

def save_edited_map(width: int, height: int, resolution: float,
                    origin: dict, grid_data) -> str:
    os.makedirs(MAPS_DIR, exist_ok=True)
    pgm_path = os.path.join(MAPS_DIR, "main.pgm")
    yaml_path = os.path.join(MAPS_DIR, "main.yaml")

    arr = np.asarray(grid_data, dtype=np.uint8)
    img = np.where(arr == 0, 254, np.where(arr == 100, 0, 205)).astype(np.uint8)
    matrix = img.reshape((height, width))
    matrix = np.flipud(matrix)

    with open(pgm_path, "wb") as f:
        f.write(f"P5\n{width} {height}\n255\n".encode("ascii"))
        f.write(matrix.tobytes())

    ox = float(origin.get("x", 0.0))
    oy = float(origin.get("y", 0.0))
    yaml_content = (
        "image: main.pgm\n"
        f"resolution: {resolution}\n"
        f"origin: [{ox}, {oy}, 0.0]\n"
        "negate: 0\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.196\n"
    )
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    return pgm_path


def reload_ros_map(yaml_path: str) -> dict:
    prefix = _ros2_source_prefix()
    if not prefix:
        return {"ok": False, "method": "none",
                "detail": "未找到 ROS 2 setup.bash，跳过地图重载"}

    node = MAP_SERVER_NODE
    chain = [
        f"ros2 lifecycle set {node} deactivate",
        f"ros2 lifecycle set {node} cleanup",
        f"ros2 lifecycle set {node} configure",
        f"ros2 lifecycle set {node} activate",
    ]
    try:
        full = f"{prefix} && " + " && ".join(chain)
        res = subprocess.run(
            ["bash", "-c", full],
            capture_output=True, text=True, timeout=30,
        )
        out = (res.stdout or "") + (res.stderr or "")
        if "error" in out.lower() or "unrecognized" in out.lower():
            print(f"【地图重载】方案A 状态链存在异常，回退方案B。输出: {out.strip()}")
        else:
            return {"ok": True, "method": "lifecycle",
                    "detail": "已通过 lifecycle 状态链重置 map_server 并重新读盘"}
    except Exception as e:
        print(f"【地图重载】方案A 触发异常: {e}")

    load_cmd = (
        f"{prefix} && ros2 service call {node}/load_map "
        f"nav2_msgs/srv/LoadMap \"{{map_url: '{yaml_path}'}}\""
    )
    try:
        res = subprocess.run(
            ["bash", "-c", load_cmd],
            capture_output=True, text=True, timeout=10,
        )
        out = (res.stdout or "") + (res.stderr or "")
        if res.returncode == 0 and "success: True" in out:
            return {"ok": True, "method": "load_map",
                    "detail": "ROS 2 地图服务已重载新地图"}
        print(f"【地图重载】方案B 失败: {out.strip()}")
    except Exception as e:
        print(f"【地图重载】方案B 触发异常: {e}")

    return {"ok": False, "method": "failed",
            "detail": "ROS 2 地图重载失败，请检查小车端 map_server 是否运行"}


@app.route("/api/map/save_edited", methods=["POST"])
def api_save_edited():
    payload = flask_request.get_json(force=True)
    try:
        width = int(payload["width"])
        height = int(payload["height"])
        resolution = float(payload["resolution"])
        origin = payload.get("origin", {"x": 0.0, "y": 0.0})
        grid_data = payload["data"]
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({"ok": False, "error": f"参数缺失或类型错误: {e}"}), 400

    if len(grid_data) != width * height:
        return jsonify({
            "ok": False,
            "error": f"数据长度 {len(grid_data)} 与 {width}x{height}={width*height} 不匹配"
        }), 400

    try:
        path = save_edited_map(width, height, resolution, origin, grid_data)
    except Exception as e:
        return jsonify({"ok": False, "error": f"写文件失败: {e}"}), 500

    yaml_path = os.path.join(MAPS_DIR, "main.yaml")
    reload = reload_ros_map(yaml_path)

    return jsonify({
        "ok": True,
        "path": path,
        "width": width,
        "height": height,
        "resolution": resolution,
        "map_reload": reload,
    })


@app.route("/api/map/save_edited/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


# ================================================================
# 一键跟随 API
# ================================================================

@app.route("/api/follow/start", methods=["POST"])
def api_follow_start():
    global _follow_proc

    if _follow_proc and _follow_proc.poll() is None:
        return jsonify({
            "ok": True,
            "pid": _follow_proc.pid,
            "detail": "跟随脚本已在运行中",
        })

    if not os.path.isfile(FOLLOW_SCRIPT):
        return jsonify({
            "ok": False,
            "detail": f"跟随脚本不存在: {FOLLOW_SCRIPT}",
        }), 404

    os.chmod(FOLLOW_SCRIPT, 0o755)

    try:
        prefix = _ros2_source_prefix()
        cmd = f"{prefix} && cd \"{FOLLOW_SCRIPT_DIR}\" && exec bash \"{FOLLOW_SCRIPT}\"" if prefix \
            else f"cd \"{FOLLOW_SCRIPT_DIR}\" && exec bash \"{FOLLOW_SCRIPT}\""

        _follow_proc = subprocess.Popen(
            ["bash", "-c", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        print(f"[Follow] yolo_follow.sh 已启动 (pid={_follow_proc.pid})")
        return jsonify({
            "ok": True,
            "pid": _follow_proc.pid,
            "detail": "跟随脚本已启动",
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "detail": f"启动跟随脚本失败: {e}",
        }), 500


@app.route("/api/follow/stop", methods=["POST"])
def api_follow_stop():
    global _follow_proc

    if _follow_proc is None or _follow_proc.poll() is not None:
        _follow_proc = None
        return jsonify({"ok": True, "detail": "跟随脚本未在运行"})

    pid = _follow_proc.pid
    try:
        _follow_proc.terminate()
        try:
            _follow_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _follow_proc.kill()
            _follow_proc.wait(timeout=2)
        print(f"[Follow] yolo_follow.sh 已停止 (pid={pid})")
    except Exception as e:
        print(f"[Follow] 停止脚本异常: {e}")
    finally:
        _follow_proc = None

    return jsonify({"ok": True, "detail": "跟随脚本已停止", "pid": pid})


@app.route("/api/follow/status", methods=["GET"])
def api_follow_status():
    global _follow_proc
    running = _follow_proc is not None and _follow_proc.poll() is None
    return jsonify({
        "ok": True,
        "running": running,
        "pid": _follow_proc.pid if running else None,
    })


# ================================================================
# ROS 2 节点：InspectionController（巡检控制器）
# ================================================================

def _start_inspection_controller():
    """在守护线程中运行 InspectionController ROS 2 节点。"""
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.action import ActionClient
    from rclpy.time import Time
    from rclpy.duration import Duration
    from tf2_ros import Buffer, TransformListener, TransformException
    from geometry_msgs.msg import PoseArray, Pose, PoseStamped, Twist, PoseWithCovarianceStamped
    from std_msgs.msg import String, Bool
    from action_msgs.msg import GoalStatus
    from nav2_msgs.action import NavigateThroughPoses, NavigateToPose
    from nav_msgs.msg import OccupancyGrid
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy

    rclpy.init()

    class InspectionController(Node):
        ROBOT_BASE_FRAMES = ('base_footprint', 'base_link', 'base')

        def __init__(self):
            super().__init__('inspection_controller')
            self.callback_group = ReentrantCallbackGroup()
            self.lock = threading.Lock()
            self.current_waypoints: list = []
            self.is_paused = False
            self.is_running = False
            self.waypoints_received = False
            self.use_fallback = False

            self._action_client_through = ActionClient(
                self, NavigateThroughPoses, '/navigate_through_poses',
                callback_group=self.callback_group,
            )
            self._action_client_to_pose = ActionClient(
                self, NavigateToPose, '/navigate_to_pose',
                callback_group=self.callback_group,
            )
            self.current_goal_handle = None
            self._remaining_waypoints: list = []
            self._fallback_active = False

            self.cmd_sub = self.create_subscription(
                String, '/inspection_cmd', self.cmd_callback, 10,
                callback_group=self.callback_group,
            )
            self.path_sub = self.create_subscription(
                PoseArray, '/waypoint_user_path', self.path_callback, 10,
                callback_group=self.callback_group,
            )
            self.pause_sub = self.create_subscription(
                Bool, '/pause_navigation', self.pause_callback, 10,
                callback_group=self.callback_group,
            )
            self.amcl_sub = self.create_subscription(
                PoseWithCovarianceStamped, '/amcl_pose', self.amcl_callback, 10,
                callback_group=self.callback_group,
            )
            self.initpose_sub = self.create_subscription(
                PoseWithCovarianceStamped, '/initialpose', self.initialpose_callback, 10,
                callback_group=self.callback_group,
            )
            self.estop_sub = self.create_subscription(
                Bool, '/emergency_stop', self.estop_callback, 10,
                callback_group=self.callback_group,
            )

            self.status_pub = self.create_publisher(String, '/inspection_status', 10)
            self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)
            self.robot_pose_pub = self.create_publisher(PoseStamped, '/robot_pose', 10)

            self.map_convert_sub = self.create_subscription(
                String, '/map_convert_cmd', self.map_convert_callback, 10,
                callback_group=self.callback_group,
            )
            self.map_convert_status_pub = self.create_publisher(String, '/map_convert_status', 10)
            self._map_ready_event = threading.Event()
            self._map_convert_lock = threading.Lock()

            qos_latched = QoSProfile(
                depth=1,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
                reliability=ReliabilityPolicy.RELIABLE,
                history=HistoryPolicy.KEEP_LAST,
            )
            self._map_bridge_pub = self.create_publisher(OccupancyGrid, '/map_bridge', 10)
            self._map_bridge_sub = self.create_subscription(
                OccupancyGrid, '/map', self._map_bridge_cb, qos_latched,
                callback_group=self.callback_group,
            )
            self._amcl_bridge_pub = self.create_publisher(
                PoseWithCovarianceStamped, '/amcl_pose_bridge', 10)
            self._amcl_bridge_sub = self.create_subscription(
                PoseWithCovarianceStamped, '/amcl_pose', self._amcl_bridge_cb, qos_latched,
                callback_group=self.callback_group,
            )
            self._last_map = None
            self._map_repub_timer = self.create_timer(3.0, self._republish_map)
            self.get_logger().info('[QoS-Bridge] /map、/amcl_pose 已桥接到 /map_bridge、/amcl_pose_bridge')

            self.localization_covariance = None
            self.emergency_stop_active = False

            self.tf_buffer = Buffer()
            self.tf_listener = TransformListener(self.tf_buffer, self)
            self._robot_pose_timer = self.create_timer(0.2, self._publish_robot_pose)

            self.get_logger().info('[InspectionController] 已启动 (MultiThreadedExecutor + ReentrantCallbackGroup)')

        def _lookup_robot_pose(self):
            last_err = None
            for target in self.ROBOT_BASE_FRAMES:
                try:
                    tf = self.tf_buffer.lookup_transform(
                        'map', target, Time(), timeout=Duration(seconds=0.3)
                    )
                except TransformException as e:
                    last_err = e
                    continue
                ps = PoseStamped()
                ps.header.frame_id = 'map'
                ps.header.stamp = self.get_clock().now().to_msg()
                t = tf.transform.translation
                r = tf.transform.rotation
                ps.pose.position.x = t.x
                ps.pose.position.y = t.y
                ps.pose.position.z = t.z
                ps.pose.orientation.x = r.x
                ps.pose.orientation.y = r.y
                ps.pose.orientation.z = r.z
                ps.pose.orientation.w = r.w
                return ps
            self.get_logger().debug(f'[tf] 暂未获取到 map->base 变换: {last_err}')
            return None

        def _publish_robot_pose(self):
            pose = self._lookup_robot_pose()
            if pose is None:
                return
            self.robot_pose_pub.publish(pose)

        def _map_bridge_cb(self, msg):
            self._last_map = msg
            self._map_bridge_pub.publish(msg)
            self._map_ready_event.set()

        def _amcl_bridge_cb(self, msg):
            self._amcl_bridge_pub.publish(msg)

        def _republish_map(self):
            if self._last_map is not None:
                self._map_bridge_pub.publish(self._last_map)

        def path_callback(self, msg):
            with self.lock:
                self.current_waypoints.clear()
                self.waypoints_received = False
                for pose in msg.poses:
                    stamped = PoseStamped()
                    stamped.header.frame_id = 'map'
                    stamped.header.stamp = self.get_clock().now().to_msg()
                    stamped.pose = pose
                    self.current_waypoints.append(stamped)
                count = len(self.current_waypoints)
                self.waypoints_received = count > 0
                self.get_logger().info(f'[path_callback] 收到 {count} 个航点')

        @staticmethod
        def _pose_yaw(pose):
            q = pose.orientation
            return math.atan2(2.0 * (q.w * q.z), 1.0 - 2.0 * (q.z * q.z))

        def amcl_callback(self, msg):
            cov = msg.pose.covariance
            self.localization_covariance = cov

        def initialpose_callback(self, msg):
            pos = msg.pose.pose.position
            self.get_logger().info(f'[initialpose] 收到初始定位: ({pos.x:.3f}, {pos.y:.3f})')
            status_msg = String()
            status_msg.data = json.dumps({
                'type': 'initial_pose_set',
                'x': round(pos.x, 3),
                'y': round(pos.y, 3),
            })
            self.status_pub.publish(status_msg)

        def estop_callback(self, msg):
            self.emergency_stop_active = msg.data
            if msg.data:
                self.get_logger().error('[estop] 检测到硬件急停激活！')

        def cmd_callback(self, msg):
            try:
                payload = json.loads(msg.data)
                cmd = payload.get('cmd', '')
            except (json.JSONDecodeError, AttributeError):
                cmd = msg.data.strip()
            self.get_logger().info(f'[cmd_callback] 收到指令: "{cmd}"')
            if cmd == 'start':
                self._handle_start()
            elif cmd == 'pause':
                self._handle_pause()
            elif cmd == 'resume':
                self._handle_resume()
            elif cmd == 'stop':
                self._handle_stop()
            elif cmd in ('save_map', 'convert_pcd'):
                self.trigger_map_conversion()

        def pause_callback(self, msg):
            if msg.data:
                self._handle_pause()
            else:
                self._handle_resume()

        def map_convert_callback(self, msg):
            try:
                payload = json.loads(msg.data)
                cmd = payload.get('cmd', '')
            except (json.JSONDecodeError, AttributeError):
                cmd = msg.data.strip()
            if cmd in ('save_map', 'convert_pcd'):
                self.trigger_map_conversion()

        def trigger_map_conversion(self):
            acquired = self._map_convert_lock.acquire(blocking=False)
            if not acquired:
                self.get_logger().warn('[map_convert] 已有转换任务在运行，忽略本次触发')
                self._publish_map_convert_status('busy', '已有转换任务在运行')
                return
            self._publish_map_convert_status('started', '正在启动 pcd2pgm 转换...')
            t = threading.Thread(target=self._convert_pcd_to_map, daemon=True)
            t.start()

        def _publish_map_convert_status(self, status, msg_text=''):
            payload = {'status': status, 'msg': msg_text}
            m = String()
            m.data = json.dumps(payload, ensure_ascii=False)
            self.map_convert_status_pub.publish(m)

        def _convert_pcd_to_map(self):
            try:
                step1 = (
                    "source /opt/ros/humble/setup.bash && "
                    "source /home/jiaverso/Desktop/SparkCar_ROS2_WS/SparkCar_Tools/install/setup.bash && "
                    "ros2 launch pcd2pgm pcd2pgm_launch.py "
                    "params_file:=/home/jiaverso/Desktop/SparkCar_ROS2_WS/SparkCar_Tools/src/pcd2pgm/config/pcd2pgm.yaml"
                )
                self._map_ready_event.clear()
                pcd_proc = subprocess.Popen(
                    ['bash', '-c', step1],
                    start_new_session=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.get_logger().info(f'[map_convert] pcd2pgm launch 已启动 (pid={pcd_proc.pid})')

                map_ready = self._map_ready_event.wait(timeout=20.0)
                if not map_ready:
                    self.get_logger().error('[map_convert] 等待 /map 话题超时（20s），转换中止')
                    self._publish_map_convert_status('error', 'pcd2pgm 未发布 /map')
                    self._kill_process_group(pcd_proc)
                    return
                self._publish_map_convert_status('map_ready', 'pcd2pgm 已就绪，正在保存地图...')
                time.sleep(3.0)

                step2 = (
                    "source /opt/ros/humble/setup.bash && "
                    "mkdir -p /home/jiaverso/Desktop/SparkCar_ROS2_WS/SparkCar_Navigation/src/sparkcar_nav_bringup/maps && "
                    "ros2 run nav2_map_server map_saver_cli "
                    "-f /home/jiaverso/Desktop/SparkCar_ROS2_WS/SparkCar_Navigation/src/sparkcar_nav_bringup/maps/main "
                    "--ros-args -p map_save_timeout:=8.0"
                )
                save_ok = False
                for attempt in range(1, 3):
                    try:
                        result = subprocess.run(
                            ['bash', '-c', step2],
                            capture_output=True, text=True, timeout=60.0,
                        )
                        if result.returncode == 0:
                            save_ok = True
                            break
                        self.get_logger().error(
                            f'[map_convert] map_saver_cli 第 {attempt} 次返回非零 (rc={result.returncode})'
                        )
                    except subprocess.TimeoutExpired:
                        self.get_logger().error(f'[map_convert] map_saver_cli 第 {attempt} 次执行超时（60s）')
                    if attempt < 2:
                        time.sleep(3.0)

                self._kill_process_group(pcd_proc)
                if save_ok:
                    self._publish_map_convert_status('success', '地图已成功保存')
                else:
                    self._publish_map_convert_status('error', '地图保存失败')
            except Exception as e:
                self._publish_map_convert_status('error', f'转换异常: {e}')
            finally:
                self._map_convert_lock.release()

        def _kill_process_group(self, proc):
            try:
                pgid = os.getpgid(proc.pid)
            except ProcessLookupError:
                return
            try:
                os.killpg(pgid, signal.SIGINT)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:
                    pass
            try:
                subprocess.run(
                    "pkill -f pcd2pgm_launch.py; pkill -f pcd_to_pcdmap; true",
                    shell=True, capture_output=True, timeout=10,
                )
            except Exception:
                pass

        def _health_check(self):
            if self.emergency_stop_active:
                self._publish_status('error: estop')
                return False
            if self.localization_covariance is not None:
                max_cov = max(abs(self.localization_covariance[i]) for i in range(6))
                if max_cov > 5.0:
                    self._publish_status('error: bad localization')
                    return False
            return True

        def _handle_start(self):
            if self.current_goal_handle is not None:
                self.current_goal_handle = None
            with self.lock:
                if self.is_running:
                    return
                if not self.waypoints_received or len(self.current_waypoints) == 0:
                    self._publish_status('error: no waypoints')
                    return
                waypoints_copy = list(self.current_waypoints)
                self.is_running = True
                self.is_paused = False
                self.use_fallback = False
                self._fallback_active = False
            if not self._health_check():
                with self.lock:
                    self.is_running = False
                return
            self._publish_status('running')
            self._send_goal_through(waypoints_copy)

        def _handle_pause(self):
            with self.lock:
                if not self.is_running or self.is_paused:
                    return
                self.is_paused = True
            if self.current_goal_handle is not None:
                cancel_future = self.current_goal_handle.cancel_goal_async()
                cancel_future.add_done_callback(self._cancel_done_callback)
            self._send_zero_velocity()
            self._publish_status('paused')

        def _handle_resume(self):
            with self.lock:
                if not self.is_paused:
                    return
                self.is_paused = False
            self._publish_status('running')
            with self.lock:
                remaining = list(self._remaining_waypoints if self._fallback_active
                                else self.current_waypoints)
            if remaining:
                self._send_goal_through(remaining)

        def _handle_stop(self):
            with self.lock:
                self.is_running = False
                self.is_paused = False
                self._fallback_active = False
                self._remaining_waypoints.clear()
            if self.current_goal_handle is not None:
                cancel_future = self.current_goal_handle.cancel_goal_async()
                cancel_future.add_done_callback(self._cancel_done_callback)
            self._send_zero_velocity()
            self._publish_status('idle')

        def _send_zero_velocity(self):
            twist = Twist()
            self.cmd_vel_pub.publish(twist)

        def _send_goal_through(self, waypoints):
            if self.current_goal_handle is not None:
                self.current_goal_handle = None
            if not self._action_client_through.wait_for_server(timeout_sec=3.0):
                self._start_fallback(waypoints)
                return
            goal_msg = NavigateThroughPoses.Goal()
            for wp in waypoints:
                ps = PoseStamped()
                ps.header.frame_id = 'map'
                ps.header.stamp = self.get_clock().now().to_msg()
                ps.pose = wp.pose
                goal_msg.poses.append(ps)
            send_goal_future = self._action_client_through.send_goal_async(
                goal_msg, feedback_callback=self._feedback_callback,
            )
            send_goal_future.add_done_callback(self._goal_response_callback)

        def _goal_response_callback(self, future):
            goal_handle = future.result()
            if not goal_handle.accepted:
                with self.lock:
                    remaining = list(self._remaining_waypoints if self._fallback_active
                                    else self.current_waypoints)
                self._start_fallback(remaining)
                return
            self.current_goal_handle = goal_handle
            result_future = goal_handle.get_result_async()
            result_future.add_done_callback(self._result_callback)

        def _result_callback(self, future):
            try:
                result_response = future.result()
                status = result_response.status
                if status == GoalStatus.STATUS_SUCCEEDED:
                    self._publish_status('completed')
                    with self.lock:
                        self.is_running = False
                    self._fallback_active = False
                elif status == GoalStatus.STATUS_ABORTED:
                    self._publish_status('error: unreachable',
                                        reason='目标点不可达')
                    with self.lock:
                        self.is_running = False
                    self._fallback_active = False
                elif status == GoalStatus.STATUS_CANCELED:
                    self._publish_status('idle')
                    with self.lock:
                        self.is_running = False
                    self._fallback_active = False
                else:
                    self._publish_status('idle')
                    with self.lock:
                        self.is_running = False
                    self._fallback_active = False
            except Exception as e:
                self.get_logger().error(f'[FATAL ERROR] 结果回调异常: {e}')
                with self.lock:
                    self.is_running = False
            finally:
                self.current_goal_handle = None

        def _start_fallback(self, waypoints):
            self.get_logger().warn('[Fallback] 降级为单点导航模式')
            with self.lock:
                self._remaining_waypoints = list(waypoints)
                self._fallback_active = True
                self.use_fallback = True
            if not waypoints:
                with self.lock:
                    self.is_running = False
                self._fallback_active = False
                self._publish_status('completed')
                return
            self._send_next_single_goal()

        def _send_next_single_goal(self):
            with self.lock:
                if not self._remaining_waypoints or not self.is_running or self.is_paused:
                    return
                wp = self._remaining_waypoints.pop(0)
            if not self._action_client_to_pose.wait_for_server(timeout_sec=3.0):
                with self.lock:
                    self.is_running = False
                    self._fallback_active = False
                self._publish_status('error: nav unavailable')
                return
            goal_msg = NavigateToPose.Goal()
            goal_msg.pose = wp
            send_future = self._action_client_to_pose.send_goal_async(
                goal_msg, feedback_callback=self._feedback_single_callback,
            )
            send_future.add_done_callback(self._goal_response_single_callback)

        def _goal_response_single_callback(self, future):
            goal_handle = future.result()
            if not goal_handle.accepted:
                self._send_next_single_goal()
                return
            self.current_goal_handle = goal_handle
            result_future = goal_handle.get_result_async()
            result_future.add_done_callback(self._result_single_callback)

        def _result_single_callback(self, future):
            try:
                response = future.result()
                status = response.status
                if status == GoalStatus.STATUS_SUCCEEDED:
                    with self.lock:
                        remaining = list(self._remaining_waypoints)
                    if remaining:
                        self._send_next_single_goal()
                    else:
                        with self.lock:
                            self.is_running = False
                            self._fallback_active = False
                        self._publish_status('completed')
                elif status == GoalStatus.STATUS_ABORTED:
                    self._send_next_single_goal()
                elif status == GoalStatus.STATUS_CANCELED:
                    with self.lock:
                        self.is_running = False
                        self._fallback_active = False
                else:
                    self._send_next_single_goal()
            except Exception as e:
                self.get_logger().error(f'[Fallback] 结果回调异常: {e}')
                with self.lock:
                    self.is_running = False
                    self._fallback_active = False
            finally:
                self.current_goal_handle = None

        def _feedback_single_callback(self, feedback_msg):
            feedback = feedback_msg.feedback
            dist = getattr(feedback, 'distance_remaining', None)
            if dist is not None:
                self.get_logger().info(f'[Fallback] 距目标 {dist:.2f} m')

        def _cancel_done_callback(self, future):
            cancel_response = future.result()
            if len(cancel_response.goals_canceling) > 0:
                self.get_logger().info('[Nav2] 巡检任务已成功取消')
            self.current_goal_handle = None

        def _feedback_callback(self, feedback_msg):
            feedback = feedback_msg.feedback
            current_idx = None
            for attr in ('current_waypoint', 'current_waypoints', 'waypoint_index'):
                if hasattr(feedback, attr):
                    val = getattr(feedback, attr)
                    if isinstance(val, (int, list)):
                        current_idx = val if isinstance(val, int) else (val[0] if val else 0)
                        break
            if current_idx is not None:
                total = len(self.current_waypoints)
                self.get_logger().info(f'[Nav2] 进度: {current_idx}/{total}')

        def _publish_status(self, status_str, reason=None):
            payload = {'status': status_str}
            if reason is not None:
                payload['reason'] = reason
            msg = String()
            msg.data = json.dumps(payload)
            self.status_pub.publish(msg)

    node = InspectionController()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


# ================================================================
# ROS 2 节点：TaskChainManager（任务链执行器）
# ================================================================

def _start_task_chain_manager():
    """在守护线程中运行 TaskChainManager ROS 2 节点。"""
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.action import ActionClient
    from action_msgs.msg import GoalStatus
    from std_msgs.msg import String
    from geometry_msgs.msg import PoseStamped
    from nav2_msgs.action import NavigateToPose, FollowWaypoints

    try:
        import numpy as _np
        import cv2 as _cv2
        _CV2_AVAILABLE = True
    except Exception:
        _CV2_AVAILABLE = False

    rclpy.init()

    NODE_TYPE_LABEL = {
        'wait': '定时启动',
        'nav': '导航',
        'robot': '机器人巡检',
        'charge': '自动充电',
    }

    class TaskChainManager(Node):
        def __init__(self):
            super().__init__('task_chain_manager')
            self.callback_group = ReentrantCallbackGroup()
            self.lock = threading.Lock()
            self._running = False
            self._paused = False
            self._abort = threading.Event()
            self._abort.clear()
            self._current_chain = []
            self._current_goal_handle = None
            self._executor_thread = None

            self.cmd_sub = self.create_subscription(
                String, '/task_chain/command', self.command_callback, 10,
                callback_group=self.callback_group,
            )
            self.status_pub = self.create_publisher(String, '/task_chain/status', 10)
            self.charge_pub = self.create_publisher(String, '/charge_command', 10)
            self.speed_limit_pub = self.create_publisher(String, '/robot_speed_limit', 10)
            self.patrol_pub = self.create_publisher(String, '/robot_patrol_command', 10)

            self._nav_client = ActionClient(
                self, NavigateToPose, '/navigate_to_pose',
                callback_group=self.callback_group,
            )
            self._follow_client = ActionClient(
                self, FollowWaypoints, '/follow_waypoints',
                callback_group=self.callback_group,
            )
            self.get_logger().info('[TaskChainManager] 已启动，等待 /task_chain/command ...')

        def command_callback(self, msg):
            try:
                payload = json.loads(msg.data)
            except (json.JSONDecodeError, TypeError):
                return
            if isinstance(payload, list):
                self.start_chain(payload)
            elif isinstance(payload, dict):
                cmd = payload.get('cmd', '')
                if cmd == 'stop':
                    self.stop_chain()
                elif cmd == 'pause':
                    self.pause_chain()
                elif cmd == 'resume':
                    self.resume_chain()

        def start_chain(self, chain):
            with self.lock:
                if self._running:
                    return
                self._running = True
                self._paused = False
                self._abort.clear()
                self._current_chain = chain
            self._executor_thread = threading.Thread(target=self._execute, daemon=True)
            self._executor_thread.start()

        def stop_chain(self):
            self._abort.set()
            if self._current_goal_handle is not None:
                try:
                    self._current_goal_handle.cancel_goal_async()
                except Exception:
                    pass
            with self.lock:
                self._running = False
                self._paused = False
            self._publish_status('stopped')

        def pause_chain(self):
            with self.lock:
                self._paused = True
            self._publish_status('paused')

        def resume_chain(self):
            with self.lock:
                self._paused = False
            self._publish_status('running')

        def _execute(self):
            chain = self._current_chain
            total = len(chain)
            self._publish_status('running', current_step=0, total=total)
            for i, node in enumerate(chain):
                if self._abort.is_set():
                    self._publish_status('stopped', total=total)
                    with self.lock:
                        self._running = False
                    return
                while self._paused and not self._abort.is_set():
                    time.sleep(0.2)
                if self._abort.is_set():
                    self._publish_status('stopped', total=total)
                    with self.lock:
                        self._running = False
                    return
                ntype = node.get('type')
                nparams = node.get('params', {}) or {}
                self._publish_status('executing', current_step=i + 1, total=total, node_type=ntype)
                try:
                    if ntype == 'wait':
                        self._exec_wait(nparams)
                    elif ntype == 'nav':
                        ok = self._exec_nav(nparams)
                        if not ok:
                            self._publish_status('error', current_step=i + 1, total=total,
                                                node_type=ntype, reason='导航失败')
                            with self.lock:
                                self._running = False
                            return
                    elif ntype == 'inspect':
                        self._exec_inspect(nparams)
                    elif ntype == 'robot':
                        self._exec_robot(nparams)
                    elif ntype == 'charge':
                        self._exec_charge(nparams)
                except Exception as e:
                    self._publish_status('error', current_step=i + 1, total=total,
                                        node_type=ntype, reason=str(e))
                    with self.lock:
                        self._running = False
                    return
            self._publish_status('completed', current_step=total, total=total)
            with self.lock:
                self._running = False

        def _exec_wait(self, params):
            at = params.get('at')
            if at:
                try:
                    target = datetime.strptime(at, '%H:%M:%S').time()
                    now = datetime.now().time()
                    delay = (datetime.combine(datetime.today(), target)
                             - datetime.combine(datetime.today(), now)).total_seconds()
                    if delay < 0:
                        delay += 24 * 3600
                    self._sleep_with_abort(delay)
                    return
                except Exception:
                    pass
            duration = float(params.get('duration', 0))
            self._sleep_with_abort(duration)

        def _sleep_with_abort(self, seconds):
            end = time.time() + seconds
            while time.time() < end:
                if self._abort.is_set():
                    return
                time.sleep(0.1)

        def _exec_nav(self, params):
            path_type = (params.get('pathType') or 'single').lower()
            waypoints = self._parse_waypoints(params)
            if path_type == 'single':
                if not waypoints:
                    return False
                wp = waypoints[0]
                return self._nav_to_pose(wp['x'], wp['y'], wp['yaw'])
            if len(waypoints) < 2:
                return False
            if path_type in ('linear', 'square'):
                return self._nav_follow_waypoints(waypoints)
            if path_type == 'loop':
                return self._nav_loop(waypoints)
            wp = waypoints[0]
            return self._nav_to_pose(wp['x'], wp['y'], wp['yaw'])

        def _parse_waypoints(self, params):
            raw = params.get('waypoints')
            if isinstance(raw, list) and raw:
                out = []
                for wp in raw:
                    try:
                        out.append({
                            'x': float(wp.get('x', 0.0)),
                            'y': float(wp.get('y', 0.0)),
                            'yaw': float(wp.get('yaw', 0.0)),
                        })
                    except (TypeError, ValueError):
                        continue
                if out:
                    return out
            try:
                return [{
                    'x': float(params.get('x', 0.0)),
                    'y': float(params.get('y', 0.0)),
                    'yaw': float(params.get('yaw', 0.0)),
                }]
            except (TypeError, ValueError):
                return []

        def _make_pose_stamped(self, x, y, yaw):
            ps = PoseStamped()
            ps.header.frame_id = 'map'
            ps.header.stamp = self.get_clock().now().to_msg()
            ps.pose.position.x = x
            ps.pose.position.y = y
            ps.pose.position.z = 0.0
            ps.pose.orientation.z = math.sin(yaw / 2.0)
            ps.pose.orientation.w = math.cos(yaw / 2.0)
            return ps

        def _nav_to_pose(self, x, y, yaw):
            goal = NavigateToPose.Goal()
            goal.pose = self._make_pose_stamped(x, y, yaw)
            if not self._nav_client.wait_for_server(timeout_sec=5.0):
                return False
            done_event = threading.Event()
            result_holder = {}

            def _response_cb(future):
                goal_handle = future.result()
                if not goal_handle.accepted:
                    result_holder['status'] = 'rejected'
                    done_event.set()
                    return
                self._current_goal_handle = goal_handle
                res_future = goal_handle.get_result_async()

                def _result_cb(rf):
                    try:
                        result_holder['status'] = rf.result().status
                    except Exception:
                        result_holder['status'] = 'error'
                    done_event.set()

                res_future.add_done_callback(_result_cb)

            self._current_goal_handle = None
            send_future = self._nav_client.send_goal_async(goal)
            send_future.add_done_callback(_response_cb)

            while not done_event.is_set():
                if self._abort.is_set():
                    if self._current_goal_handle is not None:
                        try:
                            self._current_goal_handle.cancel_goal_async()
                        except Exception:
                            pass
                    return False
                time.sleep(0.1)

            status = result_holder.get('status')
            return status == GoalStatus.STATUS_SUCCEEDED

        def _nav_follow_waypoints(self, waypoints):
            if not self._follow_client.wait_for_server(timeout_sec=5.0):
                return False
            goal = FollowWaypoints.Goal()
            goal.poses = [self._make_pose_stamped(w['x'], w['y'], w['yaw']) for w in waypoints]
            done_event = threading.Event()
            result_holder = {}

            def _response_cb(future):
                goal_handle = future.result()
                if not goal_handle.accepted:
                    result_holder['status'] = 'rejected'
                    done_event.set()
                    return
                self._current_goal_handle = goal_handle
                res_future = goal_handle.get_result_async()

                def _result_cb(rf):
                    try:
                        result_holder['status'] = rf.result().status
                    except Exception:
                        result_holder['status'] = 'error'
                    done_event.set()

                res_future.add_done_callback(_result_cb)

            self._current_goal_handle = None
            send_future = self._follow_client.send_goal_async(goal)
            send_future.add_done_callback(_response_cb)

            while not done_event.is_set():
                if self._abort.is_set():
                    if self._current_goal_handle is not None:
                        try:
                            self._current_goal_handle.cancel_goal_async()
                        except Exception:
                            pass
                    return False
                time.sleep(0.1)

            status = result_holder.get('status')
            return status == GoalStatus.STATUS_SUCCEEDED

        def _nav_loop(self, waypoints):
            idx = 0
            while not self._abort.is_set():
                wp = waypoints[idx % len(waypoints)]
                ok = self._nav_to_pose(wp['x'], wp['y'], wp['yaw'])
                if not ok:
                    if self._abort.is_set():
                        return False
                    return False
                idx += 1
            return False

        def _exec_inspect(self, params):
            cam_topic = params.get('cam_topic', '/camera/image_raw')
            captured = {}
            sub = None
            try:
                from sensor_msgs.msg import Image
                from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
                qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                                 history=HistoryPolicy.KEEP_LAST)

                def _cb(msg):
                    captured['msg'] = msg

                sub = self.create_subscription(Image, cam_topic, _cb, qos,
                                                callback_group=self.callback_group)
            except Exception:
                return
            start = time.time()
            while time.time() - start < 5.0:
                if 'msg' in captured or self._abort.is_set():
                    break
                time.sleep(0.1)
            if sub is not None:
                try:
                    self.destroy_subscription(sub)
                except Exception:
                    pass
            if 'msg' not in captured:
                self._publish_status_step_note(f'拍照: 未收到 {cam_topic} 帧')
                return
            self._save_image(captured['msg'], params.get('action', 'capture_image'))
            self._publish_status_step_note('拍照成功')

        def _save_image(self, msg, action):
            if not _CV2_AVAILABLE:
                return
            try:
                h = msg.height
                w = msg.width
                enc = (msg.encoding or 'rgb8').lower()
                data = bytes(msg.data)
                if 'rgb' in enc or 'bgr' in enc:
                    arr = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)
                    img = arr if 'bgr' in enc else cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                elif 'mono' in enc:
                    img = np.frombuffer(data, dtype=np.uint8).reshape(h, w)
                else:
                    return
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                fname = f'inspect_{action}_{ts}.jpg'
                cv2.imwrite(fname, img)
            except Exception:
                pass

        def _exec_charge(self, params):
            m = String()
            m.data = 'dock'
            self.charge_pub.publish(m)
            self._sleep_with_abort(1.0)

        def _exec_robot(self, params):
            mode = params.get('mode', 'patrol')
            try:
                max_speed = float(params.get('max_speed', 0.5))
            except (TypeError, ValueError):
                max_speed = 0.5
            try:
                duration = float(params.get('duration', 0))
            except (TypeError, ValueError):
                duration = 0.0
            spd = String()
            spd.data = json.dumps({'max_speed': max_speed}, ensure_ascii=False)
            self.speed_limit_pub.publish(spd)
            pat = String()
            pat.data = json.dumps({'mode': mode, 'action': 'start'}, ensure_ascii=False)
            self.patrol_pub.publish(pat)
            if duration > 0:
                self._sleep_with_abort(duration)
            self._publish_status_step_note(f'机器人巡检已启动 (mode={mode})')

        def _publish_status(self, status, current_step=0, total=0, node_type='', reason=''):
            payload = {'status': status}
            if total:
                payload['total'] = total
            if current_step:
                payload['current_step'] = current_step
            if node_type:
                payload['node_type'] = node_type
            if reason:
                payload['reason'] = reason
            msg = String()
            msg.data = json.dumps(payload, ensure_ascii=False)
            self.status_pub.publish(msg)

        def _publish_status_step_note(self, note):
            msg = String()
            msg.data = json.dumps({'status': 'executing', 'note': note}, ensure_ascii=False)
            self.status_pub.publish(msg)

    node = TaskChainManager()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


# ================================================================
# 主入口
# ================================================================

if __name__ == '__main__':
    # 启动 InspectionController 守护线程
    t1 = threading.Thread(target=_start_inspection_controller, daemon=True, name='inspection-controller')
    t1.start()
    print(f'[UnifiedBackend] InspectionController 守护线程已启动')

    # 启动 TaskChainManager 守护线程
    t2 = threading.Thread(target=_start_task_chain_manager, daemon=True, name='task-chain-manager')
    t2.start()
    print(f'[UnifiedBackend] TaskChainManager 守护线程已启动')

    # Flask 主线程
    print(f'[UnifiedBackend] Flask HTTP 服务启动 → 0.0.0.0:{PORT}')
    app.run(host="0.0.0.0", port=PORT, debug=False)
