<template>
  <main class="map-canvas-container" ref="containerRef">
    <canvas
      ref="canvasRef"
      class="map-canvas"
      @mousedown="onPointerDown"
      @mousemove="onPointerMove"
      @mouseup="onPointerUp"
      @mouseleave="onPointerLeave"
      @dblclick="onDoubleClick"
      @wheel="onWheel"
      @contextmenu.prevent
    />
    <div v-if="!robotStore.status.connected" class="disconnected-overlay">
      <div class="disconnected-content">
        <div class="radar-bg" aria-hidden="true"></div>
        <div class="tech-icon">
          <el-icon :size="52"><Connection /></el-icon>
        </div>
        <span class="status-text">ROBOT OFFLINE · 等待建立连接</span>
        <span class="status-sub">请在右上角输入机器人IP并发起连接</span>
      </div>
    </div>
    <div v-if="robotStore.status.connected" class="map-overlay">
      <span class="map-name">{{ mapStore.currentMap.name }}</span>
      <span class="map-info" v-if="mapStore.mapBuffer.width > 0">
        {{ mapStore.mapBuffer.width }}x{{ mapStore.mapBuffer.height }}
        | {{ mapStore.currentMap.resolution.toFixed(2) }}m/cell
      </span>
    </div>

    <!-- ===== 地图编辑器浮动工具条 ===== -->
    <div v-if="robotStore.status.connected" class="editor-toolbar">
      <div class="et-title">地图编辑</div>
      <div class="et-group">
        <button class="et-btn" :class="{ active: mapStore.editorMode === 'wall-polygon' }" @click="setMode('wall-polygon')">禁行区·多边形</button>
        <button class="et-btn" :class="{ active: mapStore.editorMode === 'path' }" @click="setMode('path')">轨迹</button>
        <button class="et-btn" :class="{ active: mapStore.editorMode === 'poi' }" @click="setMode('poi')">POI</button>
        <button class="et-btn" :class="{ active: mapStore.editorMode === 'none' }" @click="setMode('none')">浏览</button>
      </div>
      <div class="et-actions">
        <button class="et-btn et-finish" @click="finishDraft">完成</button>
        <button class="et-btn et-clear" @click="clearAll">清空</button>
        <button class="et-btn et-upload" @click="uploadEditor">保存并上传</button>
      </div>
      <div class="et-hint" v-if="mapStore.editorMode === 'wall-polygon' || mapStore.editorMode === 'path'">
        单击添加顶点，双击结束
      </div>
      <div class="et-hint" v-else-if="mapStore.editorMode === 'poi'">
        单击落点后输入名称
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection } from '@element-plus/icons-vue'
import { useMapStore } from '@/stores/map'
import { useRobotStore } from '@/stores/robot'
import { useNavigationStore } from '@/stores/navigation'
import { rosToCanvas, canvasToRos, yawToQuaternion } from '@/utils/coordinateConverter'
import { rosApi } from '@/api/ros'
import * as ROSLIB from 'roslib'
import type { EditorMode, MapInfo } from '@/types'

const mapStore = useMapStore()
const robotStore = useRobotStore()
const navStore = useNavigationStore()

// 将十六进制/CSS 颜色转为带透明度的 rgba，使雷达/路径随主题主色变化
function hexToRgba(color: string, alpha: number): string {
  const hex = color.replace('#', '').trim()
  if (hex.length === 6) {
    const r = parseInt(hex.slice(0, 2), 16)
    const g = parseInt(hex.slice(2, 4), 16)
    const b = parseInt(hex.slice(4, 6), 16)
    return `rgba(${r}, ${g}, ${b}, ${alpha})`
  }
  return color
}

const containerRef = ref<HTMLDivElement>()
const canvasRef = ref<HTMLCanvasElement>()

// 离屏位图缓冲（仅用于栅格/点云像素合成，不参与叠层绘制，非冗余临时画布）
const offscreenCanvas = document.createElement('canvas')
const offscreenCtx = offscreenCanvas.getContext('2d')
const pointCloudCanvas = document.createElement('canvas')
const pointCloudCtx = pointCloudCanvas.getContext('2d')

const cellSize = ref(3)
const mapImageDirty = ref(true)

// ===== 编辑交互状态（两步法：先点位置，再拖/点方向定 yaw）=====
let editStage = 0
let editStart: { wx: number; wy: number } | null = null
let editStartPixel: { cx: number; cy: number } | null = null
let editCurrent: { cx: number; cy: number } | null = null

// ===== 指针状态：区分“拖拽平移”与“点击放置” =====
let isPointerDown = false
let isPanning = false
let movedDuringDrag = false
let lastMouse = { x: 0, y: 0 }
let pointerDownPos = { x: 0, y: 0 }

// ================================================================
// 统一重绘调度（合并 rAF，避免重复绘制）
// ================================================================
let renderScheduled = false
function requestRender() {
  if (renderScheduled) return
  renderScheduled = true
  requestAnimationFrame(() => {
    renderScheduled = false
    drawAll()
  })
}

// ================================================================
// 地图就绪 & 坐标转换（带严格空值守护，绝不抛异常 / 输出 NaN）
// ================================================================
function isEditMode(): boolean {
  return navStore.isInitialPoseMode || navStore.currentStatus === 'ADDING'
}

function getScreenCoords(e: MouseEvent): { sx: number; sy: number } {
  const c = canvasRef.value!
  const rect = c.getBoundingClientRect()
  return { sx: e.clientX - rect.left, sy: e.clientY - rect.top }
}

