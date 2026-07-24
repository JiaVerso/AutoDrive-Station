import * as ROSLIB from 'roslib'

export interface TopicInfo {
  name: string
  type: string
  message: any
  lastUpdate: number
  subscribed?: boolean
}

export interface TopicQosOptions {
  durability?: 'volatile' | 'transient_local'
  reliability?: 'reliable' | 'best_effort'
  history?: 'keep_last' | 'keep_all'
  depth?: number
}

export interface RosApi {
  connectRobot: (ip: string, port: string) => Promise<boolean>
  disconnectRobot: () => void
  startMapping: () => void
  saveMap: (name: string) => void
  startLocalization: () => void
  startNavigation: () => void
  pauseNavigation: () => void
  resumeNavigation: () => void
  cancelNavigation: () => void
  sendVelocity: (linear: number, angular: number) => void
  publishTopic: (topicName: string, messageType: string, message: any) => void
  onConnection: (callback: () => void) => void
  onError: (callback: (error: any) => void) => void
  onClose: (callback: () => void) => void
  subscribeTopic: <T>(topicName: string, messageType: string, callback: (message: T) => void, options?: TopicQosOptions) => void
  unsubscribeTopic: (topicName: string) => void
  getTopics: (callback: (topics: TopicInfo[]) => void) => void
  subscribeAllTopics: (callback: (topic: TopicInfo) => void) => void
  unsubscribeAllTopics: () => void
  // 诊断：查询某话题当前在 ROS 侧的订阅者数量。
  // 遥控“发了但不动”时，0 说明没有任何节点（底盘/twist_mux）在监听该话题。
  getNumSubscribers: (topicName: string, callback: (n: number) => void) => void
}

// 手动遥控默认话题。绝大多数真实底盘/SparkCar 通过 twist_mux 接入，
// 手动遥控需要发到 mux 的输入端（如 /cmd_vel_teleop），而不是被 mux 占用的输出端 /cmd_vel。
// 若该值不对，前端会在“手动控制”面板给出下拉框实时切换，并展示订阅者数量用于排查。
export const VEL_TOPIC_NAME = '/cmd_vel'

class RealRosApi implements RosApi {
  private ros: ROSLIB.Ros | null = null
  private topics: Map<string, ROSLIB.Topic> = new Map()
  private topicInfo: Map<string, TopicInfo> = new Map()
  private connectionCallbacks: (() => void)[] = []
  private errorCallbacks: ((error: any) => void)[] = []
  private closeCallbacks: (() => void)[] = []
  private allTopicsCallback: ((topic: TopicInfo) => void) | null = null

  async connectRobot(ip: string, port: string): Promise<boolean> {
    return new Promise((resolve) => {
      if (this.ros) {
        this.ros.close()
      }

      const url = `ws://${ip}:${port}`
      console.log(`[ROS-DIAG] 尝试连接 WebSocket: ${url}`)
      this.ros = new ROSLIB.Ros({ url })

      this.ros.on('connection', () => {
        const wsState = (this.ros as any).socket?.readyState
        console.log(`[ROS-DIAG] ✅ Connected to ${url} | socket.readyState=${wsState}`)
        this.connectionCallbacks.forEach(cb => cb())
        resolve(true)
      })

      this.ros.on('error', (error: any) => {
        console.error(`[ROS-DIAG] ❌ Connection error on ${url}:`, error)
        this.errorCallbacks.forEach(cb => cb(error))
        resolve(false)
      })

      this.ros.on('close', () => {
        console.log(`[ROS-DIAG] ⚠️ Connection closed: ${url}`)
        this.closeCallbacks.forEach(cb => cb())
      })
    })
  }

  disconnectRobot(): void {
    if (this.ros) {
      this.ros.close()
      this.ros = null
    }
    this.unsubscribeAllTopics()
    this.topics.clear()
    this.topicInfo.clear()
    this.publishTopicsCache.clear()
    this.connectionCallbacks = []
    this.errorCallbacks = []
    this.closeCallbacks = []
  }

  startMapping(): void {
    const service = new ROSLIB.Service({
      ros: this.ros!,
      name: '/start_mapping',
      serviceType: 'std_srvs/srv/Trigger'
    })
    service.callService({}, (response: any) => {
      console.log('[ROS] Mapping started:', response)
    })
  }

  saveMap(name: string): void {
    const service = new ROSLIB.Service({
      ros: this.ros!,
      name: '/save_map',
      serviceType: 'nav2_map_server/srv/SaveMap'
    })
    service.callService({ map_file_name: name }, (response: any) => {
      console.log('[ROS] Map saved:', response)
    })
  }

