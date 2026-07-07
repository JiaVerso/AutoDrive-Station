<template>
  <main class="map-canvas-container" ref="containerRef">
    <canvas
      ref="canvasRef"
      class="map-canvas"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @mouseleave="onMouseUp"
      @wheel="onWheel"
      @click="onCanvasClick"
    />
    <div class="map-overlay">
      <span class="map-name">{{ mapStore.currentMap.name }}</span>
      <span class="zoom-level">100%</span>
    </div>
    <div class="robot-marker" v-if="robotStore.status.connected" :style="robotStyle">
      <div class="robot-icon">
        <svg viewBox="0 0 24 24" width="20" height="20">
          <polygon points="12,2 4,22 12,18 20,22" fill="#409eff" stroke="#fff" stroke-width="1"/>
        </svg>
      </div>
      <div class="robot-label">{{ robotStore.status.speed.toFixed(1) }}m/s</div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useMapStore } from '@/stores/map'
import { useRobotStore } from '@/stores/robot'
import { useNavigationStore } from '@/stores/navigation'
import { generateMockOccupiedGrid } from '@/mock/data'
import { physicalToMapPixel, screenToPhysical } from '@/utils/coordinateConverter'

const mapStore = useMapStore()
const robotStore = useRobotStore()
const navStore = useNavigationStore()

const containerRef = ref<HTMLDivElement>()
const canvasRef = ref<HTMLCanvasElement>()
const offscreenCanvas = document.createElement('canvas')
const offscreenCtx = offscreenCanvas.getContext('2d')
const pointCloudCanvas = document.createElement('canvas')
const pointCloudCtx = pointCloudCanvas.getContext('2d')
const isDragging = ref(false)
const lastMouse = ref({ x: 0, y: 0 })
const mapDirty = ref(true)

const robotStyle = computed(() => {
  const canvas = canvasRef.value
  const container = containerRef.value
  const cellSize = canvas && container ? getDynamicCellSize(canvas.width, canvas.height) : 20
  
  const { x: mapX, y: mapY } = physicalToMapPixel(robotStore.status.x, robotStore.status.y, mapStore.currentMap)
  const x = mapStore.offset.x + mapX * cellSize * mapStore.zoom
  const y = mapStore.offset.y + mapY * cellSize * mapStore.zoom
  
  return {
    transform: `translate(${x}px, ${y}px) rotate(${robotStore.status.theta}deg)`,
  }
})

function getDynamicCellSize(canvasWidth: number, canvasHeight: number): number {
  const map = mapStore.currentMap
  if (!map.width || !map.height) return 3
  return Math.min(canvasWidth / map.width, canvasHeight / map.height, 20)
}

function renderStaticMap(canvasWidth: number, canvasHeight: number) {
  if (!offscreenCtx) return
  const map = mapStore.currentMap
  
  const cellSize = getDynamicCellSize(canvasWidth, canvasHeight)
  
  offscreenCanvas.width = map.width * cellSize
  offscreenCanvas.height = map.height * cellSize
  
  offscreenCtx.fillStyle = '#f5f7fa'
  offscreenCtx.fillRect(0, 0, offscreenCanvas.width, offscreenCanvas.height)
  
  offscreenCtx.strokeStyle = '#e4e7ed'
  offscreenCtx.lineWidth = 0.5
  const gridSize = Math.max(cellSize * 10, 50)
  const gridCountX = Math.ceil(offscreenCanvas.width / gridSize)
  const gridCountY = Math.ceil(offscreenCanvas.height / gridSize)
  for (let x = 0; x <= gridCountX; x++) {
    offscreenCtx.beginPath()
    offscreenCtx.moveTo(x * gridSize, 0)
    offscreenCtx.lineTo(x * gridSize, offscreenCanvas.height)
    offscreenCtx.stroke()
  }
  for (let y = 0; y <= gridCountY; y++) {
    offscreenCtx.beginPath()
    offscreenCtx.moveTo(0, y * gridSize)
    offscreenCtx.lineTo(offscreenCanvas.width, y * gridSize)
    offscreenCtx.stroke()
  }
  
  if (map.data.length > 0) {
    for (let y = 0; y < map.height; y++) {
      for (let x = 0; x < map.width; x++) {
        const value = map.data[y]?.[x] ?? -1
        let color: string
        
        if (value === -1) {
          continue
        } else if (value === 0) {
          color = '#e8f5e9'
        } else if (value >= 50) {
          color = '#424242'
        } else {
          const gray = Math.floor(220 - (value / 50) * 150)
          color = `rgb(${gray}, ${gray}, ${gray})`
        }
        
        offscreenCtx.fillStyle = color
        offscreenCtx.fillRect(x * cellSize, y * cellSize, cellSize, cellSize)
      }
    }
  } else if (map.occupied.length > 0) {
    offscreenCtx.fillStyle = '#c0c4cc'
    for (let y = 0; y < map.occupied.length; y++) {
      for (let x = 0; x < map.occupied[y].length; x++) {
        if (map.occupied[y][x]) {
          offscreenCtx.fillRect(x * cellSize, y * cellSize, cellSize, cellSize)
        }
      }
    }
  }
  
  mapDirty.value = false
}

