#!/usr/bin/env python3
"""
地图修补后端服务
===============
接收前端（Vue）发送来的「修补后 OccupancyGrid 栅格数组 + 元数据」，
 直接重写 <MAPS_DIR>/main.pgm 与 main.yaml，无需再用 GIMP 手动修图。

ROS 栅格值约定（与前端 mapBuffer.data 对齐）：
    0    -> 空闲（可行走）  -> PGM 灰度 254（白）
    100  -> 绝对障碍（墙壁）-> PGM 灰度 0  （黑）
    其它  -> 未知区域       -> PGM 灰度 205（灰）

启动：
     pip install flask flask-cors numpy
     MAPS_DIR=/home/jiaverso/Desktop/SparkCar_ROS2_WS/SparkCar_Navigation/src/sparkcar_nav_bringup/maps PORT=5000 python3 map_edit_server.py
 默认监听 0.0.0.0:5000，可通过环境变量 PORT / MAPS_DIR 覆盖。
前端保存地址：http://<本机IP>:5000/api/map/save_edited
（开发态可在前端 .env 设置 VITE_MAP_EDIT_API=http://localhost:5000）
"""
import os
import signal
import subprocess
from flask import Flask, request, jsonify
from flask_cors import CORS
import numpy as np

MAPS_DIR = os.environ.get("MAPS_DIR", "/maps")
PORT = int(os.environ.get("PORT", "5000"))

# ===== 一键跟随：yolo_follow.sh 脚本路径 =====
FOLLOW_SCRIPT_DIR = os.environ.get(
    "FOLLOW_SCRIPT_DIR",
    os.path.expanduser("~/Desktop/SparkCar_ROS2_WS/scripts"),
)
FOLLOW_SCRIPT = os.path.join(FOLLOW_SCRIPT_DIR, "yolo_follow.sh")

# 跟随子进程 PID，用于停止时 kill
_follow_proc: subprocess.Popen | None = None

# ROS 2 环境（与 inspection_controller.py 保持一致）：
# 调用 ros2 CLI 前必须 source 对应发行版与小车工作区，
# 否则 ros2 命令找不到。按需修改 ROS_DISTRO / 工作区路径。
ROS_DISTRO = os.environ.get("ROS_DISTRO", "humble")
ROS_SETUP = os.environ.get(
    "ROS_SETUP",
    f"/opt/ros/{ROS_DISTRO}/setup.bash",
)
# 小车工作区 install/setup.bash（若存在则一并 source，提供 nav2_msgs 等类型）
WS_SETUP = os.environ.get(
    "WS_SETUP",
    os.path.expanduser(
        "~/Desktop/SparkCar_ROS2_WS/SparkCar_Navigation/install/setup.bash"
    ),
)
# map_server 节点名（lifecycle 重载回退用）。如你的节点名不同请修改。
MAP_SERVER_NODE = os.environ.get("MAP_SERVER_NODE", "/map_server")

app = Flask(__name__)
CORS(app)  # 允许浏览器跨域调用


def save_edited_map(width: int, height: int, resolution: float,
                    origin: dict, grid_data) -> str:
    os.makedirs(MAPS_DIR, exist_ok=True)
    pgm_path = os.path.join(MAPS_DIR, "main.pgm")
    yaml_path = os.path.join(MAPS_DIR, "main.yaml")

    arr = np.asarray(grid_data, dtype=np.uint8)

    # ROS 栅格值 -> PGM 灰度值（向量化映射，避免百万级 Python 循环）
    #   0    -> 254 (白, 空闲)
    #   100  -> 0   (黑, 障碍)
    #   其它 -> 205 (灰, 未知)
    img = np.where(
        arr == 0, 254,
        np.where(arr == 100, 0, 205)
    ).astype(np.uint8)

    # ROS 地图 origin 在左下角；PGM 图像行序在顶部，
    # 需上下翻转使像素与 RViz/map_server 显示一致。
    matrix = img.reshape((height, width))
    matrix = np.flipud(matrix)

    # 写入标准 P5 PGM
    with open(pgm_path, "wb") as f:
        f.write(f"P5\n{width} {height}\n255\n".encode("ascii"))
        f.write(matrix.tobytes())

    # 写入配套 YAML（map_server 加载所需元数据）
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