/** 严格校验地图元数据是否可用，避免 origin/resolution 缺失导致 NaN */
function getReadyMap(): MapInfo | null {
  const m = mapStore.currentMap
  if (!m || !m.width || !m.height || !m.resolution) return null
  if (m.origin.x === undefined || m.origin.y === undefined) return null
  return m
}

/** ROS 米坐标 -> 连续 cell 坐标（地图坐标系，Y 向上）。地图未就绪返回 null */
function rosToCell(rosX: number, rosY: number): { x: number; y: number } | null {
  const m = getReadyMap()
  if (!m) return null
  return rosToCanvas(rosX, rosY, m)
}

/** 屏幕像素 -> 连续 cell 坐标 */
function screenToCell(sx: number, sy: number): { x: number; y: number } | null {
  if (!getReadyMap()) return null
  const z = mapStore.zoom
  const cs = cellSize.value
  if (!z || !cs) return null
  return {
    x: (sx - mapStore.offset.x) / (z * cs),
    y: (sy - mapStore.offset.y) / (z * cs),
  }
}

/** 屏幕像素 -> ROS 米坐标（点击下发 /initialpose、航点、编辑器用） */
function screenToPhysical(sx: number, sy: number): { x: number; y: number } | null {
  const c = screenToCell(sx, sy)
  const m = getReadyMap()
  if (!c || !m) return null
  return canvasToRos(c.x, c.y, m)
}

/** 屏幕像素 -> 画布预缩放坐标（用于两步法绘制方向预览线） */
function screenToPreScale(sx: number, sy: number): { cx: number; cy: number } {
  const z = mapStore.zoom || 1
  return {
    cx: (sx - mapStore.offset.x) / z,
    cy: (sy - mapStore.offset.y) / z,
  }
}

// ===== 地图手绘编辑：将鼠标位置映射到 OccupancyGrid 像素并涂抹 =====
// 画布坐标系（ImageData）row=0 在顶部，ROS 栅格 row=0 在底部，
// 因此 rosRow = height - 1 - canvasRowTop（与 buildOccupancyImageData 完全一致）。
function paintAtEvent(e: MouseEvent) {
  const { sx, sy } = getScreenCoords(e)
  const cell = screenToCell(sx, sy)
  const buf = mapStore.mapBuffer
  const w = buf.width
  const h = buf.height
  if (!cell || !w || !h) return

  const col = Math.floor(cell.x)
  const canvasRowTop = Math.floor(cell.y)
  const r = Math.floor(mapStore.brushSize / 2)
  const value = mapStore.mapEditTool === 'pencil' ? 100 : 0

  for (let dy = -r; dy <= r; dy++) {
    for (let dx = -r; dx <= r; dx++) {
      const tc = col + dx
      const tr = canvasRowTop + dy
      if (tc < 0 || tc >= w || tr < 0 || tr >= h) continue
      const rosRow = h - 1 - tr
      const idx = rosRow * w + tc
      mapStore.paintCell(idx, value)
    }
  }
}

// 点击位置是否在地图可通行区域（用于航点落点校验）
function isFreeSpace(x: number, y: number): boolean {
  const m = mapStore.currentMap
  const buf = mapStore.mapBuffer
  if (!m.width || !buf.data.length) return true
  if (!m.resolution || m.origin.x === undefined || m.origin.y === undefined) return true
  const col = Math.floor((x - m.origin.x) / m.resolution)
  const rosRow = Math.floor((y - m.origin.y) / m.resolution)
  if (col < 0 || col >= m.width || rosRow < 0 || rosRow >= m.height) return false
  const idx = rosRow * buf.width + col
  if (idx < buf.data.length && buf.data[idx] === 255) return false
  return true
}

// ===== 射线法（Ray-casting）判断点是否落入多边形禁行区 =====
function pointInPolygon(px: number, py: number, poly: { x: number; y: number }[]): boolean {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i].x
    const yi = poly[i].y
    const xj = poly[j].x
    const yj = poly[j].y
    const intersect =
      yi > py !== yj > py &&
      px < ((xj - xi) * (py - yi)) / (yj - yi) + xi
    if (intersect) inside = !inside
  }
  return inside
}

// 判断 ROS 坐标 (wx, wy) 是否落在任一禁行区（多边形顶点数组）内。
// 全部走 pointInPolygon（射线法），要求 points.length >= 3。
function pointInWall(wx: number, wy: number): boolean {
  for (const w of mapStore.walls) {
    if (!w.points || w.points.length < 3) continue
    if (pointInPolygon(wx, wy, w.points)) return true
  }
  return false
}

// ================================================================
// 离屏位图合成
// ================================================================
function calcCellSize(canvasWidth: number, canvasHeight: number): number {
  const map = mapStore.currentMap
  if (!map.width || !map.height) return 3
  return Math.min(
    (canvasWidth - 40) / map.width,
    (canvasHeight - 40) / map.height,
    20
  )
}