function renderPointCloud(canvasWidth: number, canvasHeight: number) {
  if (!pointCloudCtx) return
  const map = mapStore.currentMap
  const points = mapStore.pointCloudData
  
  const cellSize = getDynamicCellSize(canvasWidth, canvasHeight)
  
  pointCloudCanvas.width = map.width * cellSize
  pointCloudCanvas.height = map.height * cellSize
  
  pointCloudCtx.clearRect(0, 0, pointCloudCanvas.width, pointCloudCanvas.height)
  
  if (points.length === 0) return
  
  const pixelSize = Math.max(cellSize * 0.5, 2)
  
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  points.forEach((point) => {
    if (point.x < minX) minX = point.x
    if (point.x > maxX) maxX = point.x
    if (point.y < minY) minY = point.y
    if (point.y > maxY) maxY = point.y
  })
  
  const pointCloudWidth = maxX - minX || 1
  const pointCloudHeight = maxY - minY || 1
  
  const mapCenterX = map.width / 2
  const mapCenterY = map.height / 2
  const pointCloudCenterX = (minX + maxX) / 2
  const pointCloudCenterY = (minY + maxY) / 2
  
  const offsetX = mapCenterX - pointCloudCenterX
  const offsetY = mapCenterY - pointCloudCenterY
  
  points.forEach((point) => {
    const px = (point.x + offsetX) * cellSize
    const py = (point.y + offsetY) * cellSize
    
    if (px < -100 || px > pointCloudCanvas.width + 100 || py < -100 || py > pointCloudCanvas.height + 100) {
      return
    }
    
    let intensity = point.intensity || 0
    if (intensity > 255) intensity = 255
    if (intensity < 0) intensity = 0
    
    const normalizedIntensity = intensity / 255
    const blue = Math.floor(64 + normalizedIntensity * 191)
    const green = Math.floor(150 + (1 - normalizedIntensity) * 105)
    const alpha = 0.6 + normalizedIntensity * 0.4
    
    pointCloudCtx.beginPath()
    pointCloudCtx.fillStyle = `rgba(${green}, ${blue}, 255, ${alpha})`
    pointCloudCtx.arc(px, py, pixelSize / 2, 0, Math.PI * 2)
    pointCloudCtx.fill()
  })
  
  mapStore.pointCloudDirty = false
}

