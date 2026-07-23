#!/usr/bin/env python3
"""
ROS2 Humble 多线程巡检控制器（含单点降级兜底）
- 多线程执行器 (MultiThreadedExecutor) 消除串行阻塞
- 可重入回调组 (ReentrantCallbackGroup) 避免回调互相等待
- 线程锁 (threading.Lock) 保护航点数据的并发读写
- Nav2 NavigateThroughPoses Action 主方案
- 自动降级为 NavigateToPose 单点循环（兜底）
- 定位置信度 & 急停状态监测
- 通过 TF 树(map->base_footprint) 原封不动地发布 /robot_pose（无任何手动偏移）
- path_callback 增加坐标自查 debug：打印机器人真实坐标与航点相对距离
"""

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.action import ActionClient
from rclpy.time import Time
from rclpy.duration import Duration

from tf2_ros import Buffer, TransformListener, TransformException

import math
import json
import threading
import subprocess
import os
import signal
import time

from geometry_msgs.msg import PoseArray, Pose, PoseStamped, Twist, PoseWithCovarianceStamped
from std_msgs.msg import String, Bool
from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateThroughPoses, NavigateToPose
from nav_msgs.msg import OccupancyGrid
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy


class InspectionController(Node):
    """多线程巡检控制器（含单点降级兜底）"""

    # 用于从 TF 查询机器人位姿的候选子帧（按优先级尝试）
    ROBOT_BASE_FRAMES = ('base_footprint', 'base_link', 'base')

    def __init__(self):
        super().__init__('inspection_controller')

        self.callback_group = ReentrantCallbackGroup()
        self.lock = threading.Lock()

        # ---------------------------------------------------------------
        # 状态变量
        # ---------------------------------------------------------------
        self.current_waypoints: list[PoseStamped] = []
        self.is_paused = False
        self.is_running = False
        self.waypoints_received = False
        self.use_fallback = False                   # 是否已降级为单点模式

        # ---------------------------------------------------------------
        # Action Client — 主方案：多航点连续导航
        # ---------------------------------------------------------------
        self._action_client_through = ActionClient(
            self,
            NavigateThroughPoses,
            '/navigate_through_poses',
            callback_group=self.callback_group,
        )
        # Action Client — 兜底方案：单点导航
        self._action_client_to_pose = ActionClient(
            self,
            NavigateToPose,
            '/navigate_to_pose',
            callback_group=self.callback_group,
        )

        self.current_goal_handle = None

        # ---------------------------------------------------------------
        # 单点降级模式专用状态
        # ---------------------------------------------------------------
        self._remaining_waypoints: list[PoseStamped] = []
        self._fallback_active = False

        # ---------------------------------------------------------------
        # 订阅者
        # ---------------------------------------------------------------
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
        # 定位置信度监测
        self.amcl_sub = self.create_subscription(
            PoseWithCovarianceStamped, '/amcl_pose', self.amcl_callback, 10,
            callback_group=self.callback_group,
        )
        # 初始定位指令 (2D Pose Estimate)
        self.initpose_sub = self.create_subscription(
            PoseWithCovarianceStamped, '/initialpose', self.initialpose_callback, 10,
            callback_group=self.callback_group,
        )
        # 急停状态监测（部分小车通过 /emergency_stop 发布 Bool）
        self.estop_sub = self.create_subscription(
            Bool, '/emergency_stop', self.estop_callback, 10,
            callback_group=self.callback_group,
        )

        # ---------------------------------------------------------------
        # 发布者
        # ---------------------------------------------------------------
        self.status_pub = self.create_publisher(String, '/inspection_status', 10)
        self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        # 机器人位姿发布：从 TF(map->base) 原封不动转发，无任何手动偏移
        self.robot_pose_pub = self.create_publisher(PoseStamped, '/robot_pose', 10)

        # ---------------------------------------------------------------
        # 地图转换（PCD -> 2D 栅格）触发订阅 / 状态发布
        # ---------------------------------------------------------------
        self.map_convert_sub = self.create_subscription(
            String, '/map_convert_cmd', self.map_convert_callback, 10,
            callback_group=self.callback_group,
        )
        self.map_convert_status_pub = self.create_publisher(String, '/map_convert_status', 10)
        # /map 就绪事件：由 _map_bridge_cb 在收到 /map 话题时置位，
        # 转换线程据此判断 pcd2pgm 是否已高频发布 /map。
        self._map_ready_event = threading.Event()
        # 防止并发重复触发转换
        self._map_convert_lock = threading.Lock()

        # ---------------------------------------------------------------
        # QoS 桥接（关键修复）
        # rosbridge 默认用 VOLATILE QoS 订阅，无法接收 latched 话题
        # (/map、/amcl_pose 均为 TRANSIENT_LOCAL)，导致前端永远收不到
        # 真实地图/定位 → 一直显示 mock 地图、航点坐标算错 → 小车不动。
        # 这里用正确的 TRANSIENT_LOCAL QoS 订阅真实话题，再以默认
        # (VOLATILE) QoS 转发到 *_bridge 话题供 rosbridge/前端订阅。
        # ---------------------------------------------------------------
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
        # 周期性重发 /map_bridge，确保“晚于地图发布才连接”的前端也能拿到地图
        self._map_repub_timer = self.create_timer(3.0, self._republish_map)
        self.get_logger().info('[QoS-Bridge] /map、/amcl_pose 已桥接到 /map_bridge、/amcl_pose_bridge')

        # ---------------------------------------------------------------
        # 定位 & 急停 状态
        # ---------------------------------------------------------------
        self.localization_covariance = None
        self.emergency_stop_active = False

        # ---------------------------------------------------------------
        # TF：用于查询机器人在 map 帧下的真实位姿
        # ---------------------------------------------------------------
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        # 周期性发布 /robot_pose，作为前端“所见即所得”的权威位姿源
        self._robot_pose_timer = self.create_timer(0.2, self._publish_robot_pose)

        self.get_logger().info('[InspectionController] 已启动 (MultiThreadedExecutor + ReentrantCallbackGroup)')

    # ================================================================
    # TF 辅助：从 map 帧查询机器人真实位姿（原封不动，无偏移）
    # ================================================================
    def _lookup_robot_pose(self) -> PoseStamped | None:
        """通过 TF 树查询 map -> base_* 的变换，原样封装为 PoseStamped。

        注意：这里只做“查询 + 透传”，**绝不**对 translation/rotation 做
        任何加减或比例缩放等二次偏移，确保前端看到的坐标与 Rviz/Gazebo 一致。
        """
        last_err: Exception | None = None
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
        """把 TF 中的机器人位姿原样发布到 /robot_pose（前端可订阅此话题）。"""
        pose = self._lookup_robot_pose()
        if pose is None:
            return
        self.robot_pose_pub.publish(pose)

    # ================================================================
    # QoS 桥接回调：把 latched 话题转发为 VOLATILE 的 *_bridge 话题
    # ================================================================
    def _map_bridge_cb(self, msg: OccupancyGrid):
        self._last_map = msg
        self._map_bridge_pub.publish(msg)
        # 通知转换线程：/map 话题已就绪（pcd2pgm 已发布首帧）
        self._map_ready_event.set()

    def _amcl_bridge_cb(self, msg: PoseWithCovarianceStamped):
        self._amcl_bridge_pub.publish(msg)

    def _republish_map(self):
        if self._last_map is not None:
            self._map_bridge_pub.publish(self._last_map)

    # ================================================================
    # path_callback — 接收航点路径
    # ================================================================
    def path_callback(self, msg: PoseArray):
        with self.lock:
            self.current_waypoints.clear()
            self.waypoints_received = False

            for i, pose in enumerate(msg.poses):
                stamped = PoseStamped()
                stamped.header.frame_id = 'map'
                stamped.header.stamp = self.get_clock().now().to_msg()
                # 航点坐标必须已经是 map 帧下的米制 X/Y（前端由真实 /map 的
                # origin/resolution 换算得到）。此处“原封不动”地封装，不叠加任何偏移。
                stamped.pose = pose
                self.current_waypoints.append(stamped)

                self.get_logger().info(
                    f'[path_callback] 航点{i+1}: x={pose.position.x:.3f}, '
                    f'y={pose.position.y:.3f}, yaw={self._pose_yaw(pose):.3f}'
                )

            count = len(self.current_waypoints)
            self.waypoints_received = count > 0
            self.get_logger().info(f'[path_callback] 收到 {count} 个航点 -> current_waypoints 已更新 (frame_id=map)')

        # ---- 坐标自查 debug（Task 3）----
        robot_pose = self._lookup_robot_pose()
        if robot_pose is None:
            self.get_logger().warn(
                '[path_callback][DEBUG] 无法通过 TF 获取机器人真实坐标，'
                '请确认已完成 AMCL 初始定位（2D Pose Estimate）'
            )
        else:
            rx = robot_pose.pose.position.x
            ry = robot_pose.pose.position.y
            for i, wp in enumerate(self.current_waypoints):
                dx = wp.pose.position.x - rx
                dy = wp.pose.position.y - ry
                dist = math.hypot(dx, dy)
                self.get_logger().info(
                    f'[path_callback][DEBUG] 航点{i+1} 相对机器人距离={dist:.3f}m | '
                    f'robot=({rx:.3f},{ry:.3f}) wp=({wp.pose.position.x:.3f},{wp.pose.position.y:.3f})'
                )

    @staticmethod
    def _pose_yaw(pose: Pose) -> float:
        q = pose.orientation
        return math.atan2(2.0 * (q.w * q.z), 1.0 - 2.0 * (q.z * q.z))

    # ================================================================
    # 定位 & 急停 & 初始定位 监测
    # ================================================================
    def amcl_callback(self, msg: PoseWithCovarianceStamped):
        cov = msg.pose.covariance
        self.localization_covariance = cov
        # 只在前 6 个元素（x, y, z, rx, ry, rz）里取最大方差作为置信度指标
        max_cov = max(abs(cov[i]) for i in range(6))
        if max_cov > 1.0:
            self.get_logger().warn(
                f'[amcl] 定位协方差偏大 (max={max_cov:.3f})，'
                f'请确认机器人已在 map 坐标系下完成初始化'
            )

    def initialpose_callback(self, msg: PoseWithCovarianceStamped):
        pos = msg.pose.pose.position
        ori = msg.pose.pose.orientation
        self.get_logger().info(
            f'[initialpose] 收到初始定位: ({pos.x:.3f}, {pos.y:.3f}) '
            f'qz={ori.z:.6f} qw={ori.w:.6f}'
        )
        # 发送状态通知前端
        status_msg = String()
        status_msg.data = json.dumps({
            'type': 'initial_pose_set',
            'x': round(pos.x, 3),
            'y': round(pos.y, 3),
        })
        self.status_pub.publish(status_msg)

    def estop_callback(self, msg: Bool):
        self.emergency_stop_active = msg.data
        if msg.data:
            self.get_logger().error('[estop] 检测到硬件急停激活 (emergency_stop=True)！小车无法移动')

    # ================================================================
    # cmd_callback — 接收巡检指令
    # ================================================================
    def cmd_callback(self, msg: String):
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
        else:
            self.get_logger().warn(f'[cmd_callback] 未知指令: {cmd}')

    def pause_callback(self, msg: Bool):
        if msg.data:
            self._handle_pause()
        else:
            self._handle_resume()

    # ================================================================
    # 地图转换（PCD -> PGM/YAML）触发入口
    # ================================================================
    def map_convert_callback(self, msg: String):
        """监听 /map_convert_cmd，收到 {"cmd":"save_map"} 即触发转换。"""
        try:
            payload = json.loads(msg.data)
            cmd = payload.get('cmd', '')
        except (json.JSONDecodeError, AttributeError):
            cmd = msg.data.strip()
        if cmd in ('save_map', 'convert_pcd'):
            self.trigger_map_conversion()
        else:
            self.get_logger().warn(f'[map_convert] 未知指令: {cmd}')

    def trigger_map_conversion(self):
        """入口：加锁防重入，开启独立守护线程执行转换命令链。"""
        acquired = self._map_convert_lock.acquire(blocking=False)
        if not acquired:
            self.get_logger().warn('[map_convert] 已有转换任务在运行，忽略本次触发')
            self._publish_map_convert_status('busy', '已有转换任务在运行')
            return
        self.get_logger().info('[map_convert] 收到一键保存地图指令，启动转换线程...')
        self._publish_map_convert_status('started', '正在启动 pcd2pgm 转换...')
        t = threading.Thread(target=self._convert_pcd_to_map, daemon=True)
        t.start()

    def _publish_map_convert_status(self, status: str, msg_text: str = ''):
        payload = {'status': status, 'msg': msg_text}
        data = json.dumps(payload, ensure_ascii=False)
        self.get_logger().info(f'[map_convert] /map_convert_status -> {data}')
        m = String()
        m.data = data
        self.map_convert_status_pub.publish(m)

    def _convert_pcd_to_map(self):
        """核心：严格按顺序执行 pcd2pgm 启动 -> 等待 /map -> map_saver 存图 -> 杀掉 launch。"""
        try:
            # ---------------- 步骤一：启动 pcd2pgm launch（阻塞式进程）----------------
            step1 = (
                "source /opt/ros/humble/setup.bash && "
                "source /home/jiaverso/Desktop/SparkCar_ROS2_WS/SparkCar_Tools/install/setup.bash && "
                "ros2 launch pcd2pgm pcd2pgm_launch.py "
                "params_file:=/home/jiaverso/Desktop/SparkCar_ROS2_WS/SparkCar_Tools/src/pcd2pgm/config/pcd2pgm.yaml"
            )
            self._map_ready_event.clear()
            pcd_proc = subprocess.Popen(
                ['bash', '-c', step1],
                start_new_session=True,   # 独立进程组，便于整体回收
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.get_logger().info(f'[map_convert] pcd2pgm launch 已启动 (pid={pcd_proc.pid})')

            # ---------------- 延迟 + 状态探测：等待 /map 话题就绪 ----------------
            map_ready = self._map_ready_event.wait(timeout=20.0)
            if not map_ready:
                self.get_logger().error('[map_convert] 等待 /map 话题超时（20s），转换中止')
                self._publish_map_convert_status('error', 'pcd2pgm 未发布 /map，请检查 launch 配置与 PCD 路径')
                self._kill_process_group(pcd_proc)
                return
            self.get_logger().info('[map_convert] 检测到 /map 话题已发布，开始保存地图')
            self._publish_map_convert_status('map_ready', 'pcd2pgm 已就绪，正在保存地图...')

            # ---------------- 关键修复：启动缓冲时延（防抖）----------------
            # pcd2pgm launch 虽已注册 /map 话题，但首帧 OccupancyGrid 的真正广播
            # 受节点生命周期与点云加载延迟影响会滞后。若此时立刻调用 map_saver_cli，
            # 其订阅会因“尚未收到首帧地图数据”而报 Failed to spin map subscription。
            # 因此强制 Sleep 3 秒，给 ROS 2 上下文初始化与地图数据稳定广播留出黄金时间。
            self.get_logger().info('[map_convert] pcd2pgm launch 已启动，等待地图数据稳定广播中...')
            time.sleep(3.0)
            self.get_logger().info('[map_convert] 开始调用 map_saver_cli 保存地图...')

            # ---------------- 步骤二：map_saver_cli 存图（带超时 + 重试）----------------
            # 说明：nav2 map_saver_cli 在 Humble 中通过 ROS 参数 map_save_timeout 控制
            # 等待首帧地图的超时（默认 2s，过短易触发 Failed to spin map subscription），
            # 需用 --ros-args -p map_save_timeout:=8.0 透传（必须置于命令末尾）。
            step2 = (
                "source /opt/ros/humble/setup.bash && "
                "mkdir -p /home/jiaverso/Desktop/SparkCar_ROS2_WS/SparkCar_Navigation/src/sparkcar_nav_bringup/maps && "
                "ros2 run nav2_map_server map_saver_cli "
                "-f /home/jiaverso/Desktop/SparkCar_ROS2_WS/SparkCar_Navigation/src/sparkcar_nav_bringup/maps/main "
                "--ros-args -p map_save_timeout:=8.0"
            )
            save_ok = False
            for attempt in range(1, 3):  # 最多重试 2 次，规避瞬时卡顿
                try:
                    result = subprocess.run(
                        ['bash', '-c', step2],
                        capture_output=True,
                        text=True,
                        timeout=60.0,
                    )
                    if result.returncode == 0:
                        save_ok = True
                        break
                    self.get_logger().error(
                        f'[map_convert] map_saver_cli 第 {attempt} 次返回非零 (rc={result.returncode}):\n'
                        f'{result.stdout}\n{result.stderr}'
                    )
                except subprocess.TimeoutExpired:
                    self.get_logger().error(f'[map_convert] map_saver_cli 第 {attempt} 次执行超时（60s）')
                if attempt < 2:
                    self.get_logger().warn('[map_convert] 3 秒后重试 map_saver_cli...')
                    time.sleep(3.0)

            # ---------------- 资源释放：彻底关掉步骤一的 launch 进程 ----------------
            self._kill_process_group(pcd_proc)

            if save_ok:
                self.get_logger().info('[map_convert] 地图已成功保存 ✅')
                self._publish_map_convert_status(
                    'success',
                    '地图已成功保存至 sparkcar_nav_bringup/maps/main.yaml',
                )
            else:
                self._publish_map_convert_status(
                    'error',
                    '地图保存失败，详情请查看控制器日志',
                )
        except Exception as e:
            self.get_logger().error(f'[map_convert] 转换过程异常: {e}')
            self._publish_map_convert_status('error', f'转换异常: {e}')
        finally:
            self._map_convert_lock.release()

    def _kill_process_group(self, proc: subprocess.Popen):
        """向整个进程组发送 SIGINT（launch 子节点可优雅退出），失败则 SIGKILL。"""
        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            return
        try:
            os.killpg(pgid, signal.SIGINT)
            self.get_logger().info(f'[map_convert] 已发送 SIGINT 至进程组 {pgid}')
        except Exception as e:
            self.get_logger().warn(f'[map_convert] SIGINT 失败，回退 terminate(): {e}')
            try:
                proc.terminate()
            except Exception:
                pass
        # 等待优雅退出，超时则强杀
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pgid, signal.SIGKILL)
                self.get_logger().warn(f'[map_convert] 进程组 {pgid} 未在 5s 内退出，已强制 SIGKILL')
            except Exception:
                pass
        # 安全网：清理可能残留的 pcd2pgm / launch 残留进程
        try:
            subprocess.run(
                "pkill -f pcd2pgm_launch.py; pkill -f pcd_to_pcdmap; true",
                shell=True, capture_output=True, timeout=10,
            )
        except Exception:
            pass

    # ================================================================
    # 指令处理函数
    # ================================================================

    def _health_check(self) -> bool:
        if self.emergency_stop_active:
            self.get_logger().error('[health] 硬件急停激活，拒绝启动')
            self._publish_status('error: estop')
            return False
        if self.localization_covariance is not None:
            max_cov = max(abs(self.localization_covariance[i]) for i in range(6))
            if max_cov > 5.0:
                self.get_logger().error(
                    f'[health] 定位协方差过大 (max={max_cov:.3f})，'
                    f'请先初始化定位再启动巡检'
                )
                self._publish_status('error: bad localization')
                return False
            self.get_logger().info(f'[health] 定位协方差 max={max_cov:.4f} -- 正常')
        else:
            self.get_logger().warn('[health] 尚未收到 /amcl_pose，定位状态未知')
        return True

    def _handle_start(self):
        if self.current_goal_handle is not None:
            self.get_logger().warn('[start] 检测到上一次的任务句柄未释放，正在强制清空...')
            self.current_goal_handle = None

        with self.lock:
            if self.is_running:
                self.get_logger().warn('[start] 巡检已在运行中，忽略重复指令')
                return
            if not self.waypoints_received or len(self.current_waypoints) == 0:
                self.get_logger().error('[start] 航点数据尚未就绪 -- 无法启动巡检')
                self._publish_status('error: no waypoints')
                return
            waypoints_copy = list(self.current_waypoints)
            self.is_running = True
            self.is_paused = False
            self.use_fallback = False
            self._fallback_active = False

        coords = ', '.join(
            f'({wp.pose.position.x:.2f}, {wp.pose.position.y:.2f})'
            for wp in waypoints_copy
        )
        self.get_logger().info(f'[start] 开始巡检 -- 下发 {len(waypoints_copy)} 个航点 [{coords}] 到 Nav2')

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

        self.get_logger().info('[pause] 正在取消当前 Nav2 导航任务...')

        if self.current_goal_handle is not None:
            cancel_future = self.current_goal_handle.cancel_goal_async()
            cancel_future.add_done_callback(self._cancel_done_callback)
        else:
            self.get_logger().warn('[pause] 当前没有正在运行的巡检任务句柄')

        self._send_zero_velocity()
        self._publish_status('paused')
        self.get_logger().info('[pause] 巡检已暂停')

    def _handle_resume(self):
        with self.lock:
            if not self.is_paused:
                return
            self.is_paused = False

        self._publish_status('running')
        self.get_logger().info('[resume] 巡检已恢复')

        with self.lock:
            remaining = list(self._remaining_waypoints if self._fallback_active
                            else self.current_waypoints)

        if remaining:
            self._send_goal_through(remaining)
        else:
            self.get_logger().warn('[resume] 没有待执行的航点')

    def _handle_stop(self):
        with self.lock:
            self.is_running = False
            self.is_paused = False
            self._fallback_active = False
            self._remaining_waypoints.clear()

        self.get_logger().info('[stop] 正在取消当前 Nav2 导航任务...')

        if self.current_goal_handle is not None:
            cancel_future = self.current_goal_handle.cancel_goal_async()
            cancel_future.add_done_callback(self._cancel_done_callback)
        else:
            self.get_logger().warn('[stop] 当前没有正在运行的巡检任务句柄')

        self._send_zero_velocity()
        self._publish_status('idle')
        self.get_logger().info('[stop] 巡检已停止')

    def _send_zero_velocity(self):
        twist = Twist()
        self.cmd_vel_pub.publish(twist)
        self.get_logger().info('[cmd_vel] 已下发零速度指令')

    # ================================================================
    # 方案一（主方案）：NavigateThroughPoses 多航点连续导航
    # ================================================================

    def _send_goal_through(self, waypoints: list[PoseStamped]):
        if self.current_goal_handle is not None:
            self.get_logger().warn('[Nav2] 发送前发现旧句柄残留，强制清空...')
            self.current_goal_handle = None

        self.get_logger().info('[Nav2] 正在等待 NavigateThroughPoses Action 服务响应...')
        if not self._action_client_through.wait_for_server(timeout_sec=3.0):
            self.get_logger().error('[Nav2] NavigateThroughPoses 不可用，即将降级为单点模式')
            self._start_fallback(waypoints)
            return

        goal_msg = NavigateThroughPoses.Goal()
        for wp in waypoints:
            ps = PoseStamped()
            ps.header.frame_id = 'map'
            ps.header.stamp = self.get_clock().now().to_msg()
            # 原样透传航点，不附加任何偏移
            ps.pose = wp.pose
            goal_msg.poses.append(ps)

        self.get_logger().info(f'[Nav2] 发送 NavigateThroughPoses 请求 ({len(goal_msg.poses)} 个航点)...')

        send_goal_future = self._action_client_through.send_goal_async(
            goal_msg,
            feedback_callback=self._feedback_callback,
        )
        send_goal_future.add_done_callback(self._goal_response_callback)

    def _goal_response_callback(self, future):
        goal_handle = future.result()
        accepted = goal_handle.accepted
        self.get_logger().info(f'[Nav2] NavigateThroughPoses 请求被接受? {accepted}')

        if not accepted:
            self.get_logger().error('[Nav2] NavigateThroughPoses 请求被拒绝，即将降级为单点模式')
            with self.lock:
                remaining = list(self._remaining_waypoints if self._fallback_active
                                else self.current_waypoints)
            self._start_fallback(remaining)
            return

        self.current_goal_handle = goal_handle
        self.get_logger().info('[Nav2] NavigateThroughPoses 请求已被接受，正在执行...')

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._result_callback)

    def _result_callback(self, future):
        try:
            result_response = future.result()
            status = result_response.status

            self.get_logger().info(f'[Nav2 Feedback] 导航任务结束，状态码为: {status}')

            if status == GoalStatus.STATUS_SUCCEEDED:
                self.get_logger().info('[Success] 小车已顺利抵达所有巡检航点！正在触发状态复位...')
                self._publish_status('completed')
                with self.lock:
                    self.is_running = False
                self._fallback_active = False

            elif status == GoalStatus.STATUS_ABORTED:
                # 状态码 6：Nav2 规划失败，目标点不可达（落在膨胀障碍物层内
                # 或被代价地图拒绝）。向前端下发明确的“不可达”状态，便于界面
                # 提示用户重新选取可达航点，并把 RUNNING 复位为 IDLE。
                self.get_logger().error(
                    f'[Nav2 Status] 任务中止(ABORTED, 状态码: {status})：'
                    f'目标点不可达或被取消，请重新选择可行航点'
                )
                self._publish_status(
                    'error: unreachable',
                    reason='目标点不可达或被取消（Nav2 规划失败）'
                )
                with self.lock:
                    self.is_running = False
                self._fallback_active = False

            elif status == GoalStatus.STATUS_CANCELED:
                self.get_logger().warn(f'[Nav2 Status] 任务被用户取消，状态码: {status}')
                self._publish_status('idle')
                with self.lock:
                    self.is_running = False
                self._fallback_active = False

            else:
                self.get_logger().error(f'[Nav2] 未知状态码: {status}')
                self._publish_status('idle')
                with self.lock:
                    self.is_running = False
                self._fallback_active = False

        except Exception as e:
            self.get_logger().error(f'[FATAL ERROR] 结果回调中发生异常，已强制拦截: {str(e)}')
            with self.lock:
                self.is_running = False
            self._fallback_active = False
        finally:
            self.current_goal_handle = None

    # ================================================================
    # 方案二（兜底）：NavigateToPose 单点循环
    # ================================================================

    def _start_fallback(self, waypoints: list[PoseStamped]):
        self.get_logger().warn('[Fallback] ***** 降级为单点导航模式 (NavigateToPose) *****')
        self.get_logger().info(f'[Fallback] 剩余 {len(waypoints)} 个待执行航点')

        with self.lock:
            self._remaining_waypoints = list(waypoints)
            self._fallback_active = True
            self.use_fallback = True

        if not waypoints:
            self.get_logger().warn('[Fallback] 没有待执行航点，结束')
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

        self.get_logger().info(
            f'[Fallback] 等待 NavigateToPose Action 服务响应...'
        )
        if not self._action_client_to_pose.wait_for_server(timeout_sec=3.0):
            self.get_logger().error('[Fallback] NavigateToPose 也不可用！彻底放弃')
            with self.lock:
                self.is_running = False
                self._fallback_active = False
            self._publish_status('error: nav unavailable')
            return

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = wp

        self.get_logger().info(
            f'[Fallback] 发送 NavigateToPose 单点: '
            f'x={wp.pose.position.x:.3f}, y={wp.pose.position.y:.3f} '
            f'(剩余 {len(self._remaining_waypoints)} 个)'
        )

        send_future = self._action_client_to_pose.send_goal_async(
            goal_msg,
            feedback_callback=self._feedback_single_callback,
        )
        send_future.add_done_callback(self._goal_response_single_callback)

    def _goal_response_single_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('[Fallback] NavigateToPose 请求被拒绝，跳过当前点')
            self._send_next_single_goal()
            return

        self.current_goal_handle = goal_handle
        self.get_logger().info('[Fallback] 单点目标已被接受，导航中...')

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._result_single_callback)

    def _result_single_callback(self, future):
        try:
            response = future.result()
            status = response.status

            self.get_logger().info(f'[Fallback] NavigateToPose 完成 -- status={status}')

            if status == GoalStatus.STATUS_SUCCEEDED:
                self.get_logger().info('[Fallback] 当前航点到达成功')
                with self.lock:
                    remaining = list(self._remaining_waypoints)
                if remaining:
                    self._send_next_single_goal()
                else:
                    self.get_logger().info('[Fallback] 所有单点导航执行完毕！')
                    with self.lock:
                        self.is_running = False
                        self._fallback_active = False
                    self._publish_status('completed')
            elif status == GoalStatus.STATUS_ABORTED:
                self.get_logger().error(
                    f'[Fallback] 当前航点导航中止(ABORTED, 状态码: {status})：'
                    f'目标点不可达，跳过此点继续下一个'
                )
                self._publish_status(
                    'error: unreachable',
                    reason='目标点不可达（Nav2 规划失败）'
                )
                self._send_next_single_goal()
            elif status == GoalStatus.STATUS_CANCELED:
                with self.lock:
                    self.is_running = False
                    self._fallback_active = False
                self.get_logger().warn('[Fallback] 导航已被用户取消')
            else:
                self.get_logger().error(f'[Fallback] 未知状态 {status}，跳过当前点')
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
        nav_time = getattr(feedback, 'navigation_time', None)
        self.get_logger().info(
            f'[Fallback] 距离目标 {dist if dist is not None else "?"}'
            f' | 耗时 {nav_time if nav_time is not None else "?"}'
        )

    # ================================================================
    # 通用回调：取消反馈
    # ================================================================

    def _cancel_done_callback(self, future):
        cancel_response = future.result()
        if len(cancel_response.goals_canceling) > 0:
            self.get_logger().info('[Nav2] 巡检任务已成功取消')
        else:
            self.get_logger().warn('[Nav2] 取消请求未被接受或任务已结束')
        self.current_goal_handle = None

    def _feedback_callback(self, feedback_msg):
        feedback = feedback_msg.feedback
        # 兼容不同 Nav2 版本的反馈字段名
        current_idx = None
        for attr in ('current_waypoint', 'current_waypoints', 'waypoint_index'):
            if hasattr(feedback, attr):
                val = getattr(feedback, attr)
                if isinstance(val, (int, list)):
                    current_idx = val if isinstance(val, int) else (val[0] if val else 0)
                    break
        if current_idx is None:
            slots = [s for s in dir(feedback) if not s.startswith('_')]
            self.get_logger().info(f'[Nav2] 收到反馈 (字段: {slots})')
            return
        total = len(self.current_waypoints)
        self.get_logger().info(f'[Nav2] 进度: {current_idx}/{total} 个航点已完成')

    # ================================================================
    # 工具方法
    # ================================================================

    @staticmethod
    def _status_to_str(status: int) -> str:
        mapping = {
            GoalStatus.STATUS_UNKNOWN: 'STATUS_UNKNOWN',
            GoalStatus.STATUS_ACCEPTED: 'STATUS_ACCEPTED',
            GoalStatus.STATUS_EXECUTING: 'STATUS_EXECUTING',
            GoalStatus.STATUS_CANCELING: 'STATUS_CANCELING',
            GoalStatus.STATUS_SUCCEEDED: 'STATUS_SUCCEEDED',
            GoalStatus.STATUS_CANCELED: 'STATUS_CANCELED',
            GoalStatus.STATUS_ABORTED: 'STATUS_ABORTED',
        }
        return mapping.get(status, f'UNKNOWN({status})')

    def _publish_status(self, status_str: str, reason: str | None = None):
        payload = {'status': status_str}
        if reason is not None:
            payload['reason'] = reason
        data = json.dumps(payload)
        self.get_logger().info(f'[publish] /inspection_status -> {data}')
        msg = String()
        msg.data = data
        self.status_pub.publish(msg)
        self.get_logger().info(f'[publish] {status_str} 发布完成')


def main(args=None):
    rclpy.init(args=args)

    node = InspectionController()

    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        node.get_logger().info('[InspectionController] 收到 Ctrl+C, 正在退出...')
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