function buildOccupancyImageData(): ImageData | null {
  const buf = mapStore.mapBuffer
  if (!buf.data.length || buf.width === 0 || buf.height === 0) return null
  if (!offscreenCtx) return null

  offscreenCanvas.width = buf.width
  offscreenCanvas.height = buf.height

  const imageData = offscreenCtx.createImageData(buf.width, buf.height)
  const pixels = imageData.data
  const raw = buf.data
  const len = buf.width * buf.height

  for (let i = 0; i < len; i++) {
    const canvasRow = Math.floor(i / buf.width)
    const col = i % buf.width
    const rosRow = buf.height - 1 - canvasRow
    const v = raw[rosRow * buf.width + col]
    const pi = i << 2

    // RViz 风格静态地图配色（作为 Canvas 最底层背景）：
    //   0   (自由)    -> 白色
    //   100 (障碍)    -> 近黑色
    //   1~99(代价)    -> 白->黑 灰度过渡
    //   -1  (未知)    -> 浅灰色（不透明，避免与暗色画布背景混淆）
    if (v === 0) {
      pixels[pi] = 248; pixels[pi + 1] = 248; pixels[pi + 2] = 248; pixels[pi + 3] = 255
    } else if (v === 100) {
      pixels[pi] = 25; pixels[pi + 1] = 25; pixels[pi + 2] = 25; pixels[pi + 3] = 255
    } else if (v >= 1 && v <= 99) {
      const t = v / 100
      const g = Math.floor(248 * (1 - t))
      pixels[pi] = g; pixels[pi + 1] = g; pixels[pi + 2] = g; pixels[pi + 3] = 255
    } else {
      // 未知区域：浅灰色（RViz 默认观感）
      pixels[pi] = 205; pixels[pi + 1] = 205; pixels[pi + 2] = 205; pixels[pi + 3] = 255
    }
  }

  offscreenCtx.putImageData(imageData, 0, 0)
  mapImageDirty.value = false
  return imageData
}

function renderPointCloud(cs: number) {
  if (!pointCloudCtx) return
  const map = getReadyMap()
  const points = mapStore.pointCloudData
  if (!map || points.length === 0) return

  pointCloudCanvas.width = map.width * cs
  pointCloudCanvas.height = map.height * cs
  pointCloudCtx.clearRect(0, 0, pointCloudCanvas.width, pointCloudCanvas.height)

  const pixelSize = Math.max(cs * 0.5, 2)

  points.forEach((p) => {
    const px = p.x * cs
    const py = (map.height - p.y) * cs
    if (px < -100 || px > pointCloudCanvas.width + 100 ||
        py < -100 || py > pointCloudCanvas.height + 100) return

    let intensity = p.intensity || 0
    if (intensity > 255) intensity = 255
    if (intensity < 0) intensity = 0
    const ni = intensity / 255
    const blue = Math.floor(64 + ni * 191)
    const green = Math.floor(150 + (1 - ni) * 105)
    const alpha = 0.6 + ni * 0.4

    pointCloudCtx.beginPath()
    pointCloudCtx.fillStyle = `rgba(${green}, ${blue}, 255, ${alpha})`
    pointCloudCtx.arc(px, py, pixelSize / 2, 0, Math.PI * 2)
    pointCloudCtx.fill()
  })

  mapStore.pointCloudDirty = false
}

// ================================================================
// 统一渲染管线 drawAll()：严格顺序
//   1. clearRect
//   2. 静态地图（Map Grid）
//   3. 路径/轨迹线（Nav2 Plan + 巡检路径）
//   4. 编辑器图层（禁行区 / 轨迹 / POI）
//   5. 巡检航点（Waypoints）
//   6. 编辑预览（航点/初始定位）
//   7. 机器人小车（Robot Icon）置顶
// ================================================================
function drawAll() {
  const canvas = canvasRef.value
  const container = containerRef.value
  if (!canvas || !container) return

  const ctx = canvas.getContext('2d')
  if (!ctx || typeof ctx.drawImage !== 'function') return

  if (canvas.width !== container.clientWidth || canvas.height !== container.clientHeight) {
    const oldW = canvas.width || 1
    const oldH = canvas.height || 1
    canvas.width = container.clientWidth
    canvas.height = container.clientHeight
    if (oldW > 0 && oldH > 0) {
      mapStore.offset.x *= canvas.width / oldW
      mapStore.offset.y *= canvas.height / oldH
    }
    cellSize.value = calcCellSize(canvas.width, canvas.height)
  }

  const cs = cellSize.value

  ctx.clearRect(0, 0, canvas.width, canvas.height)

  ctx.save()
  ctx.translate(mapStore.offset.x, mapStore.offset.y)
  ctx.scale(mapStore.zoom, mapStore.zoom)

  // 严格图层顺序：
  //  1) 清空（已在上方 clearRect）
  //  2) 静态栅格地图（OccupancyGrid 背景层）
  //  3) 编辑器图层（禁行区半透明红 / 轨迹 / POI）
  //  4) 动态点云（粉紫雷达）
  //  5) Nav2 路径 + 巡检航点
  //  6) 编辑预览（航点/初始定位）
  //  7) 机器人小车（置顶）
  drawMapGrid(ctx, cs)
  drawEditorLayer(ctx, cs)
  drawPointCloud(ctx, cs)
  drawPlans(ctx, cs)
  drawWaypoints(ctx, cs)
  drawEditPreviews(ctx, cs)
  drawRobot(ctx, cs)

  ctx.restore()
}

