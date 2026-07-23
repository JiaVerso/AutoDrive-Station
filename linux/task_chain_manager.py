#!/usr/bin/env python3
"""
task_chain_manager.py — ROS 2 任务链顺序状态机执行器

功能：
- 订阅 /task_chain/command (std_msgs/msg/String)
  * 收到 JSON 数组  -> 作为任务链启动执行（Queue Executor）
  * 收到 {"cmd":"stop"}    -> 紧急终止整条任务链
  * 收到 {"cmd":"pause"}   -> 暂停（在节点边界等待）
  * 收到 {"cmd":"resume"}  -> 恢复
- 顺序执行节点：
  * wait    : time.sleep / 等待到指定时间
  * nav     : 通过 /navigate_to_pose Action 阻塞导航，到达后才继续；失败/取消即中止整链
  * inspect : 订阅相机话题抓取一帧，保存到本地磁盘，并发布“拍照成功”反馈
  * charge  : 向 /charge_command 发布回充指令
- 每执行一步通过 /task_chain/status (std_msgs/msg/String) 发布进度：
  {"status":"executing", "current_step":2, "total":5, "node_type":"nav"}
  {"status":"completed", "total":5}
  {"status":"stopped"} / {"status":"error", "reason":"..."}
"""

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.action import ActionClient
from action_msgs.msg import GoalStatus

import math
import json
import time
import threading
from datetime import datetime

from std_msgs.msg import String
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from nav2_msgs.action import FollowWaypoints

# 图像处理（可选依赖，缺失时仅跳过落盘，不影响流程）
try:
    import numpy as np
    import cv2
    _CV2_AVAILABLE = True