function drawMap() {
  const canvas = canvasRef.value
  const container = containerRef.value
  if (!canvas || !container) return

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const prevWidth = canvas.width
  const prevHeight = canvas.height
  
  if (canvas.width !== container.clientWidth || canvas.height !== container.clientHeight) {
    canvas.width = container.clientWidth
    canvas.height = container.clientHeight
    
    if (prevWidth > 0 && prevHeight > 0) {
      const scaleX = canvas.width / prevWidth
      const scaleY = canvas.height / prevHeight
      mapStore.offset.x *= scaleX
      mapStore.offset.y *= scaleY
    }
  }

  const cellSize = getDynamicCellSize(canvas.width, canvas.height)

  ctx.fillStyle = '#f5f7fa'
  ctx.fillRect(0, 0, canvas.width, canvas.height)

  ctx.save()
  ctx.translate(mapStore.offset.x, mapStore.offset.y)
  ctx.scale(mapStore.zoom, mapStore.zoom)

  if (mapDirty.value) {
    renderStaticMap(canvas.width, canvas.height)
  }
  
  if (offscreenCanvas.width > 0) {
    ctx.drawImage(offscreenCanvas, 0, 0)
  }

  if (mapStore.pointCloudDirty) {
    renderPointCloud(canvas.width, canvas.height)
  }
  
  if (pointCloudCanvas.width > 0 && mapStore.pointCloudData.length > 0) {
    ctx.drawImage(pointCloudCanvas, 0, 0)
  }

  navStore.waypoints.forEach((wp, idx) => {
    const { x: wx, y: wy } = physicalToMapPixel(wp.x, wp.y, mapStore.currentMap)

    ctx.beginPath()
    ctx.arc(wx * cellSize, wy * cellSize, 8, 0, Math.PI * 2)
    ctx.fillStyle = '#409eff'
    ctx.fill()
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.stroke()

    ctx.fillStyle = '#fff'
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(String(idx + 1), wx * cellSize, wy * cellSize)

    ctx.fillStyle = '#4a4a4a'
    ctx.font = '11px sans-serif'
    ctx.fillText(wp.name, wx * cellSize, wy * cellSize + 18)
  })

  if (navStore.waypoints.length > 1) {
    ctx.beginPath()
    ctx.strokeStyle = 'rgba(64, 158, 255, 0.5)'
    ctx.lineWidth = 2
    ctx.setLineDash([6, 4])
    navStore.waypoints.forEach((wp, idx) => {
      const { x: wx, y: wy } = physicalToMapPixel(wp.x, wp.y, mapStore.currentMap)
      if (idx === 0) ctx.moveTo(wx * cellSize, wy * cellSize)
      else ctx.lineTo(wx * cellSize, wy * cellSize)
    })
    ctx.stroke()
    ctx.setLineDash([])
  }

  mapStore.drawLines.forEach((line) => {
    if (line.points.length < 2) return
    ctx.beginPath()
    ctx.strokeStyle = '#67c23a'
    ctx.lineWidth = 3
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    line.points.forEach((point, idx) => {
      const { x: px, y: py } = physicalToMapPixel(point.x, point.y, mapStore.currentMap)
      if (idx === 0) ctx.moveTo(px * cellSize, py * cellSize)
      else ctx.lineTo(px * cellSize, py * cellSize)
    })
    ctx.stroke()

    line.points.forEach((point) => {
      const { x: px, y: py } = physicalToMapPixel(point.x, point.y, mapStore.currentMap)
      ctx.beginPath()
      ctx.arc(px * cellSize, py * cellSize, 5, 0, Math.PI * 2)
      ctx.fillStyle = '#67c23a'
      ctx.fill()
      ctx.strokeStyle = '#fff'
      ctx.lineWidth = 2
      ctx.stroke()
    })
  })

  if (mapStore.tempLinePoints.length > 0) {
    ctx.beginPath()
    ctx.strokeStyle = 'rgba(103, 194, 58, 0.6)'
    ctx.lineWidth = 3
    ctx.setLineDash([8, 4])
    mapStore.tempLinePoints.forEach((point, idx) => {
      const { x: px, y: py } = physicalToMapPixel(point.x, point.y, mapStore.currentMap)
      if (idx === 0) ctx.moveTo(px * cellSize, py * cellSize)
      else ctx.lineTo(px * cellSize, py * cellSize)
    })
    ctx.stroke()
    ctx.setLineDash([])

    mapStore.tempLinePoints.forEach((point) => {
      const { x: px, y: py } = physicalToMapPixel(point.x, point.y, mapStore.currentMap)
      ctx.beginPath()
      ctx.arc(px * cellSize, py * cellSize, 6, 0, Math.PI * 2)
      ctx.fillStyle = '#67c23a'
      ctx.fill()
      ctx.strokeStyle = '#fff'
      ctx.lineWidth = 2
      ctx.stroke()
    })
  }

  mapStore.drawPoints.forEach((point) => {
    const { x: px, y: py } = physicalToMapPixel(point.x, point.y, mapStore.currentMap)
    ctx.beginPath()
    ctx.arc(px * cellSize, py * cellSize, 8, 0, Math.PI * 2)
    ctx.fillStyle = '#f56c6c'
    ctx.fill()
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.stroke()
    ctx.fillStyle = '#fff'
    ctx.font = 'bold 10px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText('×', px * cellSize, py * cellSize)
  })

  if (robotStore.status.connected) {
    const { x: rx, y: ry } = physicalToMapPixel(robotStore.status.x, robotStore.status.y, mapStore.currentMap)
    ctx.strokeStyle = 'rgba(0, 160, 212, 0.2)'
    ctx.lineWidth = 1
    for (let i = 0; i < 36; i++) {
      const angle = (i * 10 * Math.PI) / 180
      const dist = 40 + Math.random() * 60
      ctx.beginPath()
      ctx.moveTo(rx, ry)
      ctx.lineTo(rx + Math.cos(angle) * dist, ry + Math.sin(angle) * dist)
      ctx.stroke()
    }
  }

  ctx.restore()
}

function getMapCoordinates(e: MouseEvent): { x: number; y: number } {
  const canvas = canvasRef.value
  const container = containerRef.value
  if (!canvas || !container) return { x: 0, y: 0 }
  const rect = canvas.getBoundingClientRect()
  const cellSize = getDynamicCellSize(canvas.width, canvas.height)
  
  const screenX = e.clientX - rect.left
  const screenY = e.clientY - rect.top
  
  const { x, y } = screenToPhysical(
    screenX, 
    screenY, 
    mapStore.currentMap, 
    cellSize, 
    mapStore.offset.x, 
    mapStore.offset.y, 
    mapStore.zoom
  )
  
  return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 }
}