  startLocalization(): void {
    const service = new ROSLIB.Service({
      ros: this.ros!,
      name: '/start_localization',
      serviceType: 'std_srvs/srv/Trigger'
    })
    service.callService({}, (response: any) => {
      console.log('[ROS] Localization started:', response)
    })
  }

  startNavigation(): void {
    const service = new ROSLIB.Service({
      ros: this.ros!,
      name: '/navigate_to_pose',
      serviceType: 'nav2_msgs/srv/NavigateToPose'
    })
    service.callService({}, (response: any) => {
      console.log('[ROS] Navigation started:', response)
    })
  }

  pauseNavigation(): void {
    const service = new ROSLIB.Service({
      ros: this.ros!,
      name: '/pause_navigation',
      serviceType: 'std_srvs/srv/Trigger'
    })
    service.callService({}, (response: any) => {
      console.log('[ROS] Navigation paused:', response)
    })
  }

  resumeNavigation(): void {
    const service = new ROSLIB.Service({
      ros: this.ros!,
      name: '/resume_navigation',
      serviceType: 'std_srvs/srv/Trigger'
    })
    service.callService({}, (response: any) => {
      console.log('[ROS] Navigation resumed:', response)
    })
  }

  cancelNavigation(): void {
    const service = new ROSLIB.Service({
      ros: this.ros!,
      name: '/cancel_navigation',
      serviceType: 'std_srvs/srv/Trigger'
    })
    service.callService({}, (response: any) => {
      console.log('[ROS] Navigation cancelled:', response)
    })
  }

  sendVelocity(linear: number, angular: number): void {
    // 🔍 [DIAG-STEP3] sendVelocity 诊断
    const ws: WebSocket | undefined = (this.ros as any)?.socket
    const wsReady = ws?.readyState ?? -1
    console.log(
      `%c[ROS-DIAG] sendVelocity → linear=${linear}, angular=${angular}`,
      'color: #e91e63; font-weight: bold',
      `| ros.isConnected=${(this.ros as any)?.isConnected}`,
      `| socket.readyState=${wsReady}`
    )
    const topic = new ROSLIB.Topic({
      ros: this.ros!,
      name: '/cmd_vel',
      messageType: 'geometry_msgs/msg/Twist'
    })
    topic.publish({
      linear: { x: linear, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: angular }
    })
  }

  private publishTopicsCache: Map<string, ROSLIB.Topic> = new Map()

  publishTopic(topicName: string, messageType: string, message: any): void {
    if (!this.ros) {
      console.error(`[ROS] 发布失败：ros 未连接，拒绝发布到 ${topicName}`)
      return
    }
    // 🔍 [DIAG-STEP3] WebSocket 真实状态诊断
    const ws: WebSocket | undefined = (this.ros as any).socket
    const wsReady = ws?.readyState ?? -1
    const wsLabel = { 0: 'CONNECTING', 1: 'OPEN', 2: 'CLOSING', 3: 'CLOSED' }[wsReady] ?? 'UNKNOWN'
    console.log(
      `%c[ROS-DIAG] publishTopic → ${topicName}`,
      'color: #ff9800; font-weight: bold',
      `| ros.isConnected=${(this.ros as any).isConnected}`,
      `| socket.readyState=${wsReady}(${wsLabel})`,
      `| messageType=${messageType}`,
      '| payload=', JSON.parse(JSON.stringify(message))
    )
    if (wsReady !== 1) {
      console.error(
        `[ROS-DIAG] ❌ WebSocket 状态异常 readyState=${wsReady}(${wsLabel})，消息将无法送达 rosbridge！`
      )
    }

    let topic = this.publishTopicsCache.get(topicName)
    // 关键修复：重连后 this.ros 已被替换为新实例，但缓存里的 Topic 仍持有已关闭的旧 ros 引用，
    // 此时调用 publish() 会静默失败（"WebSocket 已连接但车不动"的典型根因之一）。
    // 所以每次都校验 topic.ros 是否仍是当前 ros，不匹配就重建并重新 advertise。
    if (!topic || (topic as any).ros !== this.ros) {
      console.log(`[ROS-DIAG] ⚠️ 缓存 miss / ros 实例变更，重建 Topic: ${topicName}`)
      topic = new ROSLIB.Topic({
        ros: this.ros,
        name: topicName,
        messageType: messageType,
        queue_size: 10
      } as any)
      this.publishTopicsCache.set(topicName, topic)
      try {
        // ROS 2 rosbridge 下发前先 advertise，确保按正确类型注册发布者，
        // 避免某些底盘驱动"未收到首帧即判定话题不存在"而不订阅。
        ;(topic as any).advertise()
        console.log(`[ROS-DIAG] ✅ advertise 成功: ${topicName}`)
      } catch (e) {
        console.warn(`[ROS-DIAG] ❌ advertise ${topicName} 失败:`, e)
      }
    }
    try {
      topic.publish(message)
      console.log(`[ROS-DIAG] ✅ topic.publish() 已调用: ${topicName}`)
    } catch (e) {
      console.error(`[ROS-DIAG] ❌ topic.publish() 异常: ${topicName}`, e)
    }
  }

