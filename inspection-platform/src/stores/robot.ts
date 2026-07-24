import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { RobotStatus } from '@/types'
import { mockRobotStatus } from '@/mock/data'
import { rosApi } from '@/api/ros'
import { ElMessage } from 'element-plus'

export const useRobotStore = defineStore('robot', () => {
  const status = ref<RobotStatus>({ ...mockRobotStatus, connected: false })
  const ip = ref('192.168.1.100')
  const port = ref('9090')
  const connecting = ref(false)
  const safetyStopped = ref(false)
  const cruiseEnabled = ref(false)

  function connect() {
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
    })

    rosApi.connectRobot(ip.value, port.value)
  }

  function disconnect() {
    status.value.connected = false
    rosApi.disconnectRobot()
    import('@/stores/map').then(({ useMapStore }) => {
      const mapStore = useMapStore()
      mapStore.clearPointCloud()
    })
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
    rosApi.subscribeTopic('/turtle1/pose', 'turtlesim/msg/Pose', (message: any) => {
      status.value.x = message.x || status.value.x
      status.value.y = message.y || status.value.y
      status.value.theta = (message.theta || 0) * 180 / Math.PI
      status.value.speed = Math.sqrt(Math.pow(message.linear_velocity, 2) + Math.pow(message.angular_velocity, 2))
    })

    rosApi.subscribeTopic('/battery_state', 'sensor_msgs/msg/BatteryState', (message: any) => {
      status.value.battery = Math.round((message.percentage || 0) * 100)
      status.value.voltage = message.voltage || status.value.voltage
    })

    rosApi.subscribeTopic('/robot_mode', 'std_msgs/msg/String', (message: any) => {
      status.value.mode = message.data || 'MANUAL'
    })

    rosApi.subscribeTopic('/map', 'nav_msgs/msg/OccupancyGrid', (message: any) => {
      import('@/stores/map').then(({ useMapStore }) => {
        const mapStore = useMapStore()
        mapStore.updateMapFromRos(message)
      })
    })

    rosApi.subscribeTopic('/terrain_points_downsampled', 'sensor_msgs/msg/PointCloud2', (message: any) => {
      import('@/stores/map').then(({ useMapStore }) => {
        const mapStore = useMapStore()
        mapStore.updatePointCloudFromRos(message)
      })
    })

    rosApi.subscribeTopic('/lidar_points', 'sensor_msgs/msg/PointCloud2', (message: any) => {
      import('@/stores/map').then(({ useMapStore }) => {
        const mapStore = useMapStore()
        mapStore.updatePointCloudFromRos(message)
      })
    })

    rosApi.subscribeTopic('/scan/points', 'sensor_msgs/msg/PointCloud2', (message: any) => {
      import('@/stores/map').then(({ useMapStore }) => {
        const mapStore = useMapStore()
        mapStore.updatePointCloudFromRos(message)
      })
    })

    rosApi.subscribeTopic('/point_cloud', 'sensor_msgs/msg/PointCloud2', (message: any) => {
      import('@/stores/map').then(({ useMapStore }) => {
        const mapStore = useMapStore()
        mapStore.updatePointCloudFromRos(message)
      })
    })

    rosApi.subscribeTopic('/livox/lidar', 'livox_ros_driver2/msg/CustomMsg', (message: any) => {
      import('@/stores/map').then(({ useMapStore }) => {
        const mapStore = useMapStore()
        mapStore.updateLivoxPointCloud(message)
      })
    })
  }

  function refreshTopics() {
    const event = new CustomEvent('ros-topics-refresh')
    window.dispatchEvent(event)
  }

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
    toggleCruise
  }
})