function drawMapGrid(ctx: CanvasRenderingContext2D, cs: number) {
  if (mapImageDirty.value || mapStore.mapBufferDirty) {
    buildOccupancyImageData()
    mapStore.mapBufferDirty = false
  }

  if (offscreenCanvas.width > 0 && offscreenCanvas.height > 0) {
    ctx.imageSmoothingEnabled = false
    ctx.drawImage(offscreenCanvas, 0, 0, offscreenCanvas.width * cs, offscreenCanvas.height * cs)
  }

  // 注：动态点云已移至 drawAll 中 drawEditorLayer 之后单独绘制，
  // 保证图层顺序为「静态栅格 → 禁行区 → 点云 → 机器人」。

  const m = getReadyMap()
  if (!m) return

  // 静态标注：用户手绘线（绿）/点（红 ×）
  mapStore.drawLines.forEach((line: { points: { x: number; y: number }[] }) => {
    if (line.points.length < 2) return
    ctx.beginPath()
    ctx.strokeStyle = '#67c23a'
    ctx.lineWidth = 3
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    line.points.forEach((point: { x: number; y: number }, idx: number) => {
      const p = rosToCell(point.x, point.y)
      if (!p) return
      if (idx === 0) ctx.moveTo(p.x * cs, p.y * cs)
      else ctx.lineTo(p.x * cs, p.y * cs)
    })
    ctx.stroke()
    line.points.forEach((point: { x: number; y: number }) => {
      const p = rosToCell(point.x, point.y)
      if (!p) return
      ctx.beginPath()
      ctx.arc(p.x * cs, p.y * cs, 5, 0, Math.PI * 2)
      ctx.fillStyle = '#67c23a'
      ctx.fill()
      ctx.strokeStyle = '#fff'
      ctx.lineWidth = 2
      ctx.stroke()
    })
  })

  mapStore.drawPoints.forEach((point: { x: number; y: number }) => {
    const p = rosToCell(point.x, point.y)
    if (!p) return
    ctx.beginPath()
    ctx.arc(p.x * cs, p.y * cs, 8, 0, Math.PI * 2)
    ctx.fillStyle = '#f56c6c'
    ctx.fill()
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.stroke()
    ctx.fillStyle = '#fff'
    ctx.font = 'bold 10px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText('×', p.x * cs, p.y * cs)
  })
}

// ===== 动态点云（在静态栅格 + 禁行区之上叠加）=====
function drawPointCloud(ctx: CanvasRenderingContext2D, cs: number) {
  if (mapStore.pointCloudDirty) {
    renderPointCloud(cs)
  }
  if (pointCloudCanvas.width > 0 && mapStore.pointCloudData.length > 0) {
    ctx.drawImage(pointCloudCanvas, 0, 0)
  }
}

// ===== Nav2 全局 / 局部路径 =====
function drawPlans(ctx: CanvasRenderingContext2D, cs: number) {
  const m = getReadyMap()
  if (!m) return

  const drawPlan = (poses: { x: number; y: number }[], color: string, dashed: boolean) => {
    if (!poses || poses.length < 2) return
    ctx.beginPath()
    let started = false
    for (const pose of poses) {
      const p = rosToCell(pose.x, pose.y)
      if (!p) continue
      if (!started) { ctx.moveTo(p.x * cs, p.y * cs); started = true }
      else ctx.lineTo(p.x * cs, p.y * cs)
    }
    if (!started) return
    ctx.strokeStyle = color
    ctx.lineWidth = 2.5
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    if (dashed) ctx.setLineDash([8, 5])
    ctx.stroke()
    ctx.setLineDash([])
  }

  drawPlan(mapStore.globalPlan.poses, 'rgba(103, 194, 58, 0.9)', false)
  const localPlanColor = getComputedStyle(document.documentElement).getPropertyValue('--slider-color').trim() || '#409eff'
  drawPlan(mapStore.localPlan.poses, hexToRgba(localPlanColor, 0.9), false)
}

// ===== 编辑器图层 =====
function drawEditorLayer(ctx: CanvasRenderingContext2D, cs: number) {
  const m = getReadyMap()
  if (!m) return

  // 禁行区 / 虚拟墙（红色半透明）
  const drawWall = (pts: { x: number; y: number }[]) => {
    if (pts.length === 0) return
    ctx.beginPath()
    pts.forEach((pt, idx) => {
      const p = rosToCell(pt.x, pt.y)
      if (!p) return
      if (idx === 0) ctx.moveTo(p.x * cs, p.y * cs)
      else ctx.lineTo(p.x * cs, p.y * cs)
    })
    if (pts.length >= 3) ctx.closePath()
    ctx.fillStyle = 'rgba(245, 108, 108, 0.28)'
    ctx.fill()
    ctx.strokeStyle = '#f56c6c'
    ctx.lineWidth = 2
    ctx.stroke()
  }

  mapStore.walls.forEach((w) => drawWall(w.points))
  if (mapStore.editorMode === 'wall-polygon' && mapStore.tempWallPoints.length) {
    drawWall([...mapStore.tempWallPoints])
  }

  // 轨迹（黄色虚线）
  const drawPath = (pts: { x: number; y: number }[]) => {
    if (pts.length < 2) return
    ctx.beginPath()
    let started = false
    pts.forEach((pt) => {
      const p = rosToCell(pt.x, pt.y)
      if (!p) return
      if (!started) { ctx.moveTo(p.x * cs, p.y * cs); started = true }
      else ctx.lineTo(p.x * cs, p.y * cs)
    })
    if (!started) return
    ctx.strokeStyle = '#e6a23c'
    ctx.lineWidth = 3
    ctx.setLineDash([10, 6])
    ctx.stroke()
    ctx.setLineDash([])
  }

  mapStore.customPaths.forEach((path) => drawPath(path.points))
  if (mapStore.editorMode === 'path' && mapStore.tempPathPoints.length) {
    drawPath(mapStore.tempPathPoints)
  }

  // 临时顶点小圆点
  const drawTempPts = (pts: { x: number; y: number }[]) => {
    pts.forEach((pt) => {
      const p = rosToCell(pt.x, pt.y)
      if (!p) return
      ctx.beginPath()
      ctx.arc(p.x * cs, p.y * cs, 5, 0, Math.PI * 2)
      ctx.fillStyle = '#fff'
      ctx.fill()
      ctx.strokeStyle = '#e6a23c'
      ctx.lineWidth = 2
      ctx.stroke()
    })
  }
  drawTempPts(mapStore.tempWallPoints)
  drawTempPts(mapStore.tempPathPoints)

  // POI（图钉 + 名称）
  mapStore.pois.forEach((poi) => {
    const p = rosToCell(poi.x, poi.y)
    if (!p) return
    const cx = p.x * cs
    const cy = p.y * cs
    ctx.beginPath()
    ctx.arc(cx, cy, 7, 0, Math.PI * 2)
    ctx.fillStyle = '#9b59ff'
    ctx.fill()
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.stroke()
    ctx.fillStyle = '#9b59ff'
    ctx.font = 'bold 12px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'bottom'
    ctx.fillText(poi.name, cx, cy - 10)
  })
}

