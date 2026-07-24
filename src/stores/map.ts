import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { MapInfo, MapBuffer, ActiveTool, DrawMode, DrawPoint, DrawLine, EditorMode, Wall, CustomPath, Poi, PlanPath, MapEditorPayload } from '@/types'
import { rosApi } from '@/api/ros'
import { mockMap, generateMockOccupiedGrid } from '@/mock/data'
import { parsePointCloud2, projectTo2D, parsePointCloud2ToFloat32Array, parseLivoxCustomMsg, type PointCloudData, type Point3D } from '@/utils/pointCloudParser'
import { useRobotStore } from '@/stores/robot'

export const useMapStore = defineStore('map', () => {
  const currentMap = ref<MapInfo>({
    ...mockMap,
    occupied: generateMockOccupiedGrid(mockMap.width, mockMap.height),
    data: [],
  })
  const activeTool = ref<ActiveTool>('map')
  // “地图”一级菜单下的二级子页面：编辑地图 / 地图信息 / 连接状态
  const currentMapTab = ref<'edit' | 'info' | 'connection'>('edit')
  // “建图”一级菜单下的二级子页面：地图设置 / 地图管理 / 实时控制
  const currentMappingTab = ref<'settings' | 'manage' | 'control'>('settings')
  const mapping = ref(false)
  const localizationReady = ref(false)
  const zoom = ref(1)
  const offset = ref({ x: 0, y: 0 })
  // 不再写死默认地图列表：真实地图列表应由后端返回（小车本地
  // .yaml/.pgm 历史地图 + 当前实时 /map），通过 API 填充此数组。
  const savedMaps = ref<string[]>([])
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

  // ===== 多图层：Nav2 全局 / 局部路径（ROS 米坐标）=====
  const globalPlan = ref<PlanPath>({ poses: [] })
  const localPlan = ref<PlanPath>({ poses: [] })
  const planDirty = ref(false)

  function setGlobalPlan(msg: any) {
    globalPlan.value = parsePlan(msg)
    planDirty.value = true
  }
  function setLocalPlan(msg: any) {
    localPlan.value = parsePlan(msg)
    planDirty.value = true
  }
  function parsePlan(msg: any): PlanPath {
    try {
      const poses = (msg?.poses || []) as any[]
      return {
        poses: poses.map((p) => {
          const pos = p?.pose?.position || p?.position || { x: 0, y: 0 }
          const o = p?.pose?.orientation || p?.orientation || { z: 0 }
          const theta = Math.atan2(2 * (o.w || 1) * (o.z || 0), 1 - 2 * ((o.z || 0) * (o.z || 0)))
          return { x: pos.x, y: pos.y, theta: theta * 180 / Math.PI }
        }),
      }
    } catch {
      return { poses: [] }
    }
  }

  // ===== 地图编辑器：禁行区 / 虚拟墙 / 轨迹 / POI =====
  const editorMode = ref<EditorMode>('none')
  const walls = ref<Wall[]>([])
  const customPaths = ref<CustomPath[]>([])
  const pois = ref<Poi[]>([])
  const tempWallPoints = ref<{ x: number; y: number }[]>([])
  const tempPathPoints = ref<{ x: number; y: number }[]>([])
  const editorDirty = ref(false)

  function setEditorMode(mode: EditorMode) {
    editorMode.value = mode
    tempWallPoints.value = []
    tempPathPoints.value = []
  }

  function addWall(wall: Wall) {
    walls.value.push(wall)
    editorDirty.value = true
  }
  function addCustomPath(path: CustomPath) {
    customPaths.value.push(path)
    editorDirty.value = true
  }
  function addPoi(poi: Poi) {
    pois.value.push(poi)
    editorDirty.value = true
  }
  function clearEditor() {
    walls.value = []
    customPaths.value = []
    pois.value = []
    tempWallPoints.value = []
    tempPathPoints.value = []
    editorMode.value = 'none'
    editorDirty.value = true
  }

  function exportEditorJson(): MapEditorPayload {
    return {
      virtual_walls: walls.value.map((w) => ({ ...w, points: [...w.points] })),
      custom_paths: customPaths.value.map((p) => ({ ...p, points: [...p.points] })),
      pois: pois.value.map((p) => ({ ...p })),
    }
  }

  function publishMapEditor() {
    const payload = exportEditorJson()
    rosApi.publishTopic('/map_editor/update', 'std_msgs/msg/String', {
      data: JSON.stringify(payload),
    })
    return payload
  }

  const mapBuffer = ref<MapBuffer>({
    data: new Uint8Array(0),
    width: 0,
    height: 0,
    resolution: 0.05,
    originX: 0,
    originY: 0,
  })
  const mapBufferDirty = ref(false)

  // ===== 地图手绘编辑（画笔/橡皮擦 修补 OccupancyGrid）=====
  // mapEditTool: 'none' | 'pencil'(墙壁/障碍=100) | 'eraser'(擦除噪点/空闲=0)
  const mapEditTool = ref<'none' | 'pencil' | 'eraser'>('none')
  // 笔刷直径（单位：栅格像素），1 / 3 / 5
  const brushSize = ref<number>(3)
  // 撤销栈：每一笔记录被修改像素的「索引 + 旧值」
  const undoStack = ref<{ i: number; v: number }[][]>([])
  let currentStroke: { i: number; v: number }[] = []

  const mapEditActive = computed(() => mapEditTool.value !== 'none')
  const canUndoMap = computed(() => undoStack.value.length > 0)

  // 状态锁：正在手绘编辑地图时，拦截 ROS /map 话题的自动重绘，防止覆盖画板。
  const isEditingMap = ref(false)
  // 短暂的重载窗口锁：保存成功后等待小车 map_server 重新加载新地图期间，
  // 也拦截旧地图的回灌，避免保存瞬间被旧帧覆盖。保存成功后由调用方释放。
  const mapReloading = ref(false)

  function setMapEditTool(t: 'none' | 'pencil' | 'eraser') {
    mapEditTool.value = t
    // 状态锁：选了画笔/橡皮擦 -> 锁住话题重绘；切回 none -> 释放锁
    isEditingMap.value = t !== 'none'
    // 关闭编辑时丢弃未提交的一笔
    if (t === 'none') currentStroke = []
  }

  function beginMapStroke() {
    currentStroke = []
  }

  // 直接修改底层栅格数组：铅笔写 100（障碍），橡皮写 0（空闲）。
  // 重复值不写、同一笔内每索引只记录一次旧值，便于精确撤销。
  function paintCell(i: number, value: number) {
    const buf = mapBuffer.value
    if (i < 0 || i >= buf.data.length) return
    const old = buf.data[i]
    if (old === value) return
    if (!currentStroke.some((s) => s.i === i)) currentStroke.push({ i, v: old })
    buf.data[i] = value
    mapBufferDirty.value = true
    mapDirty.value = true
  }

  function endMapStroke() {
    if (currentStroke.length) undoStack.value.push(currentStroke)
    currentStroke = []
  }

  function undoMapEdit() {
    const stroke = undoStack.value.pop()
    if (!stroke) return
    const buf = mapBuffer.value
    for (const s of stroke) {
      if (s.i >= 0 && s.i < buf.data.length) buf.data[s.i] = s.v
    }
    mapBufferDirty.value = true
    mapDirty.value = true
  }

  // 动态解析地图修补服务的基础地址：
  //   1) 显式传入的 baseUrl
  //   2) 环境变量 VITE_MAP_EDIT_API
  //   3) 当前已连接的小车 IP（robotStore.ip，即用户在连接面板填写的真实地址，如 192.168.110.161）
  //   4) 浏览器地址栏 hostname（若直接通过该 IP 访问前端页面）
  // 绝不回退到 localhost，避免跨设备（前端不在小车上）时请求发错主机。
  function resolveMapApiBase(override?: string): string {
    if (override) return override.replace(/\/+$/, '')
    const env = import.meta.env.VITE_MAP_EDIT_API as string | undefined
    if (env) return env.replace(/\/+$/, '')

    const robotIp = useRobotStore().ip?.trim()
    if (robotIp && robotIp !== 'localhost' && robotIp !== '127.0.0.1') {
      return `http://${robotIp}:5000`
    }
    const host = window.location.hostname
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      return `http://${host}:5000`
    }
    // 兜底：保留端口 5000，但明确指向本机（仅在确实在本机小车浏览器操作时生效）
    return 'http://localhost:5000'
  }

  // 将修补后的栅格数组 + 元数据发送给后端，由后端重写 /maps/main.pgm(.yaml)
  async function saveEditedMap(baseUrl?: string) {
    const buf = mapBuffer.value
    if (!buf.width || !buf.height) throw new Error('地图数据为空，无法保存')
    const apiBase = resolveMapApiBase(baseUrl)
    const payload = {
      width: buf.width,
      height: buf.height,
      resolution: buf.resolution,
      origin: { x: buf.originX, y: buf.originY },
      data: Array.from(buf.data),
    }
    const resp = await fetch(`${apiBase}/api/map/save_edited`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!resp.ok) throw new Error(`保存修补地图失败: HTTP ${resp.status}`)

    // 保存成功后，后端会触发 map_server 重载新地图。开启短暂重载锁，
    // 拦截重载完成前可能回灌的旧 /map 帧，避免画板被旧图覆盖。
    // 释放时机：由调用方在确认收到新地图（或超时）后调用 finishMapReload()。
    mapReloading.value = true
    isEditingMap.value = false
    return await resp.json().catch(() => ({}))
  }

  // 保存成功后由调用方在收到小车重载后的新地图（或超时兜底）时调用，释放重载锁。
  function finishMapReload() {
    mapReloading.value = false
  }

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

  // 激活“地图”一级页面并切换到指定二级子页面
  function setMapTab(tab: 'edit' | 'info' | 'connection') {
    activeTool.value = 'map'
    currentMapTab.value = tab
  }

  // 激活“建图”一级页面并切换到指定二级子页面
  function setMappingTab(tab: 'settings' | 'manage' | 'control') {
    activeTool.value = 'mapping'
    currentMappingTab.value = tab
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
    } else if (Array.isArray(data) || ArrayBuffer.isView(data)) {
      // roslibjs 可能以普通 number[] 或 Int8Array/Uint8Array 形式回传 OccupancyGrid.data
      decodedData = Array.from(data as ArrayLike<number>)
    } else {
      console.error('[Map] Unsupported map data format:', typeof data)
      return
    }

    console.log('[Map] Decoded data length:', decodedData.length, 'expected:', width * height)

    const occupied: boolean[][] = []
    const mapData: number[][] = []
    const totalPixels = width * height

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

    const buf = new Uint8Array(totalPixels)
    for (let i = 0; i < totalPixels; i++) {
      buf[i] = (decodedData[i] ?? -1) & 0xFF
    }
    mapBuffer.value = {
      data: buf,
      width,
      height,
      resolution,
      originX,
      originY,
    }
    mapBufferDirty.value = true

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

  // ===== 激光雷达 LaserScan → 2D 点云（按机器人位姿投影到地图坐标系）=====
  let lastScanUpdate = 0
  function updateScanFromRos(message: any) {
    const now = Date.now()
    if (now - lastScanUpdate < 100) return
    lastScanUpdate = now

    if (!message || !Array.isArray(message.ranges)) {
      console.warn('[Map] scan message invalid')
      return
    }
    const ranges = message.ranges
    const angleMin = message.angle_min || 0
    const angleInc = message.angle_increment || 0
    const rangeMin = message.range_min ?? 0
    const rangeMax = message.range_max ?? Infinity

    const robot = useRobotStore()
    const theta = ((robot.status.theta || 0) * Math.PI) / 180
    const cosT = Math.cos(theta)
    const sinT = Math.sin(theta)

    const pts: Point3D[] = []
    for (let i = 0; i < ranges.length; i++) {
      const r = ranges[i]
      if (!isFinite(r) || r < rangeMin || r > rangeMax) continue
      const a = angleMin + i * angleInc
      const lx = r * Math.cos(a)
      const ly = r * Math.sin(a)
      const mx = robot.status.x + lx * cosT - ly * sinT
      const my = robot.status.y + lx * sinT + ly * cosT
      pts.push({ x: mx, y: my, z: 0 })
    }
    console.log('[Map] scan points:', pts.length)
    if (pts.length > 0) {
      const projected = projectTo2D(pts, currentMap.value.origin, currentMap.value.resolution)
      const max2DPoints = 5000
      const step2D = Math.ceil(projected.length / max2DPoints)
      pointCloudData.value = projected.filter((_, i) => i % step2D === 0)
      pointCloudDirty.value = true
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

  function resetData() {
    mapping.value = false
    localizationReady.value = false
    zoom.value = 1
    offset.value = { x: 0, y: 0 }
    mapBuffer.value = { data: new Uint8Array(0), width: 0, height: 0, resolution: 0.05, originX: 0, originY: 0 }
    mapBufferDirty.value = false
    pointCloudData.value = []
    pointCloudDirty.value = false
    pointCloud3DData.value = null
    globalPlan.value = { poses: [] }
    localPlan.value = { poses: [] }
    planDirty.value = false
    walls.value = []
    customPaths.value = []
    pois.value = []
    tempWallPoints.value = []
    tempPathPoints.value = []
    editorMode.value = 'none'
    editorDirty.value = false
    clearAllDrawings()
    currentMap.value = {
      name: '未连接',
      width: 0,
      height: 0,
      resolution: 0.05,
      origin: { x: 0, y: 0, theta: 0 },
      occupied: [],
      data: [],
    }
  }

  return {
    currentMap,
    activeTool,
    currentMapTab,
    setMapTab,
    currentMappingTab,
    setMappingTab,
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
    globalPlan,
    localPlan,
    planDirty,
    editorMode,
    walls,
    customPaths,
    pois,
    tempWallPoints,
    tempPathPoints,
    editorDirty,
    setGlobalPlan,
    setLocalPlan,
    setEditorMode,
    addWall,
    addCustomPath,
    addPoi,
    clearEditor,
    exportEditorJson,
    publishMapEditor,
    mapBuffer,
    mapBufferDirty,
    mapEditTool,
    brushSize,
    mapEditActive,
    canUndoMap,
    isEditingMap,
    mapReloading,
    setMapEditTool,
    beginMapStroke,
    paintCell,
    endMapStroke,
    undoMapEdit,
    saveEditedMap,
    finishMapReload,
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
    updateScanFromRos,
    clearPointCloud,
    isPointInMap,
    getMapBounds,
    centerMap,
    resetData,
    saveMap,
    deleteMap,
    loadMap,
    localize,
  }
})