except Exception:  # pragma: no cover
    _CV2_AVAILABLE = False


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

        # 运行状态
        self._running = False
        self._paused = False
        self._abort = threading.Event()
        self._abort.clear()
        self._current_chain = []
        self._current_goal_handle = None
        self._executor_thread = None

        # ===== 订阅：任务链指令 =====
        self.cmd_sub = self.create_subscription(
            String, '/task_chain/command', self.command_callback, 10,
            callback_group=self.callback_group,
        )

        # ===== 发布：执行进度 =====
        self.status_pub = self.create_publisher(String, '/task_chain/status', 10)

        # ===== 发布：回充指令 =====
        self.charge_pub = self.create_publisher(String, '/charge_command', 10)

        # ===== 发布：巡检速度上限 / 巡检模式 =====
        self.speed_limit_pub = self.create_publisher(String, '/robot_speed_limit', 10)
        self.patrol_pub = self.create_publisher(String, '/robot_patrol_command', 10)

        # ===== Nav2 单点导航 Action Client =====
        self._nav_client = ActionClient(
            self, NavigateToPose, '/navigate_to_pose',
            callback_group=self.callback_group,
        )

        # ===== Nav2 多点导航 Action Client（直线/四边形任务）=====
        self._follow_client = ActionClient(
            self, FollowWaypoints, '/follow_waypoints',
            callback_group=self.callback_group,
        )

        self.get_logger().info('[TaskChainManager] 已启动，等待 /task_chain/command ...')

    # ============================================================
    # 指令入口
    # ============================================================
    def command_callback(self, msg: String):
        raw = msg.data
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            self.get_logger().warn(f'[TaskChainManager] 无法解析指令: {raw!r}')
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
            else:
                self.get_logger().warn(f'[TaskChainManager] 未知控制指令: {cmd}')
        else:
            self.get_logger().warn(f'[TaskChainManager] 非法 payload 类型: {type(payload)}')

    # ============================================================
    # 控制：启动 / 暂停 / 恢复 / 终止
    # ============================================================
    def start_chain(self, chain: list):
        with self.lock:
            if self._running:
                self.get_logger().warn('[TaskChainManager] 已有任务链在运行，忽略本次启动')
                return
            self._running = True
            self._paused = False
            self._abort.clear()
            self._current_chain = chain

        self.get_logger().info(f'[TaskChainManager] 收到任务链，共 {len(chain)} 个节点')
        for i, node in enumerate(chain):
            self.get_logger().info(
                f'  [{i+1}] type={node.get("type")} params={node.get("params")}'
            )

        self._executor_thread = threading.Thread(target=self._execute, daemon=True)
        self._executor_thread.start()

    def stop_chain(self):
        self.get_logger().info('[TaskChainManager] 收到紧急终止指令')
        self._abort.set()
        if self._current_goal_handle is not None:
            try:
                self._current_goal_handle.cancel_goal_async()
            except Exception as e:  # pragma: no cover
                self.get_logger().warn(f'[TaskChainManager] 取消 Nav2 目标异常: {e}')
        with self.lock:
            self._running = False
            self._paused = False
        self._publish_status('stopped')

    def pause_chain(self):
        with self.lock:
            self._paused = True
        self._publish_status('paused')
        self.get_logger().info('[TaskChainManager] 任务链已暂停')

    def resume_chain(self):
        with self.lock:
            self._paused = False
        self._publish_status('running')
        self.get_logger().info('[TaskChainManager] 任务链已恢复')

    # ============================================================
    # 状态机执行器（独立线程）
    # ============================================================
    def _execute(self):
        chain = self._current_chain
        total = len(chain)
        self._publish_status('running', current_step=0, total=total)

        for i, node in enumerate(chain):
            # 终止检查
            if self._abort.is_set():
                self._publish_status('stopped', total=total)
                with self.lock:
                    self._running = False
                return

            # 暂停检查（节点边界）
            while self._paused and not self._abort.is_set():
                time.sleep(0.2)
            if self._abort.is_set():
                self._publish_status('stopped', total=total)
                with self.lock:
                    self._running = False
                return

            ntype = node.get('type')
            nparams = node.get('params', {}) or {}
            self._publish_status(
                'executing', current_step=i + 1, total=total,
                node_type=ntype,
            )
            self.get_logger().info(
                f'[TaskChainManager] 执行第 {i+1}/{total} 步: {NODE_TYPE_LABEL.get(ntype, ntype)}'
            )

            try:
                if ntype == 'wait':
                    self._exec_wait(nparams)
                elif ntype == 'nav':
                    ok = self._exec_nav(nparams)
                    if not ok:
                        self._publish_status(
                            'error', current_step=i + 1, total=total,
                            node_type=ntype, reason='导航失败 / 被取消 / 不可达',
                        )
                        with self.lock:
                            self._running = False
                        return
                elif ntype == 'inspect':
                    self._exec_inspect(nparams)
                elif ntype == 'robot':
                    self._exec_robot(nparams)
                elif ntype == 'charge':
                    self._exec_charge(nparams)
                else:
                    self.get_logger().warn(f'[TaskChainManager] 未知节点类型: {ntype}，跳过')
            except Exception as e:
                self.get_logger().error(f'[TaskChainManager] 第 {i+1} 步执行异常: {e}')
                self._publish_status(
                    'error', current_step=i + 1, total=total,
                    node_type=ntype, reason=str(e),
                )
                with self.lock:
                    self._running = False
                return

        self._publish_status('completed', current_step=total, total=total)
        self.get_logger().info('[TaskChainManager] 任务链全部执行完成')
        with self.lock:
            self._running = False

    # ============================================================
    # 节点实现
    # ============================================================
    def _exec_wait(self, params: dict):
        # 定时启动：等待到指定 HH:MM:SS（今天或次日）
        at = params.get('at')
        if at:
            try:
                target = datetime.strptime(at, '%H:%M:%S').time()
                now = datetime.now().time()
                delay = (datetime.combine(datetime.today(), target)
                         - datetime.combine(datetime.today(), now)).total_seconds()
                if delay < 0:
                    delay += 24 * 3600  # 跨天
                self.get_logger().info(f'[TaskChainManager] 定时启动，等待 {delay:.0f}s 至 {at}')
                self._sleep_with_abort(delay)
                return
            except Exception as e:
                self.get_logger().warn(f'[TaskChainManager] 解析 at={at} 失败，回退到 duration: {e}')

        duration = float(params.get('duration', 0))
        self.get_logger().info(f'[TaskChainManager] 延时等待 {duration}s')
        self._sleep_with_abort(duration)

    def _sleep_with_abort(self, seconds: float):
        """可被紧急终止打断的 sleep。"""
        end = time.time() + seconds
        while time.time() < end:
            if self._abort.is_set():
                return
            time.sleep(0.1)

    def _exec_nav(self, params: dict) -> bool:
        path_type = (params.get('pathType') or 'single').lower()

        # 解析航点列表：多点模式优先用 waypoints，单点模式由 x/y/yaw 构造
        waypoints = self._parse_waypoints(params)

        # 单点导航：保持原 NavigateToPose 逻辑不变
        if path_type == 'single':
            if not waypoints:
                self.get_logger().error('[TaskChainManager] 单点导航缺少坐标')
                return False
            wp = waypoints[0]
            return self._nav_to_pose(wp['x'], wp['y'], wp['yaw'])

        # 多点模式（linear / square / loop）：至少需要 2 个点
        if len(waypoints) < 2:
            self.get_logger().error(
                f'[TaskChainManager] {path_type} 导航需要至少 2 个航点，当前 {len(waypoints)} 个'
            )
            return False

        # linear / square：一次性交给 Nav2 FollowWaypoints
        if path_type in ('linear', 'square'):
            return self._nav_follow_waypoints(waypoints)

        # loop：环形循环，依次导航直到最后一个点后回到第一个点，收到 stop 才停
        if path_type == 'loop':
            return self._nav_loop(waypoints)

        # 未知路径类型兜底为单点
        self.get_logger().warn(f'[TaskChainManager] 未知 pathType={path_type}，按单点处理')
        wp = waypoints[0]
        return self._nav_to_pose(wp['x'], wp['y'], wp['yaw'])

    def _parse_waypoints(self, params: dict) -> list:
        """从节点参数中解析航点列表 [{x,y,yaw}, ...]。"""
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
        # 回退：用单点 x/y/yaw
        try:
            return [{
                'x': float(params.get('x', 0.0)),
                'y': float(params.get('y', 0.0)),
                'yaw': float(params.get('yaw', 0.0)),
            }]
        except (TypeError, ValueError):
            return []

    def _make_pose_stamped(self, x: float, y: float, yaw: float) -> PoseStamped:
        ps = PoseStamped()
        ps.header.frame_id = 'map'
        ps.header.stamp = self.get_clock().now().to_msg()
        ps.pose.position.x = x
        ps.pose.position.y = y
        ps.pose.position.z = 0.0
        ps.pose.orientation.z = math.sin(yaw / 2.0)
        ps.pose.orientation.w = math.cos(yaw / 2.0)
        return ps

    def _nav_to_pose(self, x: float, y: float, yaw: float) -> bool:
        """单点导航（NavigateToPose），原逻辑保持不变。"""
        goal = NavigateToPose.Goal()
        goal.pose = self._make_pose_stamped(x, y, yaw)

        if not self._nav_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('[TaskChainManager] /navigate_to_pose Action 服务不可用')
            return False

        done_event = threading.Event()
        result_holder = {}

        def _response_cb(future):
            goal_handle = future.result()
            if not goal_handle.accepted:
                self.get_logger().error('[TaskChainManager] 导航目标被拒绝')
                result_holder['status'] = 'rejected'
                done_event.set()
                return
            self._current_goal_handle = goal_handle
            res_future = goal_handle.get_result_async()

            def _result_cb(rf):
                try:
                    result_holder['status'] = rf.result().status
                except Exception as e:  # pragma: no cover
                    result_holder['status'] = 'error'
                    self.get_logger().error(f'[TaskChainManager] 导航结果回调异常: {e}')
                done_event.set()

            res_future.add_done_callback(_result_cb)

        self._current_goal_handle = None
        send_future = self._nav_client.send_goal_async(
            goal, feedback_callback=self._nav_feedback_cb
        )
        send_future.add_done_callback(_response_cb)

        # 在独立线程中等待结果（回调跑在主 executor 线程上）
        while not done_event.is_set():
            if self._abort.is_set():
                if self._current_goal_handle is not None:
                    try:
                        self._current_goal_handle.cancel_goal_async()
                    except Exception:  # pragma: no cover
                        pass
                self.get_logger().warn('[TaskChainManager] 导航被紧急终止')
                return False
            time.sleep(0.1)

        status = result_holder.get('status')
        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info(f'[TaskChainManager] 已到达目标点 ({x:.2f}, {y:.2f})')
            return True
        if status == 'rejected':
            return False
        self.get_logger().error(f'[TaskChainManager] 导航未成功，状态码: {status}')
        return False

    def _nav_follow_waypoints(self, waypoints: list) -> bool:
        """直线/四边形等多点导航：通过 Nav2 FollowWaypoints 一次性下发。"""
        if not self._follow_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('[TaskChainManager] /follow_waypoints Action 服务不可用')
            return False

        goal = FollowWaypoints.Goal()
        goal.poses = [self._make_pose_stamped(w['x'], w['y'], w['yaw']) for w in waypoints]

        done_event = threading.Event()
        result_holder = {}

        def _response_cb(future):
            goal_handle = future.result()
            if not goal_handle.accepted:
                self.get_logger().error('[TaskChainManager] FollowWaypoints 目标被拒绝')
                result_holder['status'] = 'rejected'
                done_event.set()
                return
            self._current_goal_handle = goal_handle
            res_future = goal_handle.get_result_async()

            def _result_cb(rf):
                try:
                    result_holder['status'] = rf.result().status
                except Exception as e:  # pragma: no cover
                    result_holder['status'] = 'error'
                    self.get_logger().error(f'[TaskChainManager] FollowWaypoints 结果回调异常: {e}')
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
                    except Exception:  # pragma: no cover
                        pass
                self.get_logger().warn('[TaskChainManager] 多点导航被紧急终止')
                return False
            time.sleep(0.1)

        status = result_holder.get('status')
        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info(f'[TaskChainManager] 多点导航完成（{len(waypoints)} 个点）')
            return True
        if status == 'rejected':
            return False
        self.get_logger().error(f'[TaskChainManager] 多点导航未成功，状态码: {status}')
        return False

    def _nav_loop(self, waypoints: list) -> bool:
        """环形循环任务：依次导航每个点，到末点后回到首点，直到收到 stop/abort。"""
        self.get_logger().info(f'[TaskChainManager] 启动环形循环任务，共 {len(waypoints)} 个航点')
        idx = 0
        while not self._abort.is_set():
            wp = waypoints[idx % len(waypoints)]
            self.get_logger().info(
                f'[TaskChainManager] 环形第 {(idx % len(waypoints)) + 1}/{len(waypoints)} 圈内点 '
                f'({wp["x"]:.2f}, {wp["y"]:.2f})'
            )
            ok = self._nav_to_pose(wp['x'], wp['y'], wp['yaw'])
            if not ok:
                if self._abort.is_set():
                    self.get_logger().warn('[TaskChainManager] 环形任务被紧急终止')
                    return False
                self.get_logger().error('[TaskChainManager] 环形任务某点导航失败，终止循环')
                return False
            idx += 1
        self.get_logger().warn('[TaskChainManager] 环形任务收到终止信号，已退出循环')
        return False  # 循环是被 stop 打断的，视为非 SUCCESS 结束

    def _nav_feedback_cb(self, feedback_msg):
        feedback = feedback_msg.feedback
        dist = getattr(feedback, 'distance_remaining', None)
        if dist is not None:
            self.get_logger().info(f'[TaskChainManager][nav] 距目标剩余 {dist:.2f} m')

    def _exec_inspect(self, params: dict):
        cam_topic = params.get('cam_topic', '/camera/image_raw')
        action = params.get('action', 'capture_image')
        self.get_logger().info(f'[TaskChainManager] 拍照巡检: topic={cam_topic} action={action}')

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
        except Exception as e:
            self.get_logger().warn(f'[TaskChainManager] 订阅 {cam_topic} 失败: {e}')
            return

        # 等待一帧（最多 5s）
        start = time.time()
        while time.time() - start < 5.0:
            if 'msg' in captured or self._abort.is_set():
                break
            time.sleep(0.1)

        if sub is not None:
            try:
                self.destroy_subscription(sub)
            except Exception:  # pragma: no cover
                pass

        if 'msg' not in captured:
            self.get_logger().warn('[TaskChainManager] 未在 5s 内收到相机帧，跳过保存')
            # 仍视为本步完成（不阻断整条链），仅给出反馈
            self._publish_status_step_note(f'拍照: 未收到 {cam_topic} 帧')
            return

        self._save_image(captured['msg'], action)
        self._publish_status_step_note('拍照成功')

    def _save_image(self, msg, action: str):
        if not _CV2_AVAILABLE:
            self.get_logger().warn('[TaskChainManager] 未安装 opencv/numpy，跳过图像落盘')
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
                self.get_logger().warn(f'[TaskChainManager] 未支持编码 {enc}，跳过保存')
                return
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            fname = f'inspect_{action}_{ts}.jpg'
            cv2.imwrite(fname, img)
            self.get_logger().info(f'[TaskChainManager] 图像已保存: {fname}')
        except Exception as e:
            self.get_logger().warn(f'[TaskChainManager] 保存图像失败: {e}')

    def _exec_charge(self, params: dict):
        m = String()
        m.data = 'dock'
        self.charge_pub.publish(m)
        self.get_logger().info('[TaskChainManager] 已发布回充指令 -> /charge_command (dock)')
        # 给回充对接留出少量缓冲时间
        self._sleep_with_abort(1.0)

    def _exec_robot(self, params: dict):
        """机器人巡检节点：下发速度上限 + 巡检模式，并按 duration 持续巡检。"""
        mode = params.get('mode', 'patrol')
        try:
            max_speed = float(params.get('max_speed', 0.5))
        except (TypeError, ValueError):
            max_speed = 0.5
        try:
            duration = float(params.get('duration', 0))
        except (TypeError, ValueError):
            duration = 0.0

        self.get_logger().info(
            f'[TaskChainManager] 机器人巡检: mode={mode} max_speed={max_speed} duration={duration}s'
        )

        # 下发速度上限
        spd = String()
        spd.data = json.dumps({'max_speed': max_speed}, ensure_ascii=False)
        self.speed_limit_pub.publish(spd)

        # 下发巡检模式指令
        pat = String()
        pat.data = json.dumps({'mode': mode, 'action': 'start'}, ensure_ascii=False)
        self.patrol_pub.publish(pat)

        # duration <= 0 表示持续巡检到链结束（不阻塞整链），仍给一点缓冲
        if duration > 0:
            self._sleep_with_abort(duration)

        self._publish_status_step_note(f'机器人巡检已启动 (mode={mode})')

    # ============================================================
    # 进度发布工具
    # ============================================================
    def _publish_status(self, status: str, current_step: int = 0, total: int = 0,
                        node_type: str = '', reason: str = ''):
        payload: dict = {'status': status}
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
        self.get_logger().info(f'[TaskChainManager] /task_chain/status -> {msg.data}')

    def _publish_status_step_note(self, note: str):
        """在节点执行内部补充一条轻量反馈（仍保持 executing 状态）。"""
        msg = String()
        msg.data = json.dumps({'status': 'executing', 'note': note}, ensure_ascii=False)
        self.status_pub.publish(msg)
        self.get_logger().info(f'[TaskChainManager] note -> {note}')


def main(args=None):
    rclpy.init(args=args)
    node = TaskChainManager()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        node.get_logger().info('[TaskChainManager] 收到 Ctrl+C，退出中...')
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