function drawWaypoints(ctx: CanvasRenderingContext2D, cs: number) {
  const wps = navStore.waypointList
  if (!wps || wps.length === 0) return

  for (const wp of wps) {
    const p = rosToCell(wp.x, wp.y)
    if (!p) continue
    ctx.beginPath()
    ctx.arc(p.x * cs, p.y * cs, 3.5, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(239, 68, 68, 0.5)'
    ctx.fill()
  }

  for (let i = 0; i < wps.length; i++) {
    const wp = wps[i]
    const p = rosToCell(wp.x, wp.y)
    if (!p) continue
    const cx = p.x * cs
    const cy = p.y * cs
    const num = i + 1
    const r = 10

    ctx.beginPath()
    ctx.arc(cx, cy, r, 0, Math.PI * 2)
    ctx.fillStyle = '#EF4444'
    ctx.fill()
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.stroke()

    ctx.fillStyle = '#fff'
    ctx.font = 'bold 11px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(String(num), cx, cy)

    const a = -wp.yaw
    const sx = cx + r * Math.cos(a)
    const sy = cy + r * Math.sin(a)

    ctx.beginPath()
    ctx.moveTo(sx, sy)
    ctx.lineTo(sx + 16 * Math.cos(a), sy + 16 * Math.sin(a))
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.stroke()

    const tipX = sx + 16 * Math.cos(a)
    const tipY = sy + 16 * Math.sin(a)
    const aAng = Math.PI / 6
    const al = 8
    ctx.beginPath()
    ctx.moveTo(tipX, tipY)
    ctx.lineTo(tipX - al * Math.cos(a - aAng), tipY - al * Math.sin(a - aAng))
    ctx.lineTo(tipX - al * Math.cos(a + aAng), tipY - al * Math.sin(a + aAng))
    ctx.closePath()
    ctx.fillStyle = '#fff'
    ctx.fill()
  }
}

function drawEditPreviews(ctx: CanvasRenderingContext2D, cs: number) {
  if (editStartPixel) {
    const color = navStore.isInitialPoseMode ? '#22c55e' : '#EF4444'
    drawPreviewUi(ctx, cs, editStartPixel, editCurrent, color)
  }
}

function drawPreviewUi(
  ctx: CanvasRenderingContext2D,
  cs: number,
  start: { cx: number; cy: number },
  current: { cx: number; cy: number } | null,
  color: string
) {
  // 注意：start / current 已是“逻辑坐标”（screenToPreScale 的结果，
  // 与 rosToCell()*cs 处于同一绘制空间），画布 transform 已包含
  // translate(offset)+scale(zoom)，因此此处**不能再乘 cs**，否则会
  // 出现“第一次点击位置错乱、第二次点击才跳回正确点”的 Bug。
  const sx = start.cx
  const sy = start.cy

  ctx.beginPath()
  ctx.arc(sx, sy, 7, 0, Math.PI * 2)
  ctx.fillStyle = color
  ctx.fill()
  ctx.strokeStyle = '#fff'
  ctx.lineWidth = 2
  ctx.stroke()

  ctx.strokeStyle = 'rgba(255,255,255,0.5)'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(sx - 4, sy)
  ctx.lineTo(sx + 4, sy)
  ctx.moveTo(sx, sy - 4)
  ctx.lineTo(sx, sy + 4)
  ctx.stroke()

  if (current) {
    const cx = current.cx
    const cy = current.cy
    ctx.beginPath()
    ctx.moveTo(sx, sy)
    ctx.lineTo(cx, cy)
    ctx.strokeStyle = color
    ctx.lineWidth = 2
    ctx.setLineDash([6, 4])
    ctx.stroke()
    ctx.setLineDash([])

    const angle = Math.atan2(cy - sy, cx - sx)
    const aLen = 14
    const aAng = Math.PI / 7
    ctx.beginPath()
    ctx.moveTo(cx, cy)
    ctx.lineTo(cx - aLen * Math.cos(angle - aAng), cy - aLen * Math.sin(angle - aAng))
    ctx.lineTo(cx - aLen * Math.cos(angle + aAng), cy - aLen * Math.sin(angle + aAng))
    ctx.closePath()
    ctx.fillStyle = color
    ctx.fill()
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 1
    ctx.stroke()
  }
}

function drawRobot(ctx: CanvasRenderingContext2D, cs: number) {
  const p = rosToCell(robotStore.status.x, robotStore.status.y)
  if (!p) return

  const cx = p.x * cs
  const cy = p.y * cs

  ctx.beginPath()
  ctx.arc(cx, cy, 9, 0, Math.PI * 2)
  ctx.fillStyle = '#00bcd4'
  ctx.fill()
  ctx.strokeStyle = '#fff'
  ctx.lineWidth = 2
  ctx.stroke()

  const drawAngle = -robotStore.status.theta * Math.PI / 180
  const arrowLen = 18
  ctx.beginPath()
  ctx.moveTo(cx, cy)
  ctx.lineTo(cx + arrowLen * Math.cos(drawAngle), cy + arrowLen * Math.sin(drawAngle))
  ctx.strokeStyle = '#fff'
  ctx.lineWidth = 2.5
  ctx.stroke()
}

// ================================================================
// 编辑器工具条交互
// ================================================================
function setMode(mode: EditorMode) {
  mapStore.setEditorMode(mode)
  requestRender()
}

function finishDraft() {
  // 收尾：多边形/轨迹把临时点落定成实体
  if (mapStore.editorMode === 'wall-polygon' && mapStore.tempWallPoints.length >= 3) {
    mapStore.addWall({ id: 'w_' + Date.now(), shape: 'polygon', points: [...mapStore.tempWallPoints] })
    mapStore.tempWallPoints = []
  } else if (mapStore.editorMode === 'wall-polygon') {
    mapStore.tempWallPoints = []
  }
  if (mapStore.editorMode === 'path' && mapStore.tempPathPoints.length >= 2) {
    mapStore.addCustomPath({ id: 'p_' + Date.now(), points: [...mapStore.tempPathPoints] })
    mapStore.tempPathPoints = []
  } else if (mapStore.editorMode === 'path') {
    mapStore.tempPathPoints = []
  }
  requestRender()
}

function clearAll() {
  mapStore.clearEditor()
  requestRender()
}

function uploadEditor() {
  try {
    const payload = mapStore.publishMapEditor()
    ElMessage.success(`已上传：${payload.virtual_walls.length} 禁行区 / ${payload.custom_paths.length} 轨迹 / ${payload.pois.length} POI`)
    navStore.addLog?.('✅ 地图编辑上传 /map_editor/update')
  } catch (e) {
    console.error('[MapCanvas] publishMapEditor error:', e)
    ElMessage.error('上传失败，请确认 ROS Bridge 已连接')
  }
}

// ================================================================
// 指针事件：单画布统一处理（平移 / 编辑 / 放置）—— 全部主线程计算
// ================================================================
function onPointerDown(e: MouseEvent) {
  if (e.button === 2) return
  isPointerDown = true
  movedDuringDrag = false
  lastMouse = { x: e.clientX, y: e.clientY }
  pointerDownPos = { x: e.clientX, y: e.clientY }

  // 地图手绘编辑优先级最高：左键拖拽即在栅格上涂抹（铅笔/橡皮）
  if (e.button === 0 && mapStore.mapEditTool !== 'none' && mapStore.mapBuffer.width > 0) {
    mapStore.beginMapStroke()
    paintAtEvent(e)
    requestRender()
    return
  }

  if (isEditMode()) return

  if (mapStore.editorMode !== 'none') return

  isPanning = true
}

function onPointerMove(e: MouseEvent) {
  const { sx, sy } = getScreenCoords(e)

  // 地图手绘编辑：按住左键拖动连续涂抹
  if (mapStore.mapEditTool !== 'none' && isPointerDown) {
    paintAtEvent(e)
    requestRender()
    return
  }

  if (isPanning) {
    const dx = e.clientX - lastMouse.x
    const dy = e.clientY - lastMouse.y
    if (dx !== 0 || dy !== 0) {
      mapStore.offset.x += dx
      mapStore.offset.y += dy
      movedDuringDrag = true
      lastMouse = { x: e.clientX, y: e.clientY }
      requestRender()
    }
    return
  }

  if (isEditMode() && isPointerDown && editStage === 1) {
    editCurrent = screenToPreScale(sx, sy)
    requestRender()
    return
  }
}

function onPointerUp(e: MouseEvent) {
  const { sx, sy } = getScreenCoords(e)

  // 地图手绘编辑：结束一笔，压入撤销栈
  if (mapStore.mapEditTool !== 'none' && isPointerDown) {
    mapStore.endMapStroke()
    isPointerDown = false
    isPanning = false
    requestRender()
    return
  }

  // 编辑器：单击添加顶点 / POI
  if (mapStore.editorMode !== 'none' && !isEditMode()) {
    const dist = Math.hypot(e.clientX - pointerDownPos.x, e.clientY - pointerDownPos.y)
    if (!movedDuringDrag && dist < 6) {
      handleEditorClick(sx, sy)
    }
    isPointerDown = false
    isPanning = false
    return
  }

  if (isEditMode()) {
    const dist = Math.hypot(e.clientX - pointerDownPos.x, e.clientY - pointerDownPos.y)
    if (!movedDuringDrag && dist < 6) {
      handleEditClick(sx, sy)
    }
  }

  isPointerDown = false
  isPanning = false
}

function onDoubleClick(e: MouseEvent) {
  const { sx, sy } = getScreenCoords(e)
  if (mapStore.editorMode === 'wall-polygon' && mapStore.tempWallPoints.length >= 3) {
    mapStore.addWall({ id: 'w_' + Date.now(), shape: 'polygon', points: [...mapStore.tempWallPoints] })
    mapStore.tempWallPoints = []
    requestRender()
  } else if (mapStore.editorMode === 'path' && mapStore.tempPathPoints.length >= 2) {
    mapStore.addCustomPath({ id: 'p_' + Date.now(), points: [...mapStore.tempPathPoints] })
    mapStore.tempPathPoints = []
    requestRender()
  }
}

function handleEditorClick(sx: number, sy: number) {
  const w = screenToPhysical(sx, sy)
  if (!w) {
    ElMessage.warning('当前地图元数据未就绪，无法定位坐标')
    return
  }
  if (mapStore.editorMode === 'wall-polygon') {
    mapStore.tempWallPoints.push({ x: w.x, y: w.y })
    requestRender()
  } else if (mapStore.editorMode === 'path') {
    mapStore.tempPathPoints.push({ x: w.x, y: w.y })
    requestRender()
  } else if (mapStore.editorMode === 'poi') {
    ElMessageBox.prompt('请输入 POI 名称', '添加 POI', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: 'POI' + (mapStore.pois.length + 1),
    }).then(({ value }) => {
      mapStore.addPoi({ id: 'poi_' + Date.now(), x: w.x, y: w.y, name: value || 'POI' })
      requestRender()
    }).catch(() => {})
  }
}

