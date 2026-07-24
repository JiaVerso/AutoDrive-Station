<template>
  <!--
    ==========================================
     无人车智能跟随系统 — 摄像头图传弹窗
    ==========================================
    大疆焦点跟随风格交互：
      1. 透明 Canvas 覆盖在视频流上方，支持鼠标框选 ROI 目标区域
      2. 订阅 /yolo_detections 话题，在 Canvas 上绘制绿色锁定标记
      3. 底部控制栏：目标扫描开关、三挡跟随模式、锁定状态
  -->
  <Teleport to="body">
    <Transition name="popup-fade">
      <div
        v-if="followActive"
        ref="panelRef"
        class="follow-panel"
        :style="panelStyle"
      >
        <!-- ===== 标题栏（拖拽手柄） ===== -->
        <div class="panel-header" v-drag="onDragStart">
          <div class="header-left">
            <span class="header-dot" :class="{ live: streamOk }" />
            <span class="header-title">智能跟随</span>
            <span class="header-topic" v-if="isLocked">
              <span class="lock-badge">已锁定</span>
            </span>
            <span class="header-topic" v-else-if="scanEnabled">
              扫描中
            </span>
          </div>
          <button class="close-btn" @click="handleClose" title="停止跟随">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
            </svg>
          </button>
        </div>

        <!-- ===== 视频流 + Canvas 交互层 ===== -->
        <div
          ref="wrapperRef"
          class="stream-wrapper"
          @mousedown="onCanvasMouseDown"
          @mousemove="onCanvasMouseMove"
          @mouseup="onCanvasMouseUp"
        >
          <!-- 底层：MJPEG 视频流 -->
          <img
            v-if="streamUrl"
            ref="imgRef"
            :src="streamUrl"
            alt="Robot Camera Stream"
            class="stream-img"
            @load="onStreamLoad"
            @error="streamOk = false"
            draggable="false"
          />
          <div v-else class="stream-placeholder">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
              <rect x="2" y="4" width="20" height="16" rx="2"/>
              <circle cx="12" cy="12" r="4"/>
            </svg>
            <span>视频流不可用</span>
          </div>

          <!-- 顶层：透明 Canvas（ROI 框选 + YOLO 标记渲染） -->
          <canvas
            ref="canvasRef"
            class="stream-canvas"
            :width="canvasWidth"
            :height="canvasHeight"
          />

          <!-- 框选提示浮层（仅在无目标时显示） -->
          <div
            v-if="streamOk && !isLocked && !roiBox"
            class="canvas-hint"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <rect x="3" y="3" width="18" height="18" rx="2" stroke-dasharray="4 2"/>
              <line x1="12" y1="8" x2="12" y2="16"/>
              <line x1="8" y1="12" x2="16" y2="12"/>
            </svg>
            <span>拖拽框选目标区域</span>
          </div>
        </div>

        <!-- ===== 底部控制栏 ===== -->
        <div class="action-bar">
          <!-- 目标扫描开关 -->
          <div class="action-group">
            <button
              class="action-btn scan-btn"
              :class="{ active: scanEnabled }"
              @click="toggleScan"
              :title="scanEnabled ? '关闭目标扫描' : '开启目标扫描'"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="2" x2="12" y2="6"/>
                <line x1="12" y1="18" x2="12" y2="22"/>
                <line x1="2" y1="12" x2="6" y2="12"/>
                <line x1="18" y1="12" x2="22" y2="12"/>
              </svg>
              <span>扫描</span>
            </button>
          </div>

          <!-- 三挡跟随模式切换 -->
          <div class="action-group mode-group">
            <button
              v-for="m in modeOptions"
              :key="m.value"
              class="action-btn mode-btn"
              :class="{ active: followMode === m.value }"
              @click="setFollowMode(m.value)"
              :title="m.label"
            >
              <component :is="m.icon" />
              <span>{{ m.shortLabel }}</span>
            </button>
          </div>

          <!-- 锁定状态 / 操作 -->
          <div class="action-group">
            <button
              v-if="isLocked"
              class="action-btn unlock-btn"
              @click="unlockTarget"
              title="解除锁定"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="3" y="11" width="18" height="11" rx="2"/>
                <path d="M7 11V7a5 5 0 0110 0"/>
              </svg>
              <span>解锁</span>
            </button>
            <span v-else-if="detections.length > 0" class="detection-count">
              {{ detections.length }} 个目标
            </span>
          </div>

          <!-- 停止跟随 -->
          <button class="action-btn stop-btn" @click="handleClose">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
              <rect x="1" y="1" width="10" height="10" rx="1.5"/>
            </svg>
            <span>停止</span>
          </button>
        </div>

        <!-- ===== 状态栏 ===== -->
        <div class="panel-footer">
          <span class="footer-status" :class="{ ok: streamOk }">
            {{ streamOk ? '图传正常' : '连接中...' }}
          </span>
          <span class="footer-mode" v-if="isLocked">
            {{ followModeLabel }}
          </span>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount, onMounted, h, type Directive, type CSSProperties, type VNode } from 'vue'