def _ros2_source_prefix() -> str:
    """拼出 source ROS 环境的 bash 前缀，保证后续 ros2 CLI 可用。"""
    parts = []
    if os.path.isfile(ROS_SETUP):
        parts.append(f"source {ROS_SETUP}")
    if os.path.isfile(WS_SETUP):
        parts.append(f"source {WS_SETUP}")
    return " && ".join(parts)


def reload_ros_map(yaml_path: str) -> dict:
    """
    保存成功后让正在运行的 map_server 重新加载硬盘上的新地图。

    策略（按稳妥度自动回退）：
      方案 A（首选）：标准 lifecycle 字符串状态机链
              deactivate -> cleanup -> configure -> activate
              彻底清空内存旧缓存后重新读盘，兼容性最好。
      方案 B（回退）：调用 nav2_msgs/srv/LoadMap 服务重新加载
              （最优雅，不影响导航状态）。
    返回 {ok, method, detail}，供接口回传给前端提示。
    """
    prefix = _ros2_source_prefix()
    if not prefix:
        return {"ok": False, "method": "none",
                "detail": "未找到 ROS 2 setup.bash，跳过地图重载"}

    # ---------- 方案 A：标准 lifecycle 字符串状态机链 ----------
    # 注意：ros2 lifecycle set 只接受字符串动作名（deactivate/cleanup/
    # configure/activate），数字 change_state 在不同版本会报
    # "unrecognized arguments: 1" 而失败，故此处一律使用字符串。
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
        # configure / activate 任一失败即视为未成功
        if "error" in out.lower() or "unrecognized" in out.lower():
            print(f"【地图重载】方案A 状态链存在异常，回退方案B。输出: {out.strip()}")
        else:
            return {"ok": True, "method": "lifecycle",
                    "detail": "已通过 lifecycle 状态链重置 map_server 并重新读盘"}
    except Exception as e:  # noqa: BLE001
        print(f"【地图重载】方案A 触发异常: {e}")

    # ---------- 方案 B：LoadMap 服务回退 ----------
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
    except Exception as e:  # noqa: BLE001
        print(f"【地图重载】方案B 触发异常: {e}")

    return {"ok": False, "method": "failed",
            "detail": "ROS 2 地图重载失败，请检查小车端 map_server 是否运行"}


@app.route("/api/map/save_edited", methods=["POST"])
def api_save_edited():
    payload = request.get_json(force=True)
    try:
        width = int(payload["width"])
        height = int(payload["height"])
        resolution = float(payload["resolution"])
        origin = payload.get("origin", {"x": 0.0, "y": 0.0})
        grid_data = payload["data"]  # 一维数组 (-1/255 未知, 0 空闲, 100 障碍)
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({"ok": False, "error": f"参数缺失或类型错误: {e}"}), 400

    if len(grid_data) != width * height:
        return jsonify({
            "ok": False,
            "error": f"数据长度 {len(grid_data)} 与 {width}x{height}={width*height} 不匹配"
        }), 400

    try:
        path = save_edited_map(width, height, resolution, origin, grid_data)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"写文件失败: {e}"}), 500

    # 写入成功后，立即通知正在运行的 map_server 重新加载新地图
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
    """
    启动 yolo_follow.sh 脚本（ROS 2 YOLO 跟随节点）。
    后端在子进程中执行：
        cd ~/Desktop/SparkCar_ROS2_WS/scripts && ./yolo_follow.sh
    返回 {ok, pid, detail}。
    """
    global _follow_proc

    # 如果已在运行，直接返回成功（幂等）
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

    # 确保脚本有执行权限
    os.chmod(FOLLOW_SCRIPT, 0o755)

    try:
        # source ROS 环境后执行脚本，让子进程继承 ROS 2 上下文
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
    """
    停止正在运行的 yolo_follow.sh 子进程。
    先 SIGTERM，3 秒后若未退出则 SIGKILL。
    """
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
    """查询跟随脚本当前运行状态"""
    global _follow_proc
    running = _follow_proc is not None and _follow_proc.poll() is None
    return jsonify({
        "ok": True,
        "running": running,
        "pid": _follow_proc.pid if running else None,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