function onPointerLeave() {
  if (isEditMode() && editStage === 1) {
    editCurrent = null
    requestRender()
  }
  isPointerDown = false
  isPanning = false
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
  const canvas = canvasRef.value!
  const rect = canvas.getBoundingClientRect()
  const mouseX = e.clientX - rect.left
  const mouseY = e.clientY - rect.top

  const delta = e.deltaY > 0 ? -0.1 : 0.1
  const oldZoom = mapStore.zoom
  const newZoom = Math.max(0.5, Math.min(5.0, oldZoom + delta))
  if (newZoom === oldZoom) return

  const worldX = (mouseX - mapStore.offset.x) / oldZoom
  const worldY = (mouseY - mapStore.offset.y) / oldZoom

  mapStore.zoom = newZoom
  mapStore.offset.x = mouseX - worldX * newZoom
  mapStore.offset.y = mouseY - worldY * newZoom

  requestRender()
}

/** 两步法：第 1 次点击=落点位置；第 2 次点击=方向（由位移向量求 yaw） */
function handleEditClick(sx: number, sy: number) {
  const world = screenToPhysical(sx, sy)
  if (!world) {
    ElMessage.warning('当前地图元数据未就绪，无法定位坐标，请稍候或重新连接地图')
    return
  }

  if (editStage === 0) {
    // 航点标定：若第一下点击落在禁行区内，立即拦截并终止本次添加
    if (navStore.currentStatus === 'ADDING' && pointInWall(world.x, world.y)) {
      ElMessage.warning('目标点位于禁行区内，请重新选择！')
      return
    }
    editStage = 1
    editStart = { wx: world.x, wy: world.y }
    editStartPixel = screenToPreScale(sx, sy)
    editCurrent = null
    requestRender()
    return
  }

  const cur = screenToPreScale(sx, sy)
  if (editStartPixel && editStart) {
    const dx = cur.cx - editStartPixel.cx
    const dy = -(cur.cy - editStartPixel.cy)
    const yaw = Math.atan2(dy, dx)
    finalizeEdit(editStart.wx, editStart.wy, yaw)
  }
  editStage = 0
  editStart = null
  editStartPixel = null
  editCurrent = null
  requestRender()
}