import { useFollowMode } from '@/composables/useFollowMode'
import { useRobotStore } from '@/stores/robot'
import type { DetectionTarget, FollowModeType } from '@/types'

const robotStore = useRobotStore()
const {
  followActive, stopFollow,
  streamNaturalWidth, streamNaturalHeight,
  scanEnabled, detections,
  isLocked, lockedTargetId, lockedTarget,
  followMode, followModeLabel,
  roiBox,
  enableScan, sendRoi, lockTarget, unlockTarget, setFollowMode: setMode, updateStreamSize,
} = useFollowMode()

// ================================================================
//  面板拖拽状态
// ================================================================
const posX = ref<number | null>(null)
const posY = ref<number | null>(null)
const panelRef = ref<HTMLDivElement>()
const hasInitPos = ref(false)

watch(followActive, (v) => {
  if (v && !hasInitPos.value) {
    requestAnimationFrame(() => {
      const el = panelRef.value
      if (el) {
        posX.value = window.innerWidth - el.offsetWidth - 20
        posY.value = 68
        hasInitPos.value = true
      }
    })
  }
})

const panelStyle = computed<CSSProperties>(() => {
  const s: CSSProperties = { position: 'fixed', zIndex: 9999 }
  if (posX.value !== null) s.left = `${posX.value}px`
  if (posY.value !== null) s.top = `${posY.value}px`
  return s
})

// ================================================================
//  视频流
// ================================================================
const imgRef = ref<HTMLImageElement>()
const wrapperRef = ref<HTMLDivElement>()
const canvasRef = ref<HTMLCanvasElement>()
const streamOk = ref(false)

const streamUrl = computed(() => {
  if (!robotStore.status.connected) return ''
  const ip = robotStore.ip || '192.168.1.100'
  return `http://${ip}:8080/stream?topic=/camera/image_raw`
})

/** 视频流加载完成：获取图片原始尺寸，初始化 Canvas */
function onStreamLoad() {
  const img = imgRef.value
  if (!img) return
  streamOk.value = true
  updateStreamSize(img.naturalWidth, img.naturalHeight)
}

// ================================================================
//  Canvas 尺寸 & 坐标转换
// ================================================================
const canvasWidth = ref(0)
const canvasHeight = ref(0)

/**
 * ResizeObserver 监听 wrapper 尺寸变化，同步更新 Canvas 尺寸
 */
