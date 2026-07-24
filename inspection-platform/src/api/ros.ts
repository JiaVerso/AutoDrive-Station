import * as ROSLIB from 'roslib'

export interface TopicInfo {
  name: string
  type: string
  message: any
  lastUpdate: number
  subscribed?: boolean
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
  subscribeTopic: <T>(topicName: string, messageType: string, callback: (message: T) => void) => void
  unsubscribeTopic: (topicName: string) => void
  getTopics: (callback: (topics: TopicInfo[]) => void) => void
  subscribeAllTopics: (callback: (topic: TopicInfo) => void) => void
  unsubscribeAllTopics: () => void
}

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
      this.ros = new ROSLIB.Ros({ url })

      this.ros.on('connection', () => {
        console.log('[ROS] Connected to', url)
        this.connectionCallbacks.forEach(cb => cb())
        resolve(true)
      })

      this.ros.on('error', (error: any) => {
        console.error('[ROS] Connection error:', error)
        this.errorCallbacks.forEach(cb => cb(error))
        resolve(false)
      })

      this.ros.on('close', () => {
        console.log('[ROS] Connection closed')
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
    let topic = this.publishTopicsCache.get(topicName)
    if (!topic) {
      topic = new ROSLIB.Topic({
        ros: this.ros!,
        name: topicName,
        messageType: messageType
      })
      this.publishTopicsCache.set(topicName, topic)
    }
    topic.publish(message)
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

  subscribeTopic<T>(topicName: string, messageType: string, callback: (message: T) => void): void {
    if (!this.ros) return
    
    try {
      if (this.topics.has(topicName)) {
        this.topics.get(topicName)!.unsubscribe()
      }

      const topic = new ROSLIB.Topic({
        ros: this.ros!,
        name: topicName,
        messageType: messageType
      })

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

  subscribeTopic<T>(topicName: string, messageType: string, callback: (message: T) => void): void {
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
}

export const rosApi: RosApi = new RealRosApi()
export const mockRosApi: RosApi = new MockRosApi()