  getNumSubscribers(topicName: string, callback: (n: number) => void): void {
    if (!this.ros) { callback(0); return }
    try {
      const probe = new ROSLIB.Topic({
        ros: this.ros,
        name: topicName,
        messageType: 'std_msgs/msg/Int32'
      } as any)
      // 该 roslibjs 构建中 Topic 可能不存在 getNumSubscribers 方法，
      // 直接调用会抛 TypeError 并阻塞调用方。先判断类型，缺失则安全降级为 0。
      const fn = (probe as any).getNumSubscribers
      if (typeof fn === 'function') {
        fn.call(probe, (n: number) => callback(n ?? 0))
      } else {
        console.warn(`[ROS] roslibjs 不支持 getNumSubscribers，已忽略话题 ${topicName} 订阅者探测`)
        callback(0)
      }
    } catch (e) {
      console.warn(`[ROS] 查询 ${topicName} 订阅者数失败:`, e)
      callback(0)
    }
  }

  onConnection(callback: () => void): void {
    this.connectionCallbacks.push(callback)
  }

  onError(callback: (error: any) => void): void {
    this.errorCallbacks.push(callback)
  }

  onClose(callback: () => void): void {
    this.closeCallbacks.push(callback)
  }

  subscribeTopic<T>(topicName: string, messageType: string, callback: (message: T) => void, options?: TopicQosOptions): void {
    if (!this.ros) return
    
    try {
      if (this.topics.has(topicName)) {
        this.topics.get(topicName)!.unsubscribe()
      }

      // 将 QoS 选项透传给 rosbridge，用于订阅 latched 话题（/map、/amcl_pose 等）
      const topicOptions: any = {
        ros: this.ros!,
        name: topicName,
        messageType: messageType,
      }
      if (options) {
        if (options.durability) topicOptions.durability = options.durability
        if (options.reliability) topicOptions.reliability = options.reliability
        if (options.history) topicOptions.history = options.history
        if (options.depth !== undefined) topicOptions.depth = options.depth
      }

      const topic = new ROSLIB.Topic(topicOptions)

      topic.subscribe((message: unknown) => {
        try {
          const msg = message as T
          this.topicInfo.set(topicName, {
            name: topicName,
            type: messageType,
            message: msg,
            lastUpdate: Date.now()
          })
          callback(msg)
        } catch (error) {
          console.error(`[ROS] Error processing message for ${topicName}:`, error)
        }
      })
      
      this.topics.set(topicName, topic)
    } catch (error) {
      console.error(`[ROS] Failed to subscribe to ${topicName}:`, error)
    }
  }

  unsubscribeTopic(topicName: string): void {
    if (this.topics.has(topicName)) {
      this.topics.get(topicName)!.unsubscribe()
      this.topics.delete(topicName)
    }
  }

  getTopics(callback: (topics: TopicInfo[]) => void): void {
    if (!this.ros) return

    this.ros.getTopics((result: any) => {
      const topics: TopicInfo[] = []
      
      if (result.topics && Array.isArray(result.topics)) {
        if (result.types && Array.isArray(result.types)) {
          result.topics.forEach((name: string, index: number) => {
            const existing = this.topicInfo.get(name)
            topics.push({
              name,
              type: result.types[index] || 'unknown',
              message: existing?.message || null,
              lastUpdate: existing?.lastUpdate || 0
            })
          })
        } else if (result.topics[0] && typeof result.topics[0] === 'object') {
          result.topics.forEach((topic: any) => {
            const name = topic.name || topic.topic
            const type = topic.type || 'unknown'
            const existing = this.topicInfo.get(name)
            topics.push({
              name,
              type,
              message: existing?.message || null,
              lastUpdate: existing?.lastUpdate || 0
            })
          })
        } else {
          result.topics.forEach((name: string) => {
            const existing = this.topicInfo.get(name)
            topics.push({
              name,
              type: 'unknown',
              message: existing?.message || null,
              lastUpdate: existing?.lastUpdate || 0
            })
          })
        }
      }

      console.log('[ROS] Topics via roslib:', topics)
      
      if (topics.length === 0) {
        this.fetchTopicsViaService(callback)
      } else {
        callback(topics)
      }
    })
  }