let resizeObs: ResizeObserver | null = null
onMounted(() => {
  if (wrapperRef.value) {
    resizeObs = new ResizeObserver(() => updateCanvasSize())
    resizeObs.observe(wrapperRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObs?.disconnect()
})

function updateCanvasSize() {
  const wrapper = wrapperRef.value
  if (!wrapper) return
  const rect = wrapper.getBoundingClientRect()
  canvasWidth.value = Math.round(rect.width)
  canvasHeight.value = Math.round(rect.height)
  drawCanvas()
}

/**
 * 计算视频流在 Canvas 中的实际绘制区域（object-fit: contain 适配）
 * 返回 { left, top, w, h } —— 均为 Canvas 像素坐标
 */
function getDisplayRect() {
  const cw = canvasWidth.value
  const ch = canvasHeight.value
  const nw = streamNaturalWidth.value
  const nh = streamNaturalHeight.value
  if (!nw || !nh || !cw || !ch) {
    return { left: 0, top: 0, w: cw, h: ch }
  }
  const canvasRatio = cw / ch
  const imgRatio = nw / nh
  let w: number, h: number, left: number, top: number
  if (imgRatio > canvasRatio) {
    // 图片更宽 → 左右留黑边
    w = cw
    h = cw / imgRatio
    left = 0
    top = (ch - h) / 2
  } else {
    // 图片更高 → 上下留黑边
    h = ch
    w = ch * imgRatio
    left = (cw - w) / 2
    top = 0
  }
  return { left, top, w, h }
}

/**
 * 将 Canvas 像素坐标转换为原始图片的归一化坐标 (0~1)
 */
function canvasToImage(cx: number, cy: number) {
  const { left, top, w, h } = getDisplayRect()
  return {
    nx: Math.max(0, Math.min(1, (cx - left) / w)),
    ny: Math.max(0, Math.min(1, (cy - top) / h)),
  }
}

/**
 * 将原始图片归一化坐标转换为 Canvas 像素坐标
 */
function imageToCanvas(nx: number, ny: number) {
  const { left, top, w, h } = getDisplayRect()
  return { cx: left + nx * w, cy: top + ny * h }
}

// ================================================================
//  Canvas 绘制
// ================================================================
let animFrameId = 0

/** 触发重绘（节流：下一帧） */
function requestDraw() {
  if (animFrameId) return
  animFrameId = requestAnimationFrame(() => {
    animFrameId = 0
    drawCanvas()
  })
}

/** 主绘制函数：清除 → 绘制 ROI 框选区 → 绘制 YOLO 检测标记 */
function drawCanvas() {
  const cvs = canvasRef.value
  if (!cvs) return
  const ctx = cvs.getContext('2d')
  if (!ctx) return

  const cw = canvasWidth.value
  const ch = canvasHeight.value
  ctx.clearRect(0, 0, cw, ch)

  // 绘制 ROI 框选区域（手动框选 或 已锁定的 ROI）
  if (roiBox.value) {
    drawRoiBox(ctx, roiBox.value)
  }

  // 绘制 YOLO 自动检测标记（扫描模式开启时）
  if (scanEnabled.value && detections.value.length > 0) {
    drawYoloMarkers(ctx)
  }
}

/** 绘制 ROI 半透明框选区域 + 大疆风格角标 */
function drawRoiBox(ctx: CanvasRenderingContext2D, roi: { xMin: number; yMin: number; xMax: number; yMax: number }) {
  const { left, top, w, h } = getDisplayRect()
  const nw = streamNaturalWidth.value || w
  const nh = streamNaturalHeight.value || h

  // 将 ROI 像素坐标转为 Canvas 坐标
  const rx1 = left + (roi.xMin / nw) * w
  const ry1 = top + (roi.yMin / nh) * h
  const rx2 = left + (roi.xMax / nw) * w
  const ry2 = top + (roi.yMax / nh) * h
  const rw = rx2 - rx1
  const rh = ry2 - ry1

  // 半透明遮罩（框选区域外部变暗）
  ctx.fillStyle = 'rgba(0, 0, 0, 0.35)'
  ctx.fillRect(left, top, w, ry1 - top)
  ctx.fillRect(left, ry1, rx1 - left, rh)
  ctx.fillRect(rx2, ry1, left + w - rx2, rh)
  ctx.fillRect(left, ry2, w, top + h - ry2)

  // 框选区域边框（大疆绿 + 虚线）
  ctx.strokeStyle = 'rgba(82, 196, 26, 0.9)'
  ctx.lineWidth = 1.5
  ctx.setLineDash([6, 3])
  ctx.strokeRect(rx1, ry1, rw, rh)
  ctx.setLineDash([])

  // 四角角标（粗短线）
  const cornerLen = Math.min(16, rw / 4, rh / 4)
  ctx.strokeStyle = '#52c41a'
  ctx.lineWidth = 2.5
  // 左上
  ctx.beginPath(); ctx.moveTo(rx1, ry1 + cornerLen); ctx.lineTo(rx1, ry1); ctx.lineTo(rx1 + cornerLen, ry1); ctx.stroke()
  // 右上
  ctx.beginPath(); ctx.moveTo(rx2 - cornerLen, ry1); ctx.lineTo(rx2, ry1); ctx.lineTo(rx2, ry1 + cornerLen); ctx.stroke()
  // 左下
  ctx.beginPath(); ctx.moveTo(rx1, ry2 - cornerLen); ctx.lineTo(rx1, ry2); ctx.lineTo(rx1 + cornerLen, ry2); ctx.stroke()
  // 右下
  ctx.beginPath(); ctx.moveTo(rx2 - cornerLen, ry2); ctx.lineTo(rx2, ry2); ctx.lineTo(rx2, ry2 - cornerLen); ctx.stroke()

  // ROI 中心十字标记
  const rcx = (rx1 + rx2) / 2
  const rcy = (ry1 + ry2) / 2
  ctx.strokeStyle = 'rgba(82, 196, 26, 0.6)'
  ctx.lineWidth = 1
  ctx.beginPath(); ctx.moveTo(rcx - 6, rcy); ctx.lineTo(rcx + 6, rcy); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(rcx, rcy - 6); ctx.lineTo(rcx, rcy + 6); ctx.stroke()
}

/** 绘制 YOLO 检测标记（大疆绿色 "+" + 脉冲环 + 标签） */
function drawYoloMarkers(ctx: CanvasRenderingContext2D) {
  const nw = streamNaturalWidth.value || canvasWidth.value
  const nh = streamNaturalHeight.value || canvasHeight.value
  const time = Date.now()

  for (const det of detections.value) {
    // 归一化中心坐标 → Canvas 像素坐标
    const { cx: mCx, cy: mCy } = imageToCanvas(det.cx / nw, det.cy / nh)
    // 跳过超出画面的标记
    if (mCx < -20 || mCx > canvasWidth.value + 20 || mCy < -20 || mCy > canvasHeight.value + 20) continue

    const isThisLocked = lockedTargetId.value === det.id

    // 脉冲环动画
    const pulse = ((time % 2000) / 2000) // 0→1 循环
    const pulseR = 10 + pulse * 12
    const pulseAlpha = 0.5 * (1 - pulse)

    ctx.strokeStyle = isThisLocked
      ? `rgba(82, 196, 26, ${pulseAlpha})`
      : `rgba(82, 196, 26, ${pulseAlpha * 0.7})`
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.arc(mCx, mCy, pulseR, 0, Math.PI * 2)
    ctx.stroke()

    // 中心 "+" 标记（大疆锁定风格）
    const crossSize = isThisLocked ? 8 : 6
    ctx.strokeStyle = isThisLocked ? '#52c41a' : 'rgba(82, 196, 26, 0.85)'
    ctx.lineWidth = isThisLocked ? 2.5 : 2
    ctx.beginPath(); ctx.moveTo(mCx - crossSize, mCy); ctx.lineTo(mCx + crossSize, mCy); ctx.stroke()
    ctx.beginPath(); ctx.moveTo(mCx, mCy - crossSize); ctx.lineTo(mCx, mCy + crossSize); ctx.stroke()

    // 外框：显示检测边界框
    const { cx: bx1, cy: by1 } = imageToCanvas(det.bbox.x_min / nw, det.bbox.y_min / nh)
    const { cx: bx2, cy: by2 } = imageToCanvas(det.bbox.x_max / nw, det.bbox.y_max / nh)
    ctx.strokeStyle = isThisLocked ? '#52c41a' : 'rgba(82, 196, 26, 0.4)'
    ctx.lineWidth = isThisLocked ? 2 : 1
    ctx.setLineDash(isThisLocked ? [] : [4, 2])
    ctx.strokeRect(bx1, by1, bx2 - bx1, by2 - by1)
    ctx.setLineDash([])

    // 标签背景 + 文字
    const label = `${det.className} ${Math.round(det.confidence * 100)}%`
    ctx.font = '600 10px Inter, system-ui, sans-serif'
    const textW = ctx.measureText(label).width
    const labelX = bx1
    const labelY = by1 - 20 > 0 ? by1 - 20 : by2 + 4

    // 标签底色
    ctx.fillStyle = isThisLocked ? 'rgba(82, 196, 26, 0.9)' : 'rgba(0, 0, 0, 0.65)'
    const pad = 4
    ctx.beginPath()
    ctx.roundRect(labelX - pad, labelY - 10 - pad, textW + pad * 2, 14 + pad * 2, 3)
    ctx.fill()

    // 标签文字
    ctx.fillStyle = isThisLocked ? '#000' : '#fff'
    ctx.fillText(label, labelX, labelY)
  }

  // 持续动画：只要扫描开启就不断请求下一帧
  if (scanEnabled.value && detections.value.length > 0) {
    requestAnimationFrame(drawCanvas)
  }
}

// ================================================================
//  Canvas 鼠标交互 — ROI 框选
// ================================================================
const isDrawing = ref(false)
const drawStart = ref<{ x: number; y: number } | null>(null)
const drawCurrent = ref<{ x: number; y: number } | null>(null)

function getCanvasCoords(e: MouseEvent): { x: number; y: number } {
  const cvs = canvasRef.value
  if (!cvs) return { x: 0, y: 0 }
  const rect = cvs.getBoundingClientRect()
  return { x: e.clientX - rect.left, y: e.clientY - rect.top }
}

/** 查找点击了哪个 YOLO 标记 */
function findClickedDetection(cx: number, cy: number): DetectionTarget | null {
  if (!scanEnabled.value) return null
  const nw = streamNaturalWidth.value || canvasWidth.value
  const nh = streamNaturalHeight.value || canvasHeight.value
  const hitRadius = 24 // 像素判定半径

  for (const det of detections.value) {
    const { cx: mCx, cy: mCy } = imageToCanvas(det.cx / nw, det.cy / nh)
    const dist = Math.hypot(cx - mCx, cy - mCy)
    if (dist < hitRadius) return det
  }
  return null
}

function onCanvasMouseDown(e: MouseEvent) {
  if (e.button !== 0) return
  const { x, y } = getCanvasCoords(e)

  // 优先检测是否点击了 YOLO 标记（锁定目标）
  const clickedDet = findClickedDetection(x, y)
  if (clickedDet) {
    lockTarget(clickedDet)
    return
  }

  // 检查是否在图片有效区域内才开始框选
  const { left, top, w, h } = getDisplayRect()
  if (x < left || x > left + w || y < top || y > top + h) return

  // 开始 ROI 框选
  isDrawing.value = true
  drawStart.value = { x, y }
  drawCurrent.value = { x, y }
}

function onCanvasMouseMove(e: MouseEvent) {
  if (!isDrawing.value || !drawStart.value) return
  const { x, y } = getCanvasCoords(e)
  drawCurrent.value = { x, y }

  // 实时绘制框选预览
  drawCanvas()
  const ctx = canvasRef.value?.getContext('2d')
  if (!ctx) return

  const sx = drawStart.value.x
  const sy = drawStart.value.y
  const ex = Math.max(canvasWidth.value * 0, Math.min(x, canvasWidth.value))
  const ey = Math.max(0, Math.min(y, canvasHeight.value))
  const rx = Math.min(sx, ex)
  const ry = Math.min(sy, ey)
  const rw = Math.abs(ex - sx)
  const rh = Math.abs(ey - sy)

  // 半透明遮罩
  ctx.fillStyle = 'rgba(82, 196, 26, 0.08)'
  ctx.fillRect(rx, ry, rw, rh)
  // 虚线边框
  ctx.strokeStyle = 'rgba(82, 196, 26, 0.7)'
  ctx.lineWidth = 1.5
  ctx.setLineDash([5, 3])
  ctx.strokeRect(rx, ry, rw, rh)
  ctx.setLineDash([])
  // 尺寸标注
  ctx.fillStyle = 'rgba(82, 196, 26, 0.8)'
  ctx.font = '600 10px monospace'
  ctx.fillText(`${Math.round(rw)}×${Math.round(rh)}`, rx + 4, ry - 4 > 10 ? ry - 4 : ry + 14)
}

function onCanvasMouseUp(e: MouseEvent) {
  if (!isDrawing.value || !drawStart.value) return
  isDrawing.value = false

  const { x, y } = getCanvasCoords(e)
  const sx = drawStart.value.x
  const sy = drawStart.value.y
  drawStart.value = null
  drawCurrent.value = null

  // 过滤过小的框选（可能是误触）
  const minSize = 12
  if (Math.abs(x - sx) < minSize || Math.abs(y - sy) < minSize) {
    drawCanvas()
    return
  }

  // 将 Canvas 坐标转为原始图片像素坐标
  const nw = streamNaturalWidth.value || canvasWidth.value
  const nh = streamNaturalHeight.value || canvasHeight.value
  const { nx: nxMin, ny: nyMin } = canvasToImage(Math.min(sx, x), Math.min(sy, y))
  const { nx: nxMax, ny: nyMax } = canvasToImage(Math.max(sx, x), Math.max(sy, y))

  sendRoi({
    xMin: nxMin * nw,
    yMin: nyMin * nh,
    xMax: nxMax * nw,
    yMax: nyMax * nh,
  })

  drawCanvas()
}

// ================================================================
//  交互操作
// ================================================================
function toggleScan() {
  enableScan(!scanEnabled.value)
}

function setFollowMode(mode: FollowModeType) {
  setMode(mode)
}

function handleClose() {
  stopFollow()
}

// ================================================================
//  监听状态变化，触发 Canvas 重绘
// ================================================================
watch([scanEnabled, detections, roiBox, lockedTargetId], () => {
  requestDraw()
}, { deep: true })

// ================================================================
//  拖拽指令
// ================================================================
function onDragStart(e: MouseEvent, el: HTMLElement) {
  const panel = el.closest('.follow-panel') as HTMLElement
  if (!panel) return
  const panelRect = panel.getBoundingClientRect()
  const offsetX = e.clientX - panelRect.left
  const offsetY = e.clientY - panelRect.top

  panel.style.right = 'auto'
  panel.style.left = `${panelRect.left}px`
  panel.style.top = `${panelRect.top}px`
  posX.value = panelRect.left
  posY.value = panelRect.top

  let rafId = 0
  let pendingX = 0
  let pendingY = 0

  function onMouseMove(ev: MouseEvent) {
    pendingX = ev.clientX - offsetX
    pendingY = ev.clientY - offsetY
    if (!rafId) {
      rafId = requestAnimationFrame(() => {
        rafId = 0
        const maxX = window.innerWidth - panel.offsetWidth
        const maxY = window.innerHeight - panel.offsetHeight
        posX.value = Math.max(0, Math.min(pendingX, maxX))
        posY.value = Math.max(0, Math.min(pendingY, maxY))
      })
    }
  }

  function onMouseUp() {
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0 }
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
  }

  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'grabbing'
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
}

const vDrag: Directive<HTMLElement, (e: MouseEvent, el: HTMLElement) => void> = {
  mounted(el, binding) {
    el.style.cursor = 'grab'
    el.addEventListener('mousedown', (e: MouseEvent) => {
      if (e.button !== 0) return
      e.preventDefault()
      binding.value(e, el)
    })
  },
}

// ================================================================
//  跟随模式选项（三挡按钮）
// ================================================================
/** 使用渲染函数创建内联 SVG 图标 VNode */
function createSvgIcon(pathD: string): () => VNode {
  return () => h('svg', { width: 13, height: 13, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8 }, [
    h('path', { d: pathD }),
  ])
}

const modeOptions: { value: FollowModeType; label: string; shortLabel: string; icon: () => VNode }[] = [
  {
    value: 'parallel',
    label: '平行跟随模式',
    shortLabel: '平行',
    // 两条平行线图标
    icon: createSvgIcon('M4 4v16M20 4v16'),
  },
  {
    value: 'trace',
    label: '尾随追踪模式',
    shortLabel: '尾随',
    // 箭头跟随图标
    icon: createSvgIcon('M5 12h14M13 5l7 7-7 7'),
  },
  {
    value: 'orbit',
    label: '环绕/定点监视模式',
    shortLabel: '环绕',
    // 环形图标
    icon: createSvgIcon('M12 2a10 10 0 100 20 10 10 0 000-20z'),
  },
]

// ================================================================
//  组件卸载清理
// ================================================================
onBeforeUnmount(() => {
  if (animFrameId) cancelAnimationFrame(animFrameId)
  resizeObs?.disconnect()
})
</script>

<style lang="scss" scoped>
/* ===== 面板主体 ===== */
.follow-panel {
  width: 420px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  overflow: hidden;
  user-select: none;
}

/* ===== 标题栏（拖拽手柄） ===== */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 12px;
  background: var(--bg-card-2);
  border-bottom: 1px solid var(--border-color);
  cursor: grab;

  &:active { cursor: grabbing; }
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.header-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #666;
  flex-shrink: 0;
  transition: background 0.3s;

  &.live {
    background: var(--accent-green);
    box-shadow: 0 0 6px var(--accent-green);
  }
}

