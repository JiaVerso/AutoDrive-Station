# 智能巡检平台控制系统

基于 Vue3 + TypeScript + Element Plus 构建的智能巡检机器人平台控制系统前端应用，支持与 ROS2 Bridge 实时通信，提供地图可视化、导航控制、3D点云渲染和摄像头监控等功能。

## 功能特性

### 🏠 主界面布局

- **左侧导航栏**：建图、导航、摄像头、SLAM云四个模块切换
- **中央地图区域**：基于 Canvas 的 2D SLAM 地图渲染，支持缩放、拖拽、点云实时显示
- **右侧控制面板**：根据左侧选择显示对应模块的详细控制界面
- **底部状态栏**：实时监控 FPS、ROS 状态、WebSocket 状态、系统资源占用
- **数据面板**：ROS话题列表、消息类型、实时数据预览

### 🗺️ 地图功能

- 地图加载与保存
- 建图模式（开始/停止建图）
- 重定位功能
- 地图缩放与拖拽
- 机器人位置标记与方向指示
- 2D点云实时显示（来自多个雷达话题）
- 自动居中对齐点云数据

### 🧭 导航功能

- **航点绘制**：点击地图添加单个航点，或连续绘制航线
- **航点管理**：查看、删除单个航点，清除所有航点
- **路线管理**：保存、加载、删除路线
- **导航控制**：开始、暂停、继续、取消导航
- **进度显示**：实时显示导航进度和当前航点
- **绘制模式限制**：仅在导航模块且启用"添加航点"模式时可绘制，默认选择/拖拽模式

### 📷 摄像头功能

- 车载摄像头画面显示（`/camera/image_raw` 话题，CompressedImage 格式）
- 帧率统计
- 支持 JPEG 压缩图像

### ☁️ 3D点云

- Three.js 3D点云渲染
- 实时接收多个雷达话题数据
- 交互式旋转（左键拖动）和缩放（滚轮）
- 网格辅助线和坐标轴显示
- 点云数量实时统计

### 🎮 手动控制

- 方向控制：前后左右移动、停止
- 急停按钮
- 速度调节：线速度、角速度滑块
- 巡航模式开关

## 技术栈

| 技术 | 版本 | 说明 |
|------|------|------|
| Vue | 3.5.x | 前端框架 |
| TypeScript | 6.0.x | 类型安全 |
| Vite | 8.1.x | 构建工具 |
| Element Plus | 2.14.x | UI组件库 |
| Pinia | 3.0.x | 状态管理 |
| Vue Router | 4.6.x | 路由管理 |
| SCSS | 1.101.x | CSS预处理器 |
| Three.js | 0.158.x | 3D点云渲染 |
| roslib | 1.x | ROS2 WebSocket通信 |
| Canvas | - | 2D地图渲染 |

## 快速开始

### 环境要求

- Node.js >= 18.0.0
- npm >= 9.0.0
- Ubuntu 22.04 + ROS2 Humble（后端）

### 前端安装与运行

```bash
# 进入前端项目目录
cd inspection-platform

# 安装依赖
npm install

# 开发模式运行
npm run dev

# 访问地址
# http://localhost:5173
```

### 生产构建

```bash
npm run build
npm run preview
```

### 代码检查

```bash
npm run lint
```

## 后端配置（Ubuntu 22.04 + ROS2 Humble）

### 1. 安装 ROS2 Humble

```bash
# 添加 ROS2 仓库
sudo apt update && sudo apt install curl gnupg lsb-release
curl -s https://raw.githubusercontent.com/ros/rosdistro/master/ros.asc | sudo apt-key add -
echo "deb [arch=$(dpkg --print-architecture)] http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null

# 安装 ROS2 Humble
sudo apt update
sudo apt install ros-humble-desktop

# 安装 rosbridge
sudo apt install ros-humble-rosbridge-server

# 安装 Python 依赖
pip install opencv-python numpy
```

### 2. 运行 rosbridge 服务

```bash
# 每次打开终端都需要 source
source /opt/ros/humble/setup.bash

# 启动 rosbridge websocket 服务
ros2 launch rosbridge_server rosbridge_websocket_launch.xml

# 默认端口为 9090
```

### 3. 运行机器人模拟器

将 `linux/robot_simulator.py` 文件复制到 Ubuntu 中：

```bash
# 确保 test.pcd 文件在同一目录下
# 将 robot_simulator.py 复制到 Ubuntu

# 赋予执行权限
chmod +x robot_simulator.py

# 运行模拟器
python3 robot_simulator.py
```

**模拟器功能**：
- 发布摄像头图像（从电脑摄像头读取）
- 发布点云数据（从 test.pcd 文件加载）
- 发布机器人位姿、电池状态、地图等模拟数据
- 订阅速度指令、安全状态、巡航指令等

## 项目结构

```
inspection-platform/
├── src/
│   ├── components/          # 组件目录
│   │   ├── Header.vue       # 顶部导航栏
│   │   ├── LeftToolbar.vue  # 左侧工具栏
│   │   ├── MapCanvas.vue    # 地图画布（2D渲染）
│   │   ├── RightPanel.vue   # 右侧控制面板
│   │   ├── BottomBar.vue    # 底部状态栏
│   │   ├── DataPanel.vue    # 数据面板（ROS话题）
│   │   └── PointCloud3D.vue # 3D点云组件
│   ├── stores/              # Pinia状态管理
│   │   ├── robot.ts         # 机器人状态与ROS通信
│   │   ├── map.ts           # 地图状态与点云处理
│   │   └── navigation.ts    # 导航状态与航点管理
│   ├── types/               # TypeScript类型定义
│   │   └── index.ts         # 类型声明
│   ├── api/                 # API接口
│   │   └── ros.ts           # ROS接口（roslib实现）
│   ├── utils/               # 工具函数
│   │   ├── pointCloudParser.ts # 点云解析器
│   │   └── coordinateConverter.ts # 坐标转换工具
│   ├── mock/                # Mock数据
│   │   └── data.ts          # 模拟数据
│   ├── styles/              # 全局样式
│   │   └── variables.scss   # 样式变量
│   ├── App.vue              # 根组件
│   ├── main.ts              # 入口文件
│   └── router/index.ts      # 路由配置
├── linux/                   # Linux 后端文件
│   └── robot_simulator.py   # 机器人数据模拟器
├── index.html               # HTML模板
├── package.json             # 项目配置
├── vite.config.ts           # Vite配置
├── tsconfig.json            # TypeScript配置
└── README.md                # 项目说明
```