function finalizeEdit(x: number, y: number, yaw: number) {
  const q = yawToQuaternion(yaw)

  if (navStore.isInitialPoseMode) {
    publishInitialPose(x, y, q)
    navStore.addLog(`✅ 初始定位已发送 → (${x.toFixed(3)}, ${y.toFixed(3)}), yaw=${yaw.toFixed(3)}`)
    navStore.exitInitialPoseMode()
    return
  }

  if (navStore.currentStatus === 'ADDING') {
    if (pointInWall(x, y)) {
      ElMessage.warning('目标点位于禁行区内，请重新选择！')
      return
    }
    if (!isFreeSpace(x, y)) {
      ElMessage.warning('点击位置超出地图有效边界或位于障碍，请重新选择！')
      return
    }
    navStore.waypointList.push({
      x,
      y,
      yaw,
      qz: q.z,
      qw: q.w,
    })
    navStore.addLog(`✅ 航点 #${navStore.waypointList.length} → (${x.toFixed(3)}, ${y.toFixed(3)}), yaw=${yaw.toFixed(3)}`)
    navStore.updateInspectionUI()
  }
}

// ================================================================
// 初始定位发布（通过 rosbridge 发布到 /initialpose）
// ================================================================
function publishInitialPose(x: number, y: number, orientation: { z: number; w: number }) {
  try {
    const ros = (rosApi as any).ros
    if (!ros) {
      console.error('[MapCanvas] ❌ ROS 实例未初始化 (ros is null)，无法发送初始定位')
      navStore.addLog('❌ ROS 实例未初始化，无法发送初始定位')
      return
    }
    if (!ros.isConnected) {
      console.error('[MapCanvas] ❌ ROS 未连接，无法发送初始定位')
      navStore.addLog('❌ ROS 未连接，无法发送初始定位')
      return
    }
    const topic = new ROSLIB.Topic({
      ros,
      name: '/initialpose',
      messageType: 'geometry_msgs/msg/PoseWithCovarianceStamped',
    })
    const msg = {
      header: { frame_id: 'map', stamp: { sec: 0, nanosec: 0 } },
      pose: {
        pose: {
          position: { x, y, z: 0 },
          orientation: { x: 0, y: 0, z: orientation.z, w: orientation.w },
        },
        covariance: [
          0.25, 0, 0, 0, 0, 0,
          0, 0.25, 0, 0, 0, 0,
          0, 0, 0, 0, 0, 0,
          0, 0, 0, 0, 0, 0,
          0, 0, 0, 0, 0, 0,
          0, 0, 0, 0, 0, 0.06853891945200942,
        ],
      },
    }
    topic.publish(msg)
  } catch (err) {
    console.error('[MapCanvas] publishInitialPose error:', err)
  }
}