.header-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.header-topic {
  font-size: 10px;
  color: var(--text-muted);
  font-family: monospace;
  opacity: 0.7;
}

.lock-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 7px;
  background: rgba(82, 196, 26, 0.15);
  color: var(--accent-green);
  border: 1px solid rgba(82, 196, 26, 0.3);
  border-radius: 10px;
  font-size: 10px;
  font-weight: 600;
  font-family: inherit;
  opacity: 1;
}

.close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;

  &:hover {
    background: rgba(255, 255, 255, 0.08);
    color: var(--accent-red);
  }
}

/* ===== 视频流区域 ===== */
.stream-wrapper {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #0a0a0a;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.stream-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
  pointer-events: none;
}

/* Canvas 覆盖层：透明，接收所有鼠标事件 */
.stream-canvas {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  cursor: crosshair;
  z-index: 2;
}

.stream-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: #555;
  font-size: 12px;
  z-index: 1;

  svg { opacity: 0.3; }
}

/* 框选提示浮层 */
.canvas-hint {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  border: 1px solid rgba(82, 196, 26, 0.25);
  border-radius: 14px;
  color: rgba(255, 255, 255, 0.8);
  font-size: 11px;
  pointer-events: none;
  z-index: 3;
  animation: hintPulse 3s ease-in-out infinite;

  svg { opacity: 0.7; }
}