function onMouseDown(e: MouseEvent) {
  if (mapStore.drawMode !== 'none') return
  isDragging.value = true
  lastMouse.value = { x: e.clientX, y: e.clientY }
}

function onMouseMove(e: MouseEvent) {
  if (!isDragging.value) return
  const dx = e.clientX - lastMouse.value.x
  const dy = e.clientY - lastMouse.value.y
  mapStore.offset.x += dx
  mapStore.offset.y += dy
  lastMouse.value = { x: e.clientX, y: e.clientY }
}

function onMouseUp() {
  isDragging.value = false
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
}

function onCanvasClick(e: MouseEvent) {
  const { x, y } = getMapCoordinates(e)
  
  if (mapStore.drawMode === 'point') {
    if (isPointInCanvas(e)) {
      navStore.addWaypoint({ x, y, name: `航点${navStore.waypoints.length + 1}` })
    } else {
      showMapBoundaryWarning()
    }
  } else if (mapStore.drawMode === 'line') {
    if (isPointInCanvas(e)) {
      mapStore.addLinePoint(x, y)
    } else {
      showMapBoundaryWarning()
    }
  }
}

function isPointInCanvas(e: MouseEvent): boolean {
  const canvas = canvasRef.value
  if (!canvas) return false
  const rect = canvas.getBoundingClientRect()
  const x = e.clientX - rect.left
  const y = e.clientY - rect.top
  const map = mapStore.currentMap
  const cellSize = getDynamicCellSize(canvas.width, canvas.height)
  
  const mapLeft = mapStore.offset.x
  const mapRight = mapStore.offset.x + map.width * cellSize * mapStore.zoom
  const mapTop = mapStore.offset.y
  const mapBottom = mapStore.offset.y + map.height * cellSize * mapStore.zoom
  
  return x >= mapLeft && x <= mapRight && y >= mapTop && y <= mapBottom
}

function showMapBoundaryWarning() {
  ElMessage.warning('超出地图边界！请在地图范围内绘制')
}

function onCanvasDoubleClick() {
  if (mapStore.drawMode === 'line') {
    if (mapStore.tempLinePoints.length >= 2) {
      mapStore.tempLinePoints.forEach((point) => {
        navStore.addWaypoint({ x: point.x, y: point.y, name: `航点${navStore.waypoints.length + 1}` })
      })
      ElMessage.success(`已添加 ${mapStore.tempLinePoints.length} 个航点`)
    }
    mapStore.finishDrawLine()
  }
}

let animFrame: number
function animate() {
  drawMap()
  animFrame = requestAnimationFrame(animate)
}

watch(() => mapStore.activeTool, () => {
  if (mapStore.activeTool === 'mapping') {
    mapStore.startMapping()
  }
})

function handleResize() {
  drawMap()
  const container = containerRef.value
  if (container) {
    mapStore.centerMap(container.clientWidth, container.clientHeight)
  }
}

watch(() => mapStore.currentMap, () => {
  mapDirty.value = true
  setTimeout(() => {
    const container = containerRef.value
    if (container) {
      mapStore.centerMap(container.clientWidth, container.clientHeight)
    }
  }, 100)
}, { deep: true })

watch(() => mapStore.pointCloudData.length, () => {
  if (mapStore.pointCloudData.length > 0) {
    mapStore.pointCloudDirty = true
  }
})

onMounted(() => {
  const container = containerRef.value
  const canvas = canvasRef.value
  if (canvas && container) {
    canvas.width = container.clientWidth
    canvas.height = container.clientHeight
    renderStaticMap(canvas.width, canvas.height)
  }
  animate()
  window.addEventListener('resize', handleResize)
  canvasRef.value?.addEventListener('dblclick', onCanvasDoubleClick)
  
  setTimeout(() => {
    const container = containerRef.value
    if (container) {
      mapStore.centerMap(container.clientWidth, container.clientHeight)
    }
  }, 100)
})

onUnmounted(() => {
  cancelAnimationFrame(animFrame)
  window.removeEventListener('resize', handleResize)
  canvasRef.value?.removeEventListener('dblclick', onCanvasDoubleClick)
})
</script>

<style lang="scss" scoped>
.map-canvas-container {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: $bg-primary;
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
  color: $text-muted;
  pointer-events: none;
}

.robot-marker {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  transition: transform 100ms linear;
}

.robot-label {
  font-size: 10px;
  color: $accent-blue;
  margin-top: 2px;
}
</style>
