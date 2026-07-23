import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { Waypoint, Path, NavigationStatus, InspectionStatus, WaypointEditState, SavedRoute } from '@/types'
import { rosApi } from '@/api/ros'
import { yawToQuaternion, quaternionToYaw } from '@/utils/coordinateConverter'
import * as ROSLIB from 'roslib'

export const useNavigationStore = defineStore('navigation', () => {
  const waypoints = ref<Waypoint[]>([])
  const paths = ref<Path[]>([])
  const currentPath = ref<Path | null>(null)
  const navStatus = ref<NavigationStatus>({
    active: false,
    paused: false,
    currentWaypointIndex: 0,
    progress: 0,
  })

  let navInterval: ReturnType<typeof setInterval> | null = null

  // ===== Inspection State Machine (Demo 3 port) =====
  const currentStatus = ref<InspectionStatus>('IDLE')
  const waypointList = ref<{ x: number; y: number; yaw: number; qz: number; qw: number }[]>([])
  const wpEditStage = ref(0)
  const wpEditStart = ref<{ wx: number; wy: number; cx: number; cy: number } | null>(null)
  const wpEditCurrent = ref<{ cx: number; cy: number } | null>(null)
  const inspectionStatusText = ref('')
  const waypointCountText = ref('航点: 0')
  const consoleLogs = ref<string[]>([])

  const savedRoutes = ref<SavedRoute[]>([])

  // ===== Initial Pose (2D Pose Estimate) =====
  const isInitialPoseMode = ref(false)
  const initPoseStage = ref(0)           // 0=idle, 1=first click done
  const initPoseStart = ref<{ wx: number; wy: number; cx: number; cy: number } | null>(null)
  const initPoseCurrent = ref<{ cx: number; cy: number } | null>(null)

  function enterInitialPoseMode() {
    isInitialPoseMode.value = true
    initPoseStage.value = 0
    initPoseStart.value = null
    initPoseCurrent.value = null
    addLog('🎯 初始定位模式已开启 — 在地图上点击设定初始位置和朝向')
  }

  function exitInitialPoseMode() {
    isInitialPoseMode.value = false
    initPoseStage.value = 0
    initPoseStart.value = null
    initPoseCurrent.value = null
  }

  const isAddingMode = computed(() => currentStatus.value === 'ADDING')
  const isRunning = computed(() => currentStatus.value === 'RUNNING')
  const isPausedState = computed(() => currentStatus.value === 'PAUSED')
  const isSaved = computed(() => currentStatus.value === 'SAVED')
  const isIdle = computed(() => currentStatus.value === 'IDLE')

  let inspectionCmdTopic: any = null
  let waypointPathTopic: any = null
  let inspectionStatusTopic: any = null

  watch(currentStatus, (val) => {
    console.log('[DEBUG] [watch] currentStatus 变化:', val)
  })

  function addLog(text: string) {
    const time = new Date().toLocaleTimeString()
    consoleLogs.value.unshift(`[${time}] ${text}`)
    if (consoleLogs.value.length > 200) consoleLogs.value.splice(200)
  }

  function clearLogs() {
    consoleLogs.value = []
  }

  // ===== Waypoint helpers =====
  function addWaypoint(wp: Omit<Waypoint, 'id' | 'order'>) {
    const id = 'wp' + (waypoints.value.length + 1)
    const order = waypoints.value.length + 1
    waypoints.value.push({ ...wp, id, order, yaw: wp.yaw || 0, qz: wp.qz || 0, qw: wp.qw || 1 })
  }

  function removeWaypoint(id: string) {
    waypoints.value = waypoints.value.filter((w) => w.id !== id)
  }

  function clearWaypoints() {
    waypoints.value.splice(0, waypoints.value.length)
  }

  // ===== Inspection State Machine =====
  function setInspectionStatus(newStatus: InspectionStatus) {
    console.log(`[DEBUG] Inspection status: ${currentStatus.value} -> ${newStatus}`)
    currentStatus.value = newStatus
  }

  function resetInspection() {
    waypointList.value = []
    wpEditStage.value = 1
    wpEditStart.value = null
    wpEditCurrent.value = null
    setInspectionStatus('IDLE')
    updateInspectionUI()
    addLog('系统提示: 巡检状态已复位')
    console.log('[DEBUG] resetInspection: 状态机已彻底复位到 IDLE')
  }

  function loadSavedRoutesFromStorage() {
    try {
      const stored = localStorage.getItem('inspection_saved_routes')
      if (stored) {
        savedRoutes.value = JSON.parse(stored)
        console.log('[DEBUG] 从 localStorage 加载了', savedRoutes.value.length, '条航线')
      }
    } catch (e) {
      console.error('[DEBUG] 加载保存的航线失败:', e)
      savedRoutes.value = []
    }
  }

  function saveRoutesToStorage() {
    try {
      localStorage.setItem('inspection_saved_routes', JSON.stringify(savedRoutes.value))
      console.log('[DEBUG] 已保存', savedRoutes.value.length, '条航线到 localStorage')
    } catch (e) {
      console.error('[DEBUG] 保存航线到 localStorage 失败:', e)
    }
  }

  function saveCurrentRoute(name: string): SavedRoute | null {
    if (waypointList.value.length === 0) {
      addLog('系统提示: 航点列表为空，无法保存')
      return null
    }

    const route: SavedRoute = {
      id: 'route_' + Date.now(),
      name,
      waypoints: [...waypointList.value],
      createdAt: new Date().toLocaleString('zh-CN')
    }

    savedRoutes.value.push(route)
    saveRoutesToStorage()
    addLog(`✅ 航线 "${name}" 已保存到本地`)
    console.log('[DEBUG] 保存航线:', route.name, '-', route.waypoints.length, '个航点')
    return route
  }

  function loadRoute(id: string): boolean {
    const route = savedRoutes.value.find(r => r.id === id)
    if (!route) {
      addLog('系统提示: 未找到该航线')
      return false
    }

    waypointList.value = [...route.waypoints]
    wpEditStage.value = 1
    wpEditStart.value = null
    wpEditCurrent.value = null
    setInspectionStatus('SAVED')
    updateInspectionUI()
    addLog(`✅ 已加载航线 "${route.name}" (${route.waypoints.length} 个航点)`)
    console.log('[DEBUG] 加载航线:', route.name)
    return true
  }

  function deleteRoute(id: string): boolean {
    const index = savedRoutes.value.findIndex(r => r.id === id)
    if (index === -1) {
      addLog('系统提示: 未找到该航线')
      return false
    }

    const routeName = savedRoutes.value[index].name
    savedRoutes.value.splice(index, 1)
    saveRoutesToStorage()
    addLog(`🗑️ 已删除航线 "${routeName}"`)
    console.log('[DEBUG] 删除航线:', routeName)
    return true
  }

  function updateInspectionUI() {
    const len = waypointList.value.length
    waypointCountText.value = `航点: ${len}`

    switch (currentStatus.value) {
      case 'IDLE':
        inspectionStatusText.value = '⚪ 就绪'
        break
      case 'ADDING':
        inspectionStatusText.value = '🟡 航点录入中...'
        break
      case 'SAVED':
        inspectionStatusText.value = `🟢 已保存 ${len} 个航点`
        break
      case 'RUNNING':
        inspectionStatusText.value = '🔵 巡检运行中'
        break
      case 'PAUSED':
        inspectionStatusText.value = '🟠 巡检已暂停'
        break
    }
  }

  // ===== Button Handlers =====
  function onAddWaypoints() {
    console.log('[DEBUG] onAddWaypoints clicked, current status:', currentStatus.value)

    if (currentStatus.value === 'ADDING') {
      resetInspection()
      addLog('系统提示: 已取消航点编辑')
      return
    }

    waypointList.value = []
    wpEditStage.value = 0
    wpEditStart.value = null
    wpEditCurrent.value = null
    setInspectionStatus('ADDING')
    updateInspectionUI()
    addLog('🟡 进入多航点录入模式 — 点击地图连续添加航点，每点两下确定一个航点')
    console.log('[DEBUG] 进入 ADDING 模式')
  }

  function onCompleteWaypoints() {
    console.log('[DEBUG] 点击"完成添加", 当前航点数据:', JSON.stringify(waypointList.value))
    console.log('[DEBUG] 航点数量:', waypointList.value.length)

    if (waypointList.value.length === 0) {
      addLog('系统提示: 请至少添加一个航点')
      return
    }

    try {
      publishWaypointPath()
    } catch (err: any) {
      const errMsg = `⚠️ 下发航点路径异常: ${err.message || err}`
      addLog(errMsg)
      console.error('[DEBUG] ❌ publishWaypointPath 异常:', err)
    }

    setInspectionStatus('SAVED')
    updateInspectionUI()
    console.log('[DEBUG] 状态已切换至 SAVED')
    addLog(`✅ 完成录入 — 已保存 ${waypointList.value.length} 个航点路径，可点击"开始巡检"执行任务`)
  }

  async function onStartInspection() {
    console.log('[DEBUG] ====== 开始巡检流程 ======')
    console.log('[DEBUG] 当前 waypointList:', JSON.stringify(waypointList.value))

    if (waypointList.value.length === 0) {
      addLog('系统提示: 航点列表为空，请先添加航点')
      console.warn('[DEBUG] onStartInspection 中止: waypointList 为空')
      return
    }

    console.log('[DEBUG] Step 1/2: 重新下发航点路径到 /waypoint_user_path ...')
    console.log('[DEBUG] 1. 巡检航点数据已下发，正在等待缓存同步...')
    publishWaypointPath()

    await new Promise(resolve => setTimeout(resolve, 400))
    console.log('[DEBUG] 2. 缓存同步结束，正式下发 "start" 启动指令')

    if (!inspectionCmdTopic) {
      inspectionCmdTopic = new ROSLIB.Topic({
        ros: (rosApi as any).ros,
        name: '/inspection_cmd',
        messageType: 'std_msgs/msg/String'
      })
    }

    const cmdPayload = JSON.stringify({ cmd: 'start' })

    try {
      inspectionCmdTopic.publish({ data: cmdPayload })
      setInspectionStatus('RUNNING')
      updateInspectionUI()
      addLog('▶️ 已发送"开始巡检"命令')
      console.log('[DEBUG] ✅ 【前端送达】巡检启动信号已成功送出: /inspection_cmd')
      console.log('[DEBUG] ====== 巡检启动流程结束 ======')
    } catch (err: any) {
      const errMsg = `❌ 发布开始巡检命令失败: ${err.message || err}`
      addLog(errMsg)
      console.error('[DEBUG] ❌ publish() 抛异常:', err)
    }
  }

  function onPauseInspection() {
    console.log('[DEBUG] ====== 暂停巡检 ======')

    if (!inspectionCmdTopic) {
      inspectionCmdTopic = new ROSLIB.Topic({
        ros: (rosApi as any).ros,
        name: '/inspection_cmd',
        messageType: 'std_msgs/msg/String'
      })
    }

    const cmdPayload = JSON.stringify({ cmd: 'pause' })
    console.log('[DEBUG] 发送 pause 到 /inspection_cmd:', cmdPayload)

    try {
      inspectionCmdTopic.publish({ data: cmdPayload })
      setInspectionStatus('PAUSED')
      updateInspectionUI()
      addLog('⏸️ 已发送"暂停巡检"命令')
      console.log('[DEBUG] ✅ 暂停指令已送达 /inspection_cmd')
      console.log('[DEBUG] 终止信号已通过 WebSocket 送出')
    } catch (err: any) {
      const errMsg = `❌ 发布暂停巡检命令失败: ${err.message || err}`
      addLog(errMsg)
      console.error('[DEBUG] ❌ publish() 抛异常:', err)
    }
  }

  function onStopInspection() {
    console.log('[DEBUG] ====== 终止巡检 ======')

    if (!inspectionCmdTopic) {
      inspectionCmdTopic = new ROSLIB.Topic({
        ros: (rosApi as any).ros,
        name: '/inspection_cmd',
        messageType: 'std_msgs/msg/String'
      })
    }

    const cmdPayload = JSON.stringify({ cmd: 'stop' })
    console.log('[DEBUG] 发送 stop 到 /inspection_cmd:', cmdPayload)

    try {
      inspectionCmdTopic.publish({ data: cmdPayload })
      resetInspection()
      addLog('⏹️ 已发送"终止巡检"命令')
      console.log('[DEBUG] ✅ 终止指令已送达 /inspection_cmd')
      console.log('[DEBUG] 终止信号已通过 WebSocket 送出')
    } catch (err: any) {
      const errMsg = `❌ 发布终止巡检命令失败: ${err.message || err}`
      addLog(errMsg)
      console.error('[DEBUG] ❌ publish() 抛异常:', err)
    }
  }

  // ===== ROS Topic Publishing =====
  function publishWaypointPath() {
    const ros = (rosApi as any).ros
    if (!ros || !ros.isConnected) {
      addLog('系统提示: 未连接，无法下发航点路径')
      return
    }

    console.log('[DEBUG] 准备下发航点路径, waypointList:', JSON.stringify(waypointList.value, null, 2))
    console.log('[DEBUG] 当前连接状态:', ros.isConnected)

    waypointPathTopic = new ROSLIB.Topic({
      ros: ros,
      name: '/waypoint_user_path',
      messageType: 'geometry_msgs/msg/PoseArray'
    })

    const poses = waypointList.value.map(wp => ({
      position: { x: wp.x, y: wp.y, z: 0.0 },
      orientation: { x: 0.0, y: 0.0, z: wp.qz, w: wp.qw }
    }))

    try {
      const msg = {
        header: {
          frame_id: 'map',
          stamp: { sec: 0, nanosec: 0 }
        },
        poses: poses
      }
      waypointPathTopic.publish(msg)
      addLog(`📤 已下发 ${waypointList.value.length} 个航点到 /waypoint_user_path`)
      console.log('[DEBUG] PoseArray 发布成功, 消息内容:', JSON.stringify(msg))
    } catch (err: any) {
      const errMsg = `❌ 发布航点路径失败: ${err.message || err}`
      addLog(errMsg)
      console.error('[DEBUG] 发布错误:', err)
    }
  }

  // ===== Inspection Status Subscription =====
  function subscribeInspectionStatus() {
    try {
      const ros = (rosApi as any).ros
      if (!ros || !ros.isConnected) {
        console.log('[DEBUG] subscribeInspectionStatus: ROS 未连接，跳过')
        return
      }

      if (inspectionStatusTopic) {
        inspectionStatusTopic.unsubscribe()
      }

      inspectionStatusTopic = new ROSLIB.Topic({
        ros: ros,
        name: '/inspection_status',
        messageType: 'std_msgs/msg/String'
      })

      inspectionStatusTopic.subscribe((msg: any) => {
        if (!msg || !msg.data) return
        console.log('[DEBUG] [navigation.ts] /inspection_status 收到:', msg.data)
        try {
          const payload = JSON.parse(msg.data)
          if (payload.status === 'completed' || payload.status === 'finished') {
            console.log('[DEBUG] [navigation.ts] 触发 onInspectionComplete()')
            onInspectionComplete()
          } else if (payload.status === 'error: unreachable') {
            // Nav2 状态码 6 (ABORTED)：目标点不可达 / 被取消，
            // 明确提示用户并将 RUNNING 复位为 IDLE，等待重新选取航点。
            const reason = payload.reason || '目标点不可达或被取消（Nav2 规划失败）'
            console.warn('[navigation.ts] 巡检不可达：', reason)
            currentStatus.value = 'IDLE'
            inspectionStatusText.value = '⚠ 目标不可达'
            ElMessage.warning(reason)
            addLog('⚠ 巡检任务中止：' + reason)
          } else if (payload.status === 'idle') {
            // 被取消 / 其它中断：确保状态机回到就绪
            if (currentStatus.value === 'RUNNING' || currentStatus.value === 'PAUSED') {
              currentStatus.value = 'IDLE'
              inspectionStatusText.value = '⚪ 就绪'
              addLog('ℹ 巡检已中断，状态复位为就绪')
            }
          }
        } catch (_) {
          if (msg.data === 'completed' || msg.data === 'finished') {
            console.log('[DEBUG] [navigation.ts] 纯文本匹配，触发 onInspectionComplete()')
            onInspectionComplete()
          }
        }
      })

      addLog('系统提示: 已订阅巡检状态话题 /inspection_status')
      console.log('[DEBUG] [navigation.ts] 已订阅 /inspection_status')
    } catch (err) {
      console.error('[DEBUG] [navigation.ts] 订阅失败:', err)
    }
  }

  function onInspectionComplete() {
    addLog('✅ [系统通知] 巡检任务已圆满完成')
    console.log('[DEBUG] 巡检完成，复位状态')
    resetInspection()
  }

  // ===== (Keep existing path management for backward compatibility) =====
  function savePath(name: string) {
    const path: Path = {
      id: 'path_' + Date.now(),
      name,
      waypoints: [...waypoints.value],
    }
    paths.value.push(path)
    return path
  }

  function loadPath(pathId: string) {
    const path = paths.value.find((p) => p.id === pathId)
    if (path) {
      currentPath.value = path
      waypoints.value = [...path.waypoints]
    }
  }

  function deletePath(pathId: string) {
    paths.value = paths.value.filter((p) => p.id !== pathId)
  }

  function startNavigation() {
    if (!currentPath.value && paths.value.length > 0) {
      currentPath.value = paths.value[0]
    }
    if (!currentPath.value) return
    navStatus.value.active = true
    navStatus.value.paused = false
    navStatus.value.currentWaypointIndex = 0
    navStatus.value.progress = 0
    navInterval = setInterval(() => {
      if (!navStatus.value.paused) {
        navStatus.value.progress += 2
        if (navStatus.value.progress >= 100) {
          navStatus.value.progress = 0
          navStatus.value.currentWaypointIndex++
          if (navStatus.value.currentWaypointIndex >= (currentPath.value?.waypoints.length || 0)) {
            stopNavigation()
          }
        }
      }
    }, 200)
  }

  function pauseNavigation() {
    navStatus.value.paused = true
  }

  function resumeNavigation() {
    navStatus.value.paused = false
  }

  function cancelNavigation() {
    stopNavigation()
  }

  function stopNavigation() {
    navStatus.value.active = false
    navStatus.value.paused = false
    navStatus.value.currentWaypointIndex = 0
    navStatus.value.progress = 0
    if (navInterval) {
      clearInterval(navInterval)
      navInterval = null
    }
  }

  function sendGoalPose(x: number, y: number, theta: number = 0) {
    const goalPose = {
      header: {
        stamp: { sec: Math.floor(Date.now() / 1000), nanosec: (Date.now() % 1000) * 1000000 },
        frame_id: 'map'
      },
      pose: {
        position: { x, y, z: 0 },
        orientation: {
          x: 0,
          y: 0,
          z: Math.sin(theta / 2),
          w: Math.cos(theta / 2)
        }
      }
    }
    rosApi.publishTopic('/goal_pose', 'geometry_msgs/msg/PoseStamped', goalPose)
  }

  function generateWaypointsJson(): string {
    const data = {
      timestamp: Date.now(),
      waypoints: waypoints.value.map((wp) => ({
        id: wp.id,
        name: wp.name,
        x: wp.x,
        y: wp.y,
        yaw: wp.yaw,
        qz: wp.qz,
        qw: wp.qw,
        order: wp.order
      })),
      path: currentPath.value ? {
        id: currentPath.value.id,
        name: currentPath.value.name
      } : null,
      count: waypoints.value.length
    }
    return JSON.stringify(data, null, 2)
  }

  function saveWaypointsToFile(): boolean {
    if (waypoints.value.length === 0) return false
    const jsonStr = generateWaypointsJson()
    const blob = new Blob([jsonStr], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `waypoints_${Date.now()}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    return true
  }

  function sendWaypointsToRos(): boolean {
    if (waypoints.value.length === 0) return false
    const jsonStr = generateWaypointsJson()
    const message = {
      header: {
        stamp: { sec: Math.floor(Date.now() / 1000), nanosec: (Date.now() % 1000) * 1000000 },
        frame_id: 'map'
      },
      data: jsonStr
    }
    rosApi.publishTopic('/waypoints_json', 'std_msgs/msg/String', message)
    return true
  }

  function sendWaypointsAndSave(): boolean {
    if (waypoints.value.length === 0) return false
    const saved = saveWaypointsToFile()
    const sent = sendWaypointsToRos()
    return saved && sent
  }

  function resetData() {
    waypoints.value = []
    paths.value = []
    currentPath.value = null
    navStatus.value = { active: false, paused: false, currentWaypointIndex: 0, progress: 0 }
    waypointList.value = []
    currentStatus.value = 'IDLE'
    inspectionStatusText.value = '⚪ 就绪'
    waypointCountText.value = '航点: 0'
    consoleLogs.value = []
    wpEditStage.value = 0
    wpEditStart.value = null
    wpEditCurrent.value = null
  }

  return {
    waypoints,
    paths,
    currentPath,
    navStatus,
    currentStatus,
    waypointList,
    wpEditStage,
    wpEditStart,
    wpEditCurrent,
    inspectionStatusText,
    waypointCountText,
    consoleLogs,
    savedRoutes,
    isAddingMode,
    isRunning,
    isPausedState,
    isSaved,
    isIdle,
    addWaypoint,
    removeWaypoint,
    clearWaypoints,
    savePath,
    loadPath,
    deletePath,
    startNavigation,
    pauseNavigation,
    resumeNavigation,
    cancelNavigation,
    stopNavigation,
    sendGoalPose,
    generateWaypointsJson,
    saveWaypointsToFile,
    sendWaypointsToRos,
    sendWaypointsAndSave,
    setInspectionStatus,
    resetInspection,
    updateInspectionUI,
    onAddWaypoints,
    onCompleteWaypoints,
    onStartInspection,
    onPauseInspection,
    onStopInspection,
    publishWaypointPath,
    subscribeInspectionStatus,
    onInspectionComplete,
    isInitialPoseMode,
    initPoseStage,
    initPoseStart,
    initPoseCurrent,
    enterInitialPoseMode,
    exitInitialPoseMode,
    addLog,
    clearLogs,
    resetData,
    saveCurrentRoute,
    loadRoute,
    deleteRoute,
    loadSavedRoutesFromStorage,
  }
})