@keyframes hintPulse {
  0%, 100% { opacity: 0.7; }
  50% { opacity: 1; }
}

/* ===== 底部控制栏（Action Bar） ===== */
.action-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--bg-card-2);
  border-top: 1px solid var(--border-color);
  border-bottom: 1px solid var(--border-color);
}

.action-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.mode-group {
  flex: 1;
  justify-content: center;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--border-color);
  border-radius: 5px;
  background: transparent;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;

  svg { flex-shrink: 0; }

  &:hover {
    border-color: var(--text-secondary);
    color: var(--text-secondary);
  }

  &.active {
    background: rgba(82, 196, 26, 0.12);
    border-color: var(--accent-green);
    color: var(--accent-green);
  }
}

.scan-btn.active {
  background: rgba(82, 196, 26, 0.12);
  border-color: var(--accent-green);
  color: var(--accent-green);
}

.mode-btn.active {
  background: rgba(24, 144, 255, 0.1);
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}

html.dark .mode-btn.active {
  background: rgba(211, 47, 47, 0.1);
  border-color: var(--theme-primary);
  color: var(--theme-primary);
}

.unlock-btn {
  border-color: rgba(82, 196, 26, 0.4);
  color: var(--accent-green);

  &:hover {
    background: rgba(82, 196, 26, 0.08);
    border-color: var(--accent-green);
  }
}

.detection-count {
  font-size: 11px;
  color: var(--text-muted);
  padding: 0 4px;
}

.stop-btn {
  border-color: rgba(245, 34, 45, 0.3);
  color: var(--accent-red);

  &:hover {
    background: rgba(245, 34, 45, 0.08);
    border-color: var(--accent-red);
  }
}

/* ===== 底部状态栏 ===== */
.panel-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 12px;
}

.footer-status {
  font-size: 11px;
  color: var(--text-muted);

  &.ok {
    color: var(--accent-green);
  }
}

.footer-mode {
  font-size: 10px;
  color: var(--accent-blue);
  font-weight: 500;
}

html.dark .footer-mode {
  color: var(--theme-primary);
}

/* ===== 进入/离开动画 ===== */
.popup-fade-enter-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.popup-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.popup-fade-enter-from {
  opacity: 0;
  transform: translateY(-8px);
}
.popup-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
