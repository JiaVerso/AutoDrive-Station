import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { MapInfo, ActiveTool, DrawMode, DrawPoint, DrawLine } from '@/types'
import { mockMap, generateMockOccupiedGrid } from '@/mock/data'
import { parsePointCloud2, projectTo2D, parsePointCloud2ToFloat32Array, parseLivoxCustomMsg, type PointCloudData } from '@/utils/pointCloudParser'

export const useMapStore = defineStore('map', () => {
  const currentMap = ref<MapInfo>({
    ...mockMap,
    occupied: generateMockOccupiedGrid(mockMap.width, mockMap.height),
    data: [],
  })
  const activeTool = ref<ActiveTool>('map')
  const mapping = ref(false)
  const localizationReady = ref(false)
  const zoom = ref(1)
  const offset = ref({ x: 0, y: 0 })
  const savedMaps = ref(['factory_floor_01', 'warehouse_02', 'parking_03'])
  const mapSource = ref<'local' | 'ros'>('local')
  const cellSize = 3

  const drawMode = ref<DrawMode>('none')
  const drawPoints = ref<DrawPoint[]>([])
  const drawLines = ref<DrawLine[]>([])
  const tempLinePoints = ref<{ x: number; y: number }[]>([])
  const mapDirty = ref(true)
  const pointCloudData = ref<{ x: number; y: number; z: number; intensity?: number }[]>([])
  const pointCloudDirty = ref(false)
  const pointCloud3DData = ref<Float32Array | null>(null)

  function startMapping() {
    mapping.value = true
  }

  function stopMapping() {
    mapping.value = false
    drawMode.value = 'none'
    tempLinePoints.value = []
  }

  function setDrawMode(mode: DrawMode) {
    drawMode.value = mode
    if (mode !== 'line') {
      tempLinePoints.value = []
    }
  }

  function addDrawPoint(x: number, y: number) {
    const point: DrawPoint = {
      id: 'dp' + Date.now(),
      x,
      y,
    }
    drawPoints.value.push(point)
    return point
  }

  function deleteDrawPoint(id: string) {
    drawPoints.value = drawPoints.value.filter((p) => p.id !== id)
  }

  function clearDrawPoints() {
    drawPoints.value = []
  }

  function addLinePoint(x: number, y: number) {
    tempLinePoints.value.push({ x, y })
  }

  function finishDrawLine() {
    if (tempLinePoints.value.length >= 2) {
      const line: DrawLine = {
        id: 'dl' + Date.now(),
        points: [...tempLinePoints.value],
      }
      drawLines.value.push(line)
    }
    tempLinePoints.value = []
  }

  function cancelDrawLine() {
    tempLinePoints.value = []
  }

  function deleteDrawLine(id: string) {
    drawLines.value = drawLines.value.filter((l) => l.id !== id)
  }

  function clearDrawLines() {
    drawLines.value = []
    tempLinePoints.value = []
  }

  function clearAllDrawings() {
    drawPoints.value = []
    drawLines.value = []
    tempLinePoints.value = []
  }

  function saveMap(name: string) {
    savedMaps.value.push(name)
  }

  function deleteMap(name: string) {
    savedMaps.value = savedMaps.value.filter((m) => m !== name)
  }

  function loadMap(name: string) {
    currentMap.value.name = name
    currentMap.value.occupied = generateMockOccupiedGrid(currentMap.value.width, currentMap.value.height)
  }

  function localize() {
    localizationReady.value = true
  }

  function updateMapFromRos(message: any) {
    if (!message) return

    console.log('[Map] Received raw message:', JSON.stringify({ 
      hasInfo: !!message.info, 
      hasData: !!message.data,
      infoKeys: message.info ? Object.keys(message.info) : [],
      dataType: typeof message.data,
      dataLength: Array.isArray(message.data) ? message.data.length : (typeof message.data === 'string' ? message.data.length : 'N/A')
    }))

    const info = message.info || message
    const data = message.data
    
    if (!data) return

    const width = info.width || 500
    const height = info.height || 500
    const resolution = info.resolution || 0.1
    
    let originX = 0
    let originY = 0
    let theta = 0
    
    if (info.origin) {
      if (info.origin.position) {
        originX = info.origin.position.x || 0
        originY = info.origin.position.y || 0
      } else if (typeof info.origin.x === 'number') {
        originX = info.origin.x
        originY = info.origin.y || 0
      }
      if (info.origin.orientation) {
        theta = info.origin.orientation.z ? Math.asin(info.origin.orientation.z) * 2 : 0
      }
    }

    let decodedData: number[] = []
    if (typeof data === 'string') {
      try {
        const binaryStr = atob(data)
        decodedData = Array.from(binaryStr).map(c => c.charCodeAt(0))
      } catch {
        console.error('[Map] Failed to decode base64 map data')
        return
      }
    } else if (Array.isArray(data)) {
      decodedData = data
    } else {
      console.error('[Map] Unsupported map data format')
      return
    }

    console.log('[Map] Decoded data length:', decodedData.length, 'expected:', width * height)

    const occupied: boolean[][] = []
    const mapData: number[][] = []
    for (let y = 0; y < height; y++) {
      const occupiedRow: boolean[] = []
      const dataRow: number[] = []
      for (let x = 0; x < width; x++) {
        const index = y * width + x
        const value = decodedData[index] ?? -1
        occupiedRow.push(value >= 50)
        dataRow.push(value)
      }
      occupied.push(occupiedRow)
      mapData.push(dataRow)
    }

    currentMap.value = {
      name: 'ros_map',
      width,
      height,
      resolution,
      origin: {
        x: originX,
        y: originY,
        theta,
      },
      occupied,
      data: mapData,
    }

    console.log('[Map] Updated from ROS:', width, 'x', height, 'resolution:', resolution, 'origin:', originX, originY)
    mapSource.value = 'ros'
    mapDirty.value = true
  }

  let lastPointCloudUpdate = 0
  function updatePointCloudFromRos(message: any) {
    const now = Date.now()
    if (now - lastPointCloudUpdate < 100) return
    lastPointCloudUpdate = now
    
    console.log('[Map] updatePointCloudFromRos called, message type:', typeof message, 'has data:', !!message?.data)
    
    const parsed = parsePointCloud2(message)
    
    console.log('[Map] Parsed points length:', parsed.points.length)
    
    if (parsed.points.length > 0) {
      const max3DPoints = 8000
      const step = Math.ceil(parsed.points.length / max3DPoints)
      
      console.log('[Map] 3D step:', step, 'max3DPoints:', max3DPoints)
      
      const projected = projectTo2D(parsed.points, currentMap.value.origin, currentMap.value.resolution)
      const max2DPoints = 5000
      const step2D = Math.ceil(projected.length / max2DPoints)
      const sampled2D = projected.filter((_, i) => i % step2D === 0)
      pointCloudData.value = sampled2D
      pointCloudDirty.value = true

      const pos = new Float32Array(Math.min(max3DPoints, parsed.points.length) * 3)
      let valid = 0
      let minY = Infinity
      
      for (let i = 0; i < parsed.points.length; i += step) {
        const p = parsed.points[i]
        if (!isFinite(p.x) || !isFinite(p.y) || !isFinite(p.z)) continue
        
        const yVal = p.z
        if (yVal < minY) minY = yVal
        
        pos[valid * 3] = p.x
        pos[valid * 3 + 1] = yVal
        pos[valid * 3 + 2] = -p.y
        valid++
        
        if (valid >= max3DPoints) break
      }
      
      console.log('[Map] 3D valid points after loop:', valid)
      
      if (valid > 0) {
        const offset = -minY + 0.0
        for (let i = 0; i < valid; i++) {
          pos[i * 3 + 1] += offset
        }
        const result = pos.slice(0, valid * 3)
        pointCloud3DData.value = result
        console.log('[Map] 3D Point cloud updated, length:', result.length, 'points:', result.length / 3)
      } else {
        console.warn('[Map] No valid 3D points after filtering')
      }
    } else {
      console.warn('[Map] Parsed points is empty')
    }
  }

  let lastLivoxUpdate = 0
  function updateLivoxPointCloud(message: any) {
    const now = Date.now()
    if (now - lastLivoxUpdate < 100) return
    lastLivoxUpdate = now

    console.log('[Map] updateLivoxPointCloud called')

    const parsed = parseLivoxCustomMsg(message)
    console.log('[Map] Livox parsed points:', parsed.points.length)

    if (parsed.points.length > 0) {
      const max3DPoints = 8000
      const step = Math.ceil(parsed.points.length / max3DPoints)

      const projected = projectTo2D(parsed.points, currentMap.value.origin, currentMap.value.resolution)
      const max2DPoints = 5000
      const step2D = Math.ceil(projected.length / max2DPoints)
      const sampled2D = projected.filter((_, i) => i % step2D === 0)
      pointCloudData.value = sampled2D
      pointCloudDirty.value = true

      const pos = new Float32Array(Math.min(max3DPoints, parsed.points.length) * 3)
      let valid = 0
      let minY = Infinity

      for (let i = 0; i < parsed.points.length; i += step) {
        const p = parsed.points[i]
        if (!isFinite(p.x) || !isFinite(p.y) || !isFinite(p.z)) continue

        const yVal = p.z
        if (yVal < minY) minY = yVal

        pos[valid * 3] = p.x
        pos[valid * 3 + 1] = yVal
        pos[valid * 3 + 2] = -p.y
        valid++

        if (valid >= max3DPoints) break
      }

      if (valid > 0) {
        const offset = -minY + 0.0
        for (let i = 0; i < valid; i++) {
          pos[i * 3 + 1] += offset
        }
        const result = pos.slice(0, valid * 3)
        pointCloud3DData.value = result
        console.log('[Map] Livox 3D Point cloud updated, length:', result.length, 'points:', result.length / 3)
      }
    }
  }

  function clearPointCloud() {
    pointCloudData.value = []
    pointCloudDirty.value = true
    pointCloud3DData.value = null
  }

  function isPointInMap(x: number, y: number): boolean {
    const map = currentMap.value
    const maxX = map.origin.x + map.width * map.resolution
    const maxY = map.origin.y + map.height * map.resolution
    return x >= map.origin.x && x <= maxX && y >= map.origin.y && y <= maxY
  }

  function getMapBounds() {
    const map = currentMap.value
    const maxX = map.origin.x + map.width * map.resolution
    const maxY = map.origin.y + map.height * map.resolution
    return {
      minX: map.origin.x,
      maxX,
      minY: map.origin.y,
      maxY,
    }
  }

  function centerMap(canvasWidth: number, canvasHeight: number) {
    const map = currentMap.value
    if (!map.width || !map.height) return

    const cellSize = Math.min(canvasWidth / map.width, canvasHeight / map.height, 20)
    zoom.value = 1

    const mapPixelWidth = map.width * cellSize
    const mapPixelHeight = map.height * cellSize

    offset.value = {
      x: Math.max(0, (canvasWidth - mapPixelWidth) / 2),
      y: Math.max(0, (canvasHeight - mapPixelHeight) / 2),
    }
  }

  return {
    currentMap,
    activeTool,
    mapping,
    localizationReady,
    zoom,
    offset,
    savedMaps,
    mapSource,
    drawMode,
    drawPoints,
    drawLines,
    tempLinePoints,
    pointCloudData,
    pointCloudDirty,
    pointCloud3DData,
    startMapping,
    stopMapping,
    setDrawMode,
    addDrawPoint,
    deleteDrawPoint,
    clearDrawPoints,
    addLinePoint,
    finishDrawLine,
    cancelDrawLine,
    deleteDrawLine,
    clearDrawLines,
    clearAllDrawings,
    updateMapFromRos,
    updatePointCloudFromRos,
    updateLivoxPointCloud,
    clearPointCloud,
    isPointInMap,
    getMapBounds,
    centerMap,
    saveMap,
    deleteMap,
    loadMap,
    localize,
  }
})