// ================================================================
// 视图适配
// ================================================================
function fitMapInView() {
  const container = containerRef.value
  const canvas = canvasRef.value
  if (!container || !canvas) return
  const map = mapStore.currentMap
  if (!map.width || !map.height) return

  const cw = container.clientWidth
  const ch = container.clientHeight
  const padding = 40
  const aw = cw - padding
  const ah = ch - padding

  const cs = Math.min(aw / map.width, ah / map.height, 20)

  cellSize.value = cs
  mapStore.zoom = 1
  mapStore.offset = {
    x: Math.max(0, (cw - map.width * cs) / 2),
    y: Math.max(0, (ch - map.height * cs) / 2),
  }

  mapImageDirty.value = true
}

function handleResize() {
  nextTick(() => requestRender())
}

function resetEditState() {
  editStage = 0
  editStart = null
  editStartPixel = null
  editCurrent = null
}

// ================================================================
// 生命周期 & 监听
// ================================================================
watch(() => mapStore.currentMap, () => {
  mapImageDirty.value = true
  nextTick(() => {
    fitMapInView()
    requestRender()
  })
}, { deep: true })

watch(() => mapStore.mapBufferDirty, (v) => {
  if (v) {
    mapImageDirty.value = true
    requestRender()
  }
})

watch(() => mapStore.pointCloudDirty, (v) => {
  if (v) requestRender()
})

watch(() => mapStore.planDirty, (v) => {
  if (v) { mapStore.planDirty = false; requestRender() }
})

watch(() => mapStore.editorDirty, (v) => {
  if (v) { mapStore.editorDirty = false; requestRender() }
})

watch(() => navStore.waypointList, () => {
  requestRender()
}, { deep: true })

watch(() => [robotStore.status.x, robotStore.status.y, robotStore.status.theta], () => {
  requestRender()
})

watch(() => robotStore.status.connected, (c) => {
  if (c) requestRender()
})

watch(() => navStore.isInitialPoseMode, () => {
  resetEditState()
  requestRender()
})

watch(() => navStore.currentStatus, () => {
  resetEditState()
  requestRender()
})

onMounted(() => {
  const container = containerRef.value
  const canvas = canvasRef.value
  if (canvas && container) {
    canvas.width = container.clientWidth
    canvas.height = container.clientHeight
  }
  fitMapInView()

  nextTick(() => {
    requestRender()
  })

  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<style lang="scss" scoped>
.map-canvas-container {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: $canvas-bg;
  background: linear-gradient(135deg, $canvas-bg-2, $canvas-bg);
}

.map-canvas {
  width: 100%;
  height: 100%;
  cursor: crosshair;
}

.map-overlay {
  position: absolute;
  top: 12px;
  left: 12px;
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: $canvas-text;
  pointer-events: none;
  z-index: 10;
}

  .editor-toolbar {
    position: absolute;
    top: 12px;
    right: 12px;
    width: 224px;
    background: var(--bg-panel);
    border: 1px solid $border-color;
    border-radius: $radius;
    padding: 10px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
    z-index: 30;

    .et-title {
      font-size: 13px;
      font-weight: 700;
      color: $text-primary;
      margin-bottom: 8px;
    }

    .et-group {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 8px;
    }

    .et-actions {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
      margin-bottom: 6px;
    }

    .et-btn {
      width: 100%;
      min-width: 0;
      padding: 6px 2px;
      font-size: 11px;
      line-height: 1.25;
      white-space: normal;
      border: 1px solid $border-color;
      border-radius: $radius;
      background: var(--bg-card);
      color: $text-secondary;
      cursor: pointer;
      transition: all $transition;

    &:hover {
      border-color: $theme-primary;
      color: $theme-primary;
    }

    &.active {
      background: $theme-primary;
      border-color: $theme-primary;
      color: #fff;
    }
  }

  .et-finish { border-color: #67c23a; color: #67c23a;
    &:hover { background: #67c23a; color: #fff; border-color: #67c23a; } }
  .et-clear { border-color: #f56c6c; color: #f56c6c;
    &:hover { background: #f56c6c; color: #fff; border-color: #f56c6c; } }
  .et-upload { border-color: $theme-primary; color: $theme-primary;
    &:hover { background: $theme-primary; color: #fff; } }

  .et-hint {
    font-size: 11px;
    color: $text-muted;
    line-height: 1.4;
  }
}

.disconnected-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-canvas);
  box-shadow: inset 0 0 80px rgba(0, 0, 0, 0.4);
  z-index: 20;
}

.disconnected-content {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 0 24px;
  text-align: center;

  .radar-bg {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 260px;
    height: 260px;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    border: 1px solid rgba(255, 255, 255, 0.06);
    background:
      radial-gradient(circle, rgba(255, 255, 255, 0.03) 0%, transparent 60%);
    pointer-events: none;
    z-index: 0;
  }

  .tech-icon {
    position: relative;
    z-index: 1;
    font-size: 48px;
    color: rgba(255, 255, 255, 0.15);
    margin-bottom: 4px;
  }

  .status-text {
    position: relative;
    z-index: 1;
    font-size: 13px;
    color: #707070;
    letter-spacing: 2px;
    font-weight: 400;
  }

  .status-sub {
    position: relative;
    z-index: 1;
    font-size: 12px;
    color: #555;
    letter-spacing: 1px;
    font-weight: 300;
  }
}
</style>