  private fetchTopicsViaService(callback: (topics: TopicInfo[]) => void): void {
    try {
      const service = new ROSLIB.Service({
        ros: this.ros!,
        name: '/rosapi/topics',
        serviceType: 'rosapi/Topics'
      })
      service.callService({}, (response: any) => {
        console.log('[ROS] Topics via rosapi/topics:', response)
        const topics: TopicInfo[] = []
        if (response.topics && Array.isArray(response.topics)) {
          response.topics.forEach((name: string, index: number) => {
            const existing = this.topicInfo.get(name)
            topics.push({
              name,
              type: response.types?.[index] || 'unknown',
              message: existing?.message || null,
              lastUpdate: existing?.lastUpdate || 0
            })
          })
        }
        console.log('[ROS] Topics parsed:', topics)
        callback(topics)
      }, (error: any) => {
        console.error('[ROS] rosapi/topics failed:', error)
        callback([])
      })
    } catch (error) {
      console.error('[ROS] fetchTopicsViaService error:', error)
      callback([])
    }
  }

  subscribeAllTopics(callback: (topic: TopicInfo) => void): void {
    this.allTopicsCallback = callback

    this.getTopics((topics) => {
      topics.forEach((topic) => {
        this.subscribeTopic(topic.name, topic.type, (message: any) => {
          const info: TopicInfo = {
            name: topic.name,
            type: topic.type,
            message,
            lastUpdate: Date.now()
          }
          this.topicInfo.set(topic.name, info)
          if (this.allTopicsCallback) {
            this.allTopicsCallback(info)
          }
        })
      })
    })
  }

  unsubscribeAllTopics(): void {
    this.topics.forEach((topic) => {
      topic.unsubscribe()
    })
    this.topics.clear()
    this.allTopicsCallback = null
  }
}

class MockRosApi implements RosApi {
  private connectionCallbacks: (() => void)[] = []
  private errorCallbacks: ((error: any) => void)[] = []
  private closeCallbacks: (() => void)[] = []

  async connectRobot(_ip: string, _port: string): Promise<boolean> {
    console.log('[ROS Mock] Connecting to', _ip, ':', _port)
    return new Promise((resolve) => setTimeout(() => {
      this.connectionCallbacks.forEach(cb => cb())
      resolve(true)
    }, 1000))
  }

  disconnectRobot(): void {
    console.log('[ROS Mock] Disconnected')
    this.closeCallbacks.forEach(cb => cb())
  }

  startMapping(): void {
    console.log('[ROS Mock] Mapping started')
  }

  saveMap(name: string): void {
    console.log('[ROS Mock] Map saved:', name)
  }

  startLocalization(): void {
    console.log('[ROS Mock] Localization started')
  }

  startNavigation(): void {
    console.log('[ROS Mock] Navigation started')
  }

  pauseNavigation(): void {
    console.log('[ROS Mock] Navigation paused')
  }

  resumeNavigation(): void {
    console.log('[ROS Mock] Navigation resumed')
  }

  cancelNavigation(): void {
    console.log('[ROS Mock] Navigation cancelled')
  }

  sendVelocity(linear: number, angular: number): void {
    console.log('[ROS Mock] Velocity:', linear, angular)
  }

  publishTopic(topicName: string, messageType: string, message: any): void {
    console.log('[ROS Mock] Publishing to:', topicName, messageType, message)
  }

  onConnection(callback: () => void): void {
    this.connectionCallbacks.push(callback)
  }

  onError(callback: (error: any) => void): void {
    this.errorCallbacks.push(callback)
  }

  onClose(callback: () => void): void {
    this.closeCallbacks.push(callback)
  }

  subscribeTopic<T>(topicName: string, messageType: string, callback: (message: T) => void, _options?: TopicQosOptions): void {
    console.log('[ROS Mock] Subscribing to:', topicName, messageType)
  }

  unsubscribeTopic(topicName: string): void {
    console.log('[ROS Mock] Unsubscribing from:', topicName)
  }

  getTopics(callback: (topics: TopicInfo[]) => void): void {
    callback([
      { name: '/turtle1/pose', type: 'turtlesim/msg/Pose', message: null, lastUpdate: 0 },
      { name: '/cmd_vel', type: 'geometry_msgs/msg/Twist', message: null, lastUpdate: 0 },
      { name: '/rosout', type: 'rcl_interfaces/msg/Log', message: null, lastUpdate: 0 },
      { name: '/parameter_events', type: 'rcl_interfaces/msg/ParameterEvent', message: null, lastUpdate: 0 }
    ])
  }

  subscribeAllTopics(callback: (topic: TopicInfo) => void): void {
    console.log('[ROS Mock] Subscribing to all topics')
  }

  unsubscribeAllTopics(): void {
    console.log('[ROS Mock] Unsubscribing from all topics')
  }

  getNumSubscribers(_topicName: string, callback: (n: number) => void): void {
    callback(1)
  }
}

export const rosApi: RosApi = new RealRosApi()
export const mockRosApi: RosApi = new MockRosApi()