## ROS2 通信配置

### 自动订阅话题

连接成功后自动订阅以下话题：

| 话题 | 消息类型 | 说明 |
|------|----------|------|
| `/turtle1/pose` | `turtlesim/msg/Pose` | 机器人位姿 |
| `/battery_state` | `sensor_msgs/msg/BatteryState` | 电池状态 |
| `/robot_mode` | `std_msgs/msg/String` | 运行模式 |
| `/map` | `nav_msgs/msg/OccupancyGrid` | 2D栅格地图 |
| `/terrain_points_downsampled` | `sensor_msgs/msg/PointCloud2` | 地形点云 |
| `/lidar_points` | `sensor_msgs/msg/PointCloud2` | 激光雷达点云 |
| `/scan/points` | `sensor_msgs/msg/PointCloud2` | 扫描点云 |
| `/point_cloud` | `sensor_msgs/msg/PointCloud2` | 通用点云 |
| `/livox/lidar` | `livox_ros_driver2/msg/CustomMsg` | Livox雷达数据 |

### 发布话题

| 话题 | 消息类型 | 说明 |
|------|----------|------|
| `/cmd_vel` | `geometry_msgs/msg/Twist` | 速度指令 |
| `/safety_status` | `std_msgs/msg/Bool` | 安全状态 |
| `/cruise_cmd` | `std_msgs/msg/Bool` | 巡航指令 |
| `/goal_pose` | `geometry_msgs/msg/PoseStamped` | 导航目标 |
| `/waypoints_json` | `std_msgs/msg/String` | 航点JSON数据 |

### 服务调用

| 服务 | 类型 | 说明 |
|------|------|------|
| `/start_mapping` | `std_srvs/srv/Trigger` | 开始建图 |
| `/save_map` | `std_srvs/srv/Trigger` | 保存地图 |
| `/start_localization` | `std_srvs/srv/Trigger` | 开始定位 |
| `/navigate_to_pose` | `std_srvs/srv/Trigger` | 开始导航 |

## 使用说明

### 完整使用流程

1. **启动后端服务**（Ubuntu）：
   ```bash
   source /opt/ros/humble/setup.bash
   ros2 launch rosbridge_server rosbridge_websocket_launch.xml
   ```

2. **启动机器人模拟器**（Ubuntu）：
   ```bash
   python3 robot_simulator.py
   ```

3. **启动前端**（Windows）：
   ```bash
   cd inspection-platform
   npm run dev
   ```

4. **连接 ROS2 Bridge**：
   - 在前端界面右上角输入 Ubuntu 的 IP 地址（默认端口 9090）
   - 点击"连接"按钮

5. **查看数据**：
   - 连接成功后，地图、点云、摄像头画面会自动显示
   - 可在底部数据面板查看 ROS 话题列表和实时数据

### 绘制航点

1. 点击左侧导航栏"导航"
2. 在右侧面板选择"添加航点"模式
3. 点击地图添加航点（必须在地图范围内）
4. 可通过"绘制航线"模式连续添加多个航点，双击结束
5. 点击"完成航线"确认航点绘制

### 发送航点到后端

1. 绘制完成后，点击"发送航点"按钮
2. 航点数据会通过 `/waypoints_json` 话题发送到后端
3. 后端接收到后会自动保存为JSON文件

### 航点JSON格式

```json
{
  "timestamp": 1783388595000,
  "waypoints": [
    {
      "id": "wp1",
      "name": "航点1",
      "x": 5.23,
      "y": 3.45,
      "order": 1
    },
    {
      "id": "wp2",
      "name": "航点2",
      "x": 8.91,
      "y": 6.23,
      "order": 2
    }
  ],
  "path": {
    "id": "path_1783388595000",
    "name": "巡检路线"
  },
  "count": 2
}
```

### 导航控制

1. 添加航点后，点击"保存路线"保存当前航线
2. 选择路线后点击"开始导航"启动导航
3. 可随时暂停、继续或取消导航

### 地图操作

- **缩放**：鼠标滚轮
- **拖拽**：选择模式下点击并拖动地图
- **绘制**：选择对应绘制模式后点击地图

### 3D点云操作

- **旋转**：左键拖动
- **缩放**：滚轮

## 注意事项

- 需要运行 ROS2 Bridge 后端服务才能接收真实数据
- 连接地址格式：`ws://<IP>:<PORT>`，默认端口 9090
- 建议使用 Chrome 浏览器以获得最佳体验
- 地图边界约束：绘制点和线必须在地图范围内
- 点云数据需要支持 `sensor_msgs/msg/PointCloud2` 格式
- 摄像头图像需要使用 `sensor_msgs/msg/CompressedImage` 格式（JPEG）
- 机器人模拟器需要 `test.pcd` 文件放在同一目录下（支持 ASCII 和 binary 格式）
- 摄像头设备需要正确权限：`sudo chmod 666 /dev/video*`

## License

MIT License