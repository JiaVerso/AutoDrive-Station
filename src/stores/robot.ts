import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import type { RobotStatus } from '@/types'
import { mockRobotStatus } from '@/mock/data'
import { rosApi } from '@/api/ros'
import { ElMessage } from 'element-plus'
import { useMapStore } from '@/stores/map'
import { useNavigationStore } from '@/stores/navigation'
import * as ROSLIB from 'roslib'

export const useRobotStore = defineStore('robot', () => {
  const status = ref<RobotStatus>({ ...mockRobotStatus, connected: false })
  const ip = ref('192.168.1.100')
  const port = ref('9090')
  const connecting = ref(false)
  const safetyStopped = ref(false)
  const cruiseEnabled = ref(false)
  let latencyTimer: ReturnType<typeof setInterval> | null = null

  function connect() {
    console.log(`[ROS-DIAG] robot.connect() 调用 → ip=${ip.value}, port=${port.value}`)
    console.log(`[ROS-DIAG] 即将连接 ws://${ip.value}:${port.value}`)
    connecting.value = true
    
    rosApi.disconnectRobot()
    
    rosApi.onConnection(() => {
      console.log('[ROS] Connection callback triggered')
      status.value = { ...mockRobotStatus, connected: true }
      connecting.value = false
      ElMessage.success({
        message: '成功连接到 ROS Bridge!',
        duration: 2000
      })
      
      subscribeToTopics()
      // TODO: 排查完毕后恢复 startLatencyPing()
      // startLatencyPing()
      
      setTimeout(() => {
        refreshTopics()
      }, 500)
    })

    rosApi.onError((error) => {
      status.value.connected = false
      connecting.value = false
      ElMessage.error({
        message: '连接失败: ' + error,
        duration: 2000
      })
    })

    rosApi.onClose(() => {
      if (status.value.connected) {
        status.value.connected = false
        ElMessage.warning({
          message: '连接已断开',
          duration: 2000
        })
      }
      resetAllStores()
    })

    rosApi.connectRobot(ip.value, port.value)
  }

  function disconnect() {
    status.value.connected = false
    stopLatencyPing()
    rosApi.disconnectRobot()
    resetAllStores()
    ElMessage.info({
      message: '已断开连接',
      duration: 2000
    })
  }

  function sendVelocity(linear: number, angular: number) {
    rosApi.sendVelocity(linear, angular)
    status.value.speed = Math.abs(linear)
  }

  function subscribeToTopics() {
    // 统一异常兜底：任何话题回调内的异常都被吞掉并记录，
    // 避免单次解析失败抛到事件循环外，导致 UI 卡死 / 视图切换无响应。
    const safe = (cb: (m: any) => void) => (m: any) => {
      try {
        cb(m)
      } catch (e) {
        console.error('[subscribeToTopics] 回调异常（已忽略）:', e)
      }
    }

    // ⚠️ 关键修复：/amcl_pose 由 amcl 以 TRANSIENT_LOCAL（latched）QoS 发布，
    // 默认 VOLATILE 订阅会因 QoS 不匹配而永远收不到 → 小车位置停留在 mock 初始值。
    // 必须用 rosbridge 支持的 durability/reliability/history 选项订阅。
    // 优先订阅小车真实话题 /amcl_pose；同时保留桥接话题 /amcl_pose_bridge 作为兼容。
    let hasAmclPose = false
    const onAmclPose = safe((message: any) => {
      if (!message || !message.pose || !message.pose.pose) return
      const pos = message.pose.pose.position
      const orient = message.pose.pose.orientation
      status.value.x = pos.x ?? status.value.x
      status.value.y = pos.y ?? status.value.y
      const yaw = Math.atan2(2 * (orient.w || 1) * (orient.z || 0), 1 - 2 * ((orient.z || 0) * (orient.z || 0)))
      status.value.theta = yaw * 180 / Math.PI
      status.value.poseSource = 'amcl'
      hasAmclPose = true
    })
    rosApi.subscribeTopic('/amcl_pose', 'geometry_msgs/msg/PoseWithCovarianceStamped', onAmclPose,
      { durability: 'transient_local', reliability: 'reliable', history: 'keep_last', depth: 10 })
    rosApi.subscribeTopic('/amcl_pose_bridge', 'geometry_msgs/msg/PoseWithCovarianceStamped', onAmclPose,
      { durability: 'transient_local', reliability: 'reliable', history: 'keep_last', depth: 10 })

    rosApi.subscribeTopic('/battery_state', 'sensor_msgs/msg/BatteryState', safe((message: any) => {
      status.value.battery = Math.round((message.percentage || 0) * 100)
      status.value.voltage = message.voltage || status.value.voltage
    }))

    rosApi.subscribeTopic('/robot_mode', 'std_msgs/msg/String', safe((message: any) => {
      status.value.mode = message.data || 'MANUAL'
    }))

    // ⚠️ 关键修复：/map 由 map_server / SLAM 以 TRANSIENT_LOCAL（latched）QoS 发布。
    // 默认 VOLATILE 订阅会因 QoS 不匹配而永远收不到 → 前端一直显示尺寸 0x0 的 mock 地图，
    // 航点坐标全部算错 → Nav2 规划失败 → 小车不动。必须显式声明 QoS。
    // 优先订阅小车真实话题 /map；同时保留桥接话题 /map_bridge 作为兼容。
    const onMap = safe((message: any) => {
      const mapStore = useMapStore()
      // 核心修复：正在手绘编辑地图，或保存后等待 map_server 重载新地图期间，
      // 拦截 ROS /map 话题的自动重绘，防止覆盖画板或回灌旧图。
      if (mapStore.isEditingMap || mapStore.mapReloading) {
        console.log('[Map] 正在编辑/重载地图，已拦截 ROS 话题的自动刷新重绘，防止覆盖画板。')
        return
      }
      console.log('接收到地图数据:', message)
      mapStore.updateMapFromRos(message)
    })
    rosApi.subscribeTopic('/map', 'nav_msgs/msg/OccupancyGrid', onMap,
      { durability: 'transient_local', reliability: 'reliable', history: 'keep_last', depth: 1 })
    rosApi.subscribeTopic('/map_bridge', 'nav_msgs/msg/OccupancyGrid', onMap,
      { durability: 'transient_local', reliability: 'reliable', history: 'keep_last', depth: 1 })

    // ===== 里程计 /odom（nav_msgs/msg/Odometry）：位姿 + 速度面板数据源 =====
    rosApi.subscribeTopic('/odom', 'nav_msgs/msg/Odometry', safe((message: any) => {
      const pose = message?.pose?.pose
      const tw = message?.twist?.twist
      // 若 amcl 已提供定位，则 odom 只用于速度；否则作为位姿兜底
      if (!hasAmclPose && pose) {
        status.value.x = pose.position?.x ?? status.value.x
        status.value.y = pose.position?.y ?? status.value.y
        const orient = pose.orientation
        if (orient) {
          const yaw = Math.atan2(2 * (orient.w || 1) * (orient.z || 0), 1 - 2 * ((orient.z || 0) * (orient.z || 0)))
          status.value.theta = yaw * 180 / Math.PI
        }
        status.value.poseSource = 'odom'
      }
      if (tw) {
        const v = Math.abs(tw.linear?.x || 0)
        status.value.speed = v
        const w = Math.abs(tw.angular?.z || 0)
        status.value.angularVelocity = w
      }
    }))

    // ===== 雷达激光扫描 /scan（sensor_msgs/msg/LaserScan）：投影为 2D 点云叠加 =====
    rosApi.subscribeTopic('/scan', 'sensor_msgs/msg/LaserScan', safe((message: any) => {
      useMapStore().updateScanFromRos(message)
    }))

    // ===== 点云别名 /points2（sensor_msgs/msg/PointCloud2）=====
    rosApi.subscribeTopic('/points2', 'sensor_msgs/msg/PointCloud2', safe((message: any) => {
      useMapStore().updatePointCloudFromRos(message)
    }))

    rosApi.subscribeTopic('/inspection_status', 'std_msgs/msg/String', safe((message: any) => {
      if (!message || !message.data) return
      const navStore = useNavigationStore()
      try {
        const payload = JSON.parse(message.data)
        if (payload.status === 'completed' || payload.status === 'finished') {
          navStore.onInspectionComplete()
        }
      } catch (_) {
        if (message.data === 'completed' || message.data === 'finished') {
          navStore.onInspectionComplete()
        }
      }
    }))

    rosApi.subscribeTopic('/map_convert_status', 'std_msgs/msg/String', safe((message: any) => {
      const navStore = useNavigationStore()
      let payload: any = {}
      try {
        payload = JSON.parse(message.data)
      } catch (_) {
        payload = { status: message.data }
      }
      const status = payload.status
      const detail = payload.detail || payload.message || ''
      if (status === 'done' || status === 'success' || status === 'completed') {
        navStore.addLog(`✅ 栅格地图保存完成 ${detail}`)
        ElMessage.success('2D 栅格地图已保存: ' + (payload.map_path || detail || ''))
      } else if (status === 'failed' || status === 'error') {
        navStore.addLog(`❌ 栅格地图保存失败 ${detail}`)
        ElMessage.error('栅格地图保存失败: ' + detail)
      } else {
        navStore.addLog(`⏳ 建图进度: ${status} ${detail}`)
      }
    }))

    rosApi.subscribeTopic('/terrain_points_downsampled', 'sensor_msgs/msg/PointCloud2', safe((message: any) => {
      useMapStore().updatePointCloudFromRos(message)
    }))

    rosApi.subscribeTopic('/lidar_points', 'sensor_msgs/msg/PointCloud2', safe((message: any) => {
      useMapStore().updatePointCloudFromRos(message)
    }))

    rosApi.subscribeTopic('/scan/points', 'sensor_msgs/msg/PointCloud2', safe((message: any) => {
      useMapStore().updatePointCloudFromRos(message)
    }))

    rosApi.subscribeTopic('/point_cloud', 'sensor_msgs/msg/PointCloud2', safe((message: any) => {
      useMapStore().updatePointCloudFromRos(message)
    }))

    rosApi.subscribeTopic('/livox/lidar', 'livox_ros_driver2/msg/CustomMsg', safe((message: any) => {
      useMapStore().updateLivoxPointCloud(message)
    }))

    // ===== 多图层：Nav2 全局/局部路径（nav_msgs/Path）=====
    const handlePlan = (setter: (m: any) => void) => safe((message: any) => setter(message))
    rosApi.subscribeTopic('/plan', 'nav_msgs/msg/Path', handlePlan((m) => useMapStore().setGlobalPlan(m)))
    rosApi.subscribeTopic('/global_plan', 'nav_msgs/msg/Path', handlePlan((m) => useMapStore().setGlobalPlan(m)))
    rosApi.subscribeTopic('/local_plan', 'nav_msgs/msg/Path', handlePlan((m) => useMapStore().setLocalPlan(m)))

    rosApi.subscribeTopic('/rosout', 'rosgraph_msgs/msg/Log', safe((message: any) => {
      if (!message || !message.msg) return
      const navStore = useNavigationStore()
      const levelLabel = ['DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL'][message.level] || 'UNKNOWN'
      navStore.addLog(`[${levelLabel}] [${message.name || ''}] ${message.msg}`)
    }))
  }

  function refreshTopics() {
    const event = new CustomEvent('ros-topics-refresh')
    window.dispatchEvent(event)
  }

  // ===== 轻量级 RTT 延时探测：订阅 /rosapi/get_time 服务 =====
  // 每 2 秒调用一次，记录发出/返回时刻，差值即为网络往返延时（ms）。
  function startLatencyPing() {
    if (latencyTimer) return
    const ros = (rosApi as any).ros
    if (!ros || !ros.isConnected) return

    let getTimeService: any = null
    try {
      getTimeService = new ROSLIB.Service({
        ros,
        name: '/rosapi/get_time',
        serviceType: 'rosapi/GetTime'
      })
    } catch (_) {
      console.error('[latencyPing] 构造 /rosapi/get_time 服务失败:', _)
      return
    }

    const ping = () => {
      if (!ros.isConnected) {
        stopLatencyPing()
        return
      }
      const t0 = performance.now()
      getTimeService.callService(
        {},
        () => {
          status.value.latency = Math.round(performance.now() - t0)
        },
        () => {
          // 服务调用失败时不清零，仅标记异常，避免数值抖动
          status.value.latency = -1
        }
      )
    }

    latencyTimer = setInterval(ping, 2000)
    ping()
  }

  function stopLatencyPing() {
    if (latencyTimer) {
      clearInterval(latencyTimer)
      latencyTimer = null
    }
  }

  // ===== 联动 navStore：根据巡检状态机同步 navStatus =====
  // RUNNING/执行中 → 'navigating'；PAUSED → 'paused'；
  // 不可达/错误态 → 'error'；其余（IDLE/ADDING/SAVED）→ 'idle'。
  const navStore = useNavigationStore()
  watch(
    () => navStore.currentStatus,
    (val) => {
      switch (val) {
        case 'RUNNING':
          status.value.navStatus = 'navigating'
          break
        case 'PAUSED':
          status.value.navStatus = 'paused'
          break
        default:
          status.value.navStatus = 'idle'
      }
    },
    { immediate: true }
  )


  function triggerSafetyStop(stop: boolean) {
    safetyStopped.value = stop
    rosApi.publishTopic('/safety_status', 'std_msgs/msg/Bool', { data: stop })
    if (stop) {
      sendVelocity(0, 0)
      ElMessage.warning('急停已触发')
    } else {
      ElMessage.success('急停已解除')
    }
  }

  function toggleCruise(enabled: boolean) {
    cruiseEnabled.value = enabled
    rosApi.publishTopic('/cruise_cmd', 'std_msgs/msg/Bool', { data: enabled })
    if (enabled) {
      ElMessage.success('自主巡航已开启')
    } else {
      ElMessage.info('自主巡航已关闭')
    }
  }

  function resetStoreData() {
    status.value = { ...mockRobotStatus, connected: false }
    connecting.value = false
    safetyStopped.value = false
    cruiseEnabled.value = false
    stopLatencyPing()
    status.value.latency = 0
    status.value.navStatus = 'idle'
  }

  function resetAllStores() {
    resetStoreData()
    useMapStore().resetData()
    useNavigationStore().resetData()
  }

  return { 
    status, 
    ip, 
    port, 
    connecting, 
    safetyStopped,
    cruiseEnabled,
    connect, 
    disconnect,
    sendVelocity,
    triggerSafetyStop,
    toggleCruise,
    resetStoreData,
    resetAllStores,
    startLatencyPing,
    stopLatencyPing,
  }
})
