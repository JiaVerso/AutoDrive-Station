# 智能巡检小车控制平台（AutoDrive-Station）

基于 Vue3 + TypeScript + Element Plus 构建的智能巡检机器人平台控制系统前端应用，支持与 ROS2 Bridge 实时通信，提供地图可视化、导航控制、3D点云渲染和摄像头监控等功能。

## 功能特性

- **地图擦除与修补**：在网页上直接用画笔和橡皮擦对 ROS 2 地图进行实时修改，擦掉噪点后一键保存覆盖小车本地地图
- **拖拽式任务链条**：像搭积木一样，把"导航到某点"、"去充电"、"原地等待"等卡片拖到画布里串成一条线，点击"一键启动"
- **动态地址，跨设备可用**：前端自动读取连接的小车真实 IP，哪怕前端不在小车上跑也能畅通保存

### 主界面布局

- **左侧导航栏**：建图、导航、摄像头、SLAM云四个模块切换
- **中央地图区域**：基于 Canvas 的 2D SLAM 地图渲染，支持缩放、拖拽、点云实时显示
- **右侧控制面板**：根据左侧选择显示对应模块的详细控制界面
- **底部状态栏**：实时监控 FPS、ROS 状态、WebSocket 状态、系统资源占用

### 地图功能

- 地图加载与保存、建图模式、重定位功能
- 地图缩放与拖拽、机器人位置标记与方向指示
- 2D点云实时显示（来自多个雷达话题）

### 导航功能

- **航点绘制**：点击地图添加单个航点，或连续绘制航线
- **路线管理**：保存、加载、删除路线
- **导航控制**：开始、暂停、继续、取消导航

### 手动控制

- 方向控制：前后左右移动、停止、急停按钮
- 速度调节：线速度、角速度滑块

## 技术栈

| 技术 | 版本 | 说明 |
|------|------|------|
| Vue | 3.5.x | 前端框架 |
| TypeScript | 6.0.x | 类型安全 |
| Vite | 8.1.x | 构建工具 |
| Element Plus | 2.14.x | UI组件库 |
| Pinia | 3.0.x | 状态管理 |
| SCSS | 1.101.x | CSS预处理器 |
| Three.js | 0.158.x | 3D点云渲染 |
| roslib | 2.1.x | ROS2 WebSocket通信 |

## 快速开始

### 环境要求

- Node.js >= 18.0.0
- npm >= 9.0.0
- Ubuntu 22.04 + ROS2 Humble（后端）

### 安装与运行

```bash
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

## 项目结构

```
仓库根目录/
├── src/
│   ├── components/          # 组件目录
│   │   ├── Header.vue       # 顶部导航栏
│   │   ├── LeftToolbar.vue  # 左侧工具栏
│   │   ├── MapCanvas.vue    # 地图画布（2D渲染）
│   │   ├── RightPanel.vue   # 右侧控制面板
│   │   ├── BottomBar.vue    # 底部状态栏
│   │   ├── DataPanel.vue    # 数据面板（ROS话题）
│   │   ├── FollowCameraPopup.vue  # 摄像头跟随弹窗
│   │   └── TaskChain.vue    # 任务链组件
│   ├── stores/              # Pinia状态管理
│   │   ├── robot.ts         # 机器人状态与ROS通信
│   │   ├── map.ts           # 地图状态与点云处理
│   │   ├── navigation.ts    # 导航状态与航点管理
│   │   └── taskChain.ts     # 任务链状态
│   ├── api/
│   │   └── ros.ts           # ROS接口（roslib实现）
│   ├── utils/
│   │   ├── coordinateConverter.ts  # 坐标转换
│   │   └── pointCloudParser.ts     # 点云解析
│   ├── mock/data.ts         # Mock数据
│   ├── styles/
│   │   ├── global.scss      # 全局样式
│   │   └── variables.scss   # 样式变量
│   ├── types/index.ts       # TypeScript类型定义
│   ├── workers/camera.worker.ts  # 摄像头Worker
│   ├── composables/         # 组合式函数
│   │   ├── useFollowMode.ts
│   │   └── useTheme.ts
│   ├── App.vue              # 根组件
│   └── main.ts              # 入口文件
├── public/                  # 静态资源
├── index.html               # HTML模板
├── package.json             # 项目配置
├── vite.config.ts           # Vite配置
├── tsconfig.json            # TypeScript配置
├── 智能巡检平台控制系统_PRD.md  # 产品需求文档
└── README.md                # 项目说明
```

## ROS2 通信配置

### 自动订阅话题

| 话题 | 消息类型 | 说明 |
|------|----------|------|
| `/amcl_pose` | `geometry_msgs/msg/PoseWithCovarianceStamped` | 机器人位姿 |
| `/map` | `nav_msgs/msg/OccupancyGrid` | 2D栅格地图 |
| `/inspection_status` | `std_msgs/msg/String` | 任务状态反馈 |

### 发布话题

| 话题 | 消息类型 | 说明 |
|------|----------|------|
| `/initialpose` | `geometry_msgs/msg/PoseWithCovarianceStamped` | 重定位 |
| `/inspection_control` | `std_msgs/msg/String` | 巡检控制指令 |
| `/navigate_through_poses` | `nav2_msgs/action/NavigateThroughPoses` | 多航点巡检任务 |

## 注意事项

- 需要运行 ROS2 Bridge 后端服务才能接收真实数据
- 连接地址格式：`ws://<IP>:<PORT>`，默认端口 9090
- 建议使用 Chrome 浏览器以获得最佳体验

## License

Apache 2.0
