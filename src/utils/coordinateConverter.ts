import type { MapInfo, MapRenderState } from '@/types'

/**
 * 标准的 ROS 米坐标 <-> Canvas 像素坐标转换。
 *
 * 约定（与 nav_msgs/OccupancyGrid 完全一致）：
 *  - ROS 世界 X 向右、Y 向上；Canvas 像素 Y 向下。
 *  - 地图元数据 origin = 地图左下角(cell 0,0) 在 ROS 世界系中的物理坐标（通常为负数）。
 *  - resolution = 每个栅格的边长（米）。
 *  - 像素坐标以“cell 连续值”表示（再乘以 cellSize 与 zoom 得到实际屏幕像素）。
 *
 * 注意：这里使用 map.height（而非 height-1），与地图位图以“cell 中心”渲染的
 * 约定严格一致，保证小车/航点图标与地图栅格 1:1 对齐（消除半个栅格的偏移）。
 */

/** ROS 米坐标 -> 地图像素坐标（连续 cell 值） */
export function rosToCanvas(rosX: number, rosY: number, map: MapInfo): { x: number; y: number } {
  const relX = rosX - map.origin.x
  const relY = rosY - map.origin.y
  const pixelX = relX / map.resolution
  // ROS Y 向上 -> Canvas Y 向下，用整张地图高度翻转
  const pixelY = map.height - relY / map.resolution
  return { x: pixelX, y: pixelY }
}

/** 地图像素坐标（连续 cell 值） -> ROS 米坐标 */
export function canvasToRos(pixelX: number, pixelY: number, map: MapInfo): { x: number; y: number } {
  const relX = pixelX * map.resolution
  const relY = (map.height - pixelY) * map.resolution
  const rosX = relX + map.origin.x
  const rosY = relY + map.origin.y
  return { x: rosX, y: rosY }
}

// ---- 兼容旧调用别名的统一实现（单一真相来源）----
export const physicalToMapPixel = rosToCanvas
export const mapPixelToPhysical = canvasToRos

/** ROS 米坐标 + 画布变换参数 -> 屏幕像素坐标 */
export function physicalToScreen(
  physicalX: number,
  physicalY: number,
  map: MapInfo,
  cellSize: number,
  offsetX: number,
  offsetY: number,
  zoom: number
): { x: number; y: number } {
  const { x: px, y: py } = rosToCanvas(physicalX, physicalY, map)
  return {
    x: px * cellSize * zoom + offsetX,
    y: py * cellSize * zoom + offsetY,
  }
}

/** 屏幕像素坐标 -> ROS 米坐标（点击下发 /initialpose、航点时使用的逆运算） */
export function screenToPhysical(
  screenX: number,
  screenY: number,
  map: MapInfo,
  cellSize: number,
  offsetX: number,
  offsetY: number,
  zoom: number
): { x: number; y: number } {
  const mapX = (screenX - offsetX) / (zoom * cellSize)
  const mapY = (screenY - offsetY) / (zoom * cellSize)
  return canvasToRos(mapX, mapY, map)
}

/**
 * ROS 偏航角(弧度, 逆时针为正) -> Canvas 绘制弧度。
 * 因为 Canvas 的 Y 轴向下，旋转方向恰好相反，需要取反。
 */
export function rosYawToCanvas(yawRad: number): number {
  return -yawRad
}

/** Canvas 绘制弧度 -> ROS 偏航角(弧度) */
export function canvasToRosYaw(drawAngleRad: number): number {
  return -drawAngleRad
}

export function yawToQuaternion(yaw: number): { x: number; y: number; z: number; w: number } {
  return { x: 0, y: 0, z: Math.sin(yaw / 2), w: Math.cos(yaw / 2) }
}

export function quaternionToYaw(q: { x?: number; y?: number; z?: number; w?: number } | null | undefined): number {
  if (!q) return 0
  return Math.atan2(2 * (q.w || 1) * (q.z || 0), 1 - 2 * ((q.z || 0) * (q.z || 0)))
}

// ---- 保留以下兼容函数（统一到上述标准实现）----
export function canvasToWorld(
  cx: number,
  cy: number,
  state: MapRenderState
): { x: number; y: number } | null {
  const { origin, resolution, height, offsetX, offsetY, scale } = state
  if (!origin || scale === 0) return null

  const mapPxX = (cx - offsetX) / scale
  const mapPxY = (cy - offsetY) / scale

  const rx = origin.position.x + mapPxX * resolution
  const ry = origin.position.y + (height - mapPxY) * resolution

  return { x: rx, y: ry }
}

export function worldToCanvas(
  rx: number,
  ry: number,
  state: MapRenderState
): { cx: number; cy: number } | null {
  const { origin, resolution, height, offsetX, offsetY, scale } = state
  if (!origin || scale === 0) return null

  const mapPxX = (rx - origin.position.x) / resolution
  const rowFromBottom = (ry - origin.position.y) / resolution
  const mapPxY = height - rowFromBottom

  const cx = offsetX + mapPxX * scale
  const cy = offsetY + mapPxY * scale

  return { cx, cy }
}

export function computeMapRenderState(
  map: MapInfo,
  canvasWidth: number,
  canvasHeight: number
): MapRenderState {
  const scaleX = canvasWidth / map.width
  const scaleY = canvasHeight / map.height
  const scale = Math.min(scaleX, scaleY)

  const offsetX = (canvasWidth - map.width * scale) / 2
  const offsetY = (canvasHeight - map.height * scale) / 2

  return {
    width: map.width,
    height: map.height,
    resolution: map.resolution,
    origin: {
      position: { x: map.origin.x, y: map.origin.y, z: 0 },
      orientation: { x: 0, y: 0, z: 0, w: 1 }
    },
    offsetX,
    offsetY,
    scale
  }
}
