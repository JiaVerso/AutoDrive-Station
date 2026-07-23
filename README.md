# 智能巡检小车控制平台（AutoDrive-Station）

基于 Vue 3 + TypeScript + ROS2 (Humble) + Nav2 构建的智能巡检机器人平台控制系统，支持 Web 端遥控、地图高精编辑、多航点巡检任务链调度及实时状态监测。

---

## 目录结构 (Directory Architecture)

```text
SparkMoveCarWeb/
├── linux/                          # ROS2 后端 Python 核心服务
│   ├── inspection_controller.py    # 巡检控制核心 (AMCL位姿校验 / Nav2联动)
│   ├── map_edit_server.py          # 地图编辑 / 禁行区 / POI 保存服务
│   ├── task_chain_manager.py       # 巡检任务链与多航点调度管理
│   ├── unified_backend.py          # 统一后端启动入口
│   └── robot_simulator.py          # (可选) 仿真测试脚本
├── src/                            # Vue3 前端源码
│   ├── components/                 # 组件目录
│   │   ├── Header.vue              # 顶部导航栏
│   │   ├── LeftToolbar.vue         # 左侧工具栏
│   │   ├── MapCanvas.vue           # 地图画布（2D渲染）
│   │   ├── RightPanel.vue          # 右侧控制面板
│   │   ├── BottomBar.vue           # 底部状态栏
│   │   ├── DataPanel.vue           # 数据面板（ROS话题）
│   │   ├── FollowCameraPopup.vue   # 摄像头跟随弹窗
│   │   └── TaskChain.vue           # 任务链组件
│   ├── stores/                     # Pinia 状态管理
│   │   ├── robot.ts                # 机器人状态与 ROS 通信
│   │   ├── map.ts                  # 地图状态与点云处理
│   │   ├── navigation.ts           # 导航状态与航点管理
│   │   └── taskChain.ts            # 任务链状态
│   ├── api/
│   │   └── ros.ts                  # ROS 接口（roslib 实现）
│   ├── utils/
│   │   ├── coordinateConverter.ts  # 坐标转换
│   │   └── pointCloudParser.ts     # 点云解析
│   ├── mock/data.ts                # Mock 数据
│   ├── styles/
│   │   ├── global.scss             # 全局样式
│   │   └── variables.scss          # 样式变量
│   ├── types/index.ts              # TypeScript 类型定义
│   ├── workers/camera.worker.ts    # 摄像头 Worker
│   ├── composables/                # 组合式函数
│   │   ├── useFollowMode.ts
│   │   └── useTheme.ts
│   ├── App.vue                     # 根组件
│   └── main.ts                     # 入口文件
├── public/                         # 静态资源
├── index.html                      # HTML 模板
├── package.json                    # 项目配置
├── vite.config.ts                  # Vite 配置
├── tsconfig.json                   # TypeScript 配置
├── 智能巡检平台控制系统_PRD.md       # 产品需求文档
└── README.md                       # 项目说明
```

---

## 环境部署与准备 (Prerequisites)

| 环境 | 版本要求 | 说明 |
|------|----------|------|
| 操作系统 | Ubuntu 22.04 LTS | ROS2 Humble 官方支持平台 |
| ROS2 | Humble Hawksbill | 导航栈 Nav2 |
| Node.js | >= 18.x | 前端构建运行 |
| npm | >= 9.x | 包管理器 |
| Python | >= 3.10 | 后端核心脚本运行 |

**Python 核心依赖：**

- `rclpy`
- `nav2_simple_commander`
- `geometry_msgs`
- `nav_msgs`

---

## Linux 后端服务启动 (Linux Backend)

### 步骤一：加载 ROS2 及导航工作区环境变量

```bash
source /opt/ros/humble/setup.bash
# 替换为你的 ROS2 导航工作区实际路径
source ~/Desktop/SparkCar_ROS2_WS/SparkCar_Navigation/install/setup.bash
```

### 步骤二：运行后端核心服务（三选一或统一启动）

**方式 A（推荐 unified 统一后端）：**

```bash
python3 linux/unified_backend.py
```

**方式 B（按需单独启动核心模块）：**

```bash
# 终端 1：启动巡检控制器
python3 linux/inspection_controller.py

# 终端 2：启动地图编辑服务端
python3 linux/map_edit_server.py

# 终端 3：启动任务链管理器
python3 linux/task_chain_manager.py
```

---

## Web 前端启动 (Web Frontend)

```bash
# 1. 安装项目依赖
npm install

# 2. 启动开发服务器
npm run dev
```

启动成功后，浏览器访问：**http://localhost:5173**

### 生产构建

```bash
npm run build
npm run preview
```

---

## ROS2 通信配置 (ROS2 Configurations)

### 自动订阅话题

| 话题 | 消息类型 | 说明 |
|------|----------|------|
| `/amcl_pose` | `geometry_msgs/msg/PoseWithCovarianceStamped` | 机器人位姿 |
| `/map` | `nav_msgs/msg/OccupancyGrid` | 2D 栅格地图 |
| `/inspection_status` | `std_msgs/msg/String` | 任务状态反馈 |

### 发布话题

| 话题 | 消息类型 | 说明 |
|------|----------|------|
| `/initialpose` | `geometry_msgs/msg/PoseWithCovarianceStamped` | 重定位 |
| `/inspection_control` | `std_msgs/msg/String` | 巡检控制指令 |
| `/navigate_through_poses` | `nav2_msgs/action/NavigateThroughPoses` | 多航点巡检任务 |

### 注意事项

- **ROSBridge 接口：** 确保前端通过 `ws://<机器人IP>:9090` 连接到 `rosbridge_websocket`。
- **AMCL 重定位说明：** `inspection_controller.py` 内置 AMCL 定位保护逻辑。发起巡检前，请先在 RViz 中通过 **2D Pose Estimate** 或从 Web 端设置机器人初始位姿。
- 建议使用 Chrome 浏览器以获得最佳体验。

---

## License

Apache 2.0
