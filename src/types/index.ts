export type InspectionStatus = 'IDLE' | 'ADDING' | 'SAVED' | 'RUNNING' | 'PAUSED'

export interface RobotStatus {
  connected: boolean
  battery: number
  voltage: number
  speed: number
  angularVelocity: number
  latency: number
  mode: string
  navStatus: 'navigating' | 'paused' | 'idle' | 'error'
  x: number
  y: number
  theta: number
  poseSource?: 'amcl' | 'odom' | 'mock'
}

export interface MapOrigin {
  x: number
  y: number
  theta: number
}

export interface MapInfo {
  name: string
  width: number
  height: number
  resolution: number
  origin: MapOrigin
  occupied: boolean[][]
  data: number[][]
}

export interface OccupancyGridInfo {
  width: number
  height: number
  resolution: number
  origin: {
    position: { x: number; y: number; z: number }
    orientation: { x: number; y: number; z: number; w: number }
  }
}

export interface OccupancyGrid {
  header: {
    seq: number
    stamp: { sec: number; nanosec: number }
    frame_id: string
  }
  info: OccupancyGridInfo
  data: number[] | string
}

export interface MapBuffer {
  data: Uint8Array
  width: number
  height: number
  resolution: number
  originX: number
  originY: number
}

export interface Waypoint {
  id: string
  x: number
  y: number
  yaw: number
  qz: number
  qw: number
  name: string
  order: number
}

export interface WaypointEditState {
  stage: number
  start: { wx: number; wy: number; cx: number; cy: number } | null
  current: { cx: number; cy: number } | null
}

export interface MapRenderState {
  width: number
  height: number
  resolution: number
  origin: { position: { x: number; y: number; z: number }; orientation: { x: number; y: number; z: number; w: number } } | null
  offsetX: number
  offsetY: number
  scale: number
}

export interface Path {
  id: string
  name: string
  waypoints: Waypoint[]
}

export interface SavedRoute {
  id: string
  name: string
  waypoints: { x: number; y: number; yaw: number; qz: number; qw: number }[]
  createdAt: string
}

export interface NavigationStatus {
  active: boolean
  paused: boolean
  currentWaypointIndex: number
  progress: number
}

export interface LogEntry {
  time: string
  level: 'info' | 'warn' | 'error' | 'debug'
  source: string
  message: string
}

export type ActiveTool = 'map' | 'mapping' | 'navigation' | 'taskchain' | 'log' | 'settings'

export type TaskNodeType = 'nav' | 'charge' | 'wait' | 'robot'

export interface TaskNode {
  id: string
  type: TaskNodeType
  params: Record<string, any>
  expanded: boolean
}

export type TaskChainStatus = 'idle' | 'running' | 'paused' | 'completed' | 'error'

export interface DrawPoint {
  id: string
  x: number
  y: number
}

export interface DrawLine {
  id: string
  points: { x: number; y: number }[]
}

export type DrawMode = 'none' | 'point' | 'line'

// ===== 地图编辑器（禁行区 / 虚拟墙 / 轨迹 / POI）=====
export type EditorMode = 'none' | 'wall-polygon' | 'path' | 'poi'

export interface Wall {
  id: string
  shape: 'rect' | 'polygon'
  points: { x: number; y: number }[]
}

export interface CustomPath {
  id: string
  points: { x: number; y: number }[]
}

export interface Poi {
  id: string
  x: number
  y: number
  name: string
}

export interface PlanPose {
  x: number
  y: number
  theta: number
}

export interface PlanPath {
  poses: PlanPose[]
}

export interface MapEditorPayload {
  virtual_walls: Wall[]
  custom_paths: CustomPath[]
  pois: Poi[]
}

// ============================================================
// 跟随模式 — DJI 焦点跟随系统
// ============================================================

/** 跟随挡位/模式枚举 */
export type FollowModeType = 'parallel' | 'trace' | 'orbit'

/** 检测框体（像素坐标，由 YOLO 节点发布） */
export interface YoloBBox {
  x_min: number
  y_min: number
  x_max: number
  y_max: number
}

/** 单个 YOLO 检测结果 */
export interface YoloDetection {
  bbox: YoloBBox
  confidence: number
  class_id: number
  class_name?: string
}

/** /yolo_detections 话题消息结构 */
export interface YoloDetectionsMsg {
  header?: { stamp?: { sec: number; nanosec: number }; frame_id?: string }
  detections: YoloBBox[]
  confidences: number[]
  class_ids: number[]
  class_names?: string[]
  image_width: number
  image_height: number
}

/** 前端渲染用的检测目标（已合并为单一对象） */
export interface DetectionTarget {
  id: number
  cx: number
  cy: number
  bbox: YoloBBox
  confidence: number
  classId: number
  className: string
}
