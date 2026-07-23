# 智能巡检平台控制系统（PRD）

## 项目目标

构建一个基于 **Vue3 + ROS2 + Foxglove Bridge**
的智能巡检平台控制系统，用于无人车、AGV、巡检机器人地面站。

## 页面布局

``` text
┌──────────────────────────────────────────────────────────────┐
│ Header：Logo｜IP连接｜状态｜建图｜定位｜导航｜急停            │
├───────────────┬──────────────────────────────┬───────────────┤
│ 左侧工具栏     │        地图/SLAM区域(70%)     │ 右侧控制面板   │
│ - 建图        │ - 网格地图                   │ - 建图控制     │
│ - 定位        │ - 航点编辑                   │ - 地图管理     │
│ - 导航        │ - 路径规划                   │ - 手动控制     │
│ - 日志        │ - 实时机器人                 │ - 属性面板     │
├──────────────────────────────────────────────────────────────┤
│ Bottom：FPS｜ROS状态｜WebSocket｜CPU｜Memory｜时间           │
└──────────────────────────────────────────────────────────────┘
```

## 核心模块

### Header

-   Logo
-   IP 输入框
-   Port 输入框
-   开始连接
-   断开连接
-   重连
-   在线状态
-   电池、电压、速度、模式

### 左侧工具栏

-   地图浏览
-   建图
-   定位
-   导航
-   航点编辑
-   路径编辑
-   虚拟墙
-   日志
-   设置

### 中央地图

-   二维 SLAM 地图
-   缩放、拖拽
-   点击添加航点
-   路径生成
-   机器人实时位置
-   激光雷达扫描
-   历史轨迹

### 右侧控制面板

#### 建图

-   开始建图
-   停止建图
-   保存地图
-   加载地图
-   删除地图
-   切换地图
-   重定位

#### 导航

-   添加航点
-   删除航点
-   保存路线
-   加载路线
-   开始导航
-   暂停
-   继续
-   取消

#### 手动控制

-   九宫格方向控制
-   急停
-   线速度 Slider
-   角速度 Slider
-   键盘 WASD 预留
-   手柄接口预留

## 数据面板

Tabs： - Robot - Map - Navigation - Task - ROS Topic - Console

## ROS2 API 预留

``` ts
connectRobot()
disconnectRobot()
startMapping()
saveMap()
startLocalization()
startNavigation()
pauseNavigation()
resumeNavigation()
cancelNavigation()
sendVelocity()
```

## 技术栈

-   Vue3
-   Vite
-   TypeScript
-   Element Plus
-   Pinia
-   Vue Router
-   SCSS
-   Canvas

## UI 风格

-   工业科技风
-   浅灰+蓝色
-   圆角8px
-   卡片布局
-   响应式
-   动效 200ms

## 开发目标

-   模块化组件
-   Mock 数据可演示
-   后续无缝接入 ROS2、Foxglove、Nav2、SLAM Toolbox。
