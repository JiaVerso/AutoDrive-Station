import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { rosApi } from '@/api/ros'
import { useRobotStore } from '@/stores/robot'
import type { FollowModeType, DetectionTarget, YoloDetectionsMsg, YoloBBox } from '@/types'

/**
 * 动态解析 Flask API 基础地址
 *
 * 优先级：
 *   1. 环境变量 VITE_FOLLOW_API（显式覆盖）
 *   2. 当前已连接的小车 IP（robotStore.ip，如 192.168.110.155）
 *   3. 浏览器地址栏 hostname（直接通过 IP 访问前端时）
 *   4. localhost（兜底，仅本机调试）
 *
 * 绝不硬编码 IP，确保前端跑在任意开发机上都能正确指向车端 Flask。
 */
function resolveFlaskApiBase(): string {
  const env = import.meta.env.VITE_FOLLOW_API as string | undefined
  if (env) return env.replace(/\/+$/, '')

  const robotIp = useRobotStore().ip?.trim()
  if (robotIp && robotIp !== 'localhost' && robotIp !== '127.0.0.1') {
    return `http://${robotIp}:5000`
  }

  const host = window.location.hostname
  if (host && host !== 'localhost' && host !== '127.0.0.1') {
    return `http://${host}:5000`
  }

  return 'http://localhost:5000'
}

// ===== ROS 话题名称常量 =====
const TOPIC_YOLO_DETECTIONS = '/yolo_detections'
const TOPIC_FOLLOW_ROI = '/follow/roi'
const TOPIC_FOLLOW_LOCK = '/follow/lock'

/**
 * 全局跟随模式状态（单例）
 *
 * 核心流程：
 *   1. Header 点击"一键跟随" → startFollow() → 弹出摄像头画面
 *   2. 用户在画面上框选目标 / 点击 YOLO 绿色标记 → 发送 ROI / lock 指令
 *   3. 选择跟随模式（平行/尾随/环绕） → 发送配置到后端
 *   4. 点击关闭 → stopFollow() → 停止跟随并清理所有状态
 */
const followActive = ref(false)
const followLoading = ref(false)

// ===== 图传画面尺寸（由 img @load 回调写入，用于 Canvas 坐标转换） =====
const streamNaturalWidth = ref(0)
const streamNaturalHeight = ref(0)

// ===== 目标扫描开关 =====
const scanEnabled = ref(false)

// ===== YOLO 检测结果列表 =====
const detections = ref<DetectionTarget[]>([])

// ===== 当前锁定目标 ID（null 表示未锁定） =====
const lockedTargetId = ref<number | null>(null)

// ===== 当前跟随模式 =====
const followMode = ref<FollowModeType>('trace')

// ===== 框选 ROI 状态（像素坐标，相对于画面） =====
const roiBox = ref<{ xMin: number; yMin: number; xMax: number; yMax: number } | null>(null)

// ===== ROS YOLO 订阅是否已激活 =====
let yoloSubscribed = false

export function useFollowMode() {

  // ===== 计算属性 =====
  const isLocked = computed(() => lockedTargetId.value !== null)

  const lockedTarget = computed(() => {
    if (lockedTargetId.value === null) return null
    return detections.value.find(d => d.id === lockedTargetId.value) ?? null
  })

  /** 跟随模式中文标签 */
  const followModeLabel = computed(() => {
    switch (followMode.value) {
      case 'parallel': return '平行跟随'
      case 'trace': return '尾随追踪'
      case 'orbit': return '环绕监视'
    }
  })

  // ================================================================
  //  启动跟随
  // ================================================================
  async function startFollow(): Promise<boolean> {
    followLoading.value = true
    try {
      const res = await fetch(`${resolveFlaskApiBase()}/api/follow/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      const data = await res.json()

      if (data.ok) {
        followActive.value = true
        ElMessage.success(data.detail || '跟随模式已启动，请在画面上框选或点击目标')
        // 启动后自动开启目标扫描
        enableScan(true)
        return true
      } else {
        ElMessage.error(data.detail || '启动跟随失败')
        return false
      }
    } catch (err) {
      console.error('[FollowMode] 启动跟随请求失败:', err)
      ElMessage.error('无法连接后端服务，请确认 Flask 服务已启动 (端口 5000)')
      return false
    } finally {
      followLoading.value = false
    }
  }

  // ================================================================
  //  停止跟随（清理所有状态）
  // ================================================================
  async function stopFollow(): Promise<void> {
    try {
      await fetch(`${resolveFlaskApiBase()}/api/follow/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
    } catch (err) {
      console.warn('[FollowMode] 停止跟随请求失败（后端可能已关闭）:', err)
    } finally {
      // 无论后端是否成功，前端都清理状态
      followActive.value = false
      followLoading.value = false
      scanEnabled.value = false
      detections.value = []
      lockedTargetId.value = null
      followMode.value = 'trace'
      roiBox.value = null
      streamNaturalWidth.value = 0
      streamNaturalHeight.value = 0
      unsubscribeYolo()
    }
  }

  // ================================================================
  //  目标扫描：订阅 /yolo_detections 话题
  // ================================================================
  function enableScan(enabled: boolean) {
    scanEnabled.value = enabled
    if (enabled) {
      subscribeYolo()
    } else {
      detections.value = []
      unsubscribeYolo()
    }
  }

  function subscribeYolo() {
    if (yoloSubscribed) return
    yoloSubscribed = true

    // 订阅 std_msgs/String（JSON payload），兼容模拟器和真实 YOLO 节点
    rosApi.subscribeTopic<{ data: string }>(
      TOPIC_YOLO_DETECTIONS,
      'std_msgs/msg/String',
      (msg) => {
        if (!msg || !msg.data) {
          detections.value = []
          return
        }
        try {
          const payload: YoloDetectionsMsg = JSON.parse(msg.data)
          if (!payload.detections || payload.detections.length === 0) {
            detections.value = []
            return
          }
          const result: DetectionTarget[] = []
          const len = payload.detections.length
          for (let i = 0; i < len; i++) {
            const box: YoloBBox = payload.detections[i]
            const conf = payload.confidences?.[i] ?? 0
            const clsId = payload.class_ids?.[i] ?? 0
            const clsName = payload.class_names?.[i] ?? `class_${clsId}`
            if (conf < 0.35) continue
            result.push({
              id: i,
              cx: (box.x_min + box.x_max) / 2,
              cy: (box.y_min + box.y_max) / 2,
              bbox: box,
              confidence: conf,
              classId: clsId,
              className: clsName,
            })
          }
          detections.value = result
        } catch (e) {
          console.warn('[FollowMode] YOLO 消息解析失败:', e)
        }
      }
    )
  }

  function unsubscribeYolo() {
    if (!yoloSubscribed) return
    yoloSubscribed = false
    rosApi.unsubscribeTopic(TOPIC_YOLO_DETECTIONS)
  }

  // ================================================================
  //  框选 ROI → 发送到后端
  // ================================================================
  function sendRoi(roi: { xMin: number; yMin: number; xMax: number; yMax: number }) {
    roiBox.value = roi
    // 发布到 ROS 话题（像素坐标 + 图像尺寸）
    rosApi.publishTopic(TOPIC_FOLLOW_ROI, 'sensor_msgs/msg/RegionOfInterest', {
      x_offset: Math.round(roi.xMin),
      y_offset: Math.round(roi.yMin),
      width: Math.round(roi.xMax - roi.xMin),
      height: Math.round(roi.yMax - roi.yMin),
      do_rectify: false,
    })
    // 同时通过 REST API 发送（供非 ROS 后端消费）
    fetch(`${resolveFlaskApiBase()}/api/follow/roi`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        x_min: roi.xMin,
        y_min: roi.yMin,
        x_max: roi.xMax,
        y_max: roi.yMax,
        image_width: streamNaturalWidth.value,
        image_height: streamNaturalHeight.value,
      }),
    }).catch(err => console.warn('[FollowMode] ROI 请求发送失败:', err))

    ElMessage.success('目标区域已发送')
  }

  // ================================================================
  //  锁定目标 → 发送到后端
  // ================================================================
  function lockTarget(target: DetectionTarget) {
    lockedTargetId.value = target.id
    // 发布到 ROS 话题
    rosApi.publishTopic(TOPIC_FOLLOW_LOCK, 'std_msgs/msg/Int32MultiArray', {
      data: [target.classId, target.id, Math.round(target.bbox.x_min), Math.round(target.bbox.y_min), Math.round(target.bbox.x_max), Math.round(target.bbox.y_max)],
    })
    // 同时通过 REST API 发送
    fetch(`${resolveFlaskApiBase()}/api/follow/lock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_id: target.id,
        class_id: target.classId,
        class_name: target.className,
        bbox: target.bbox,
        confidence: target.confidence,
      }),
    }).catch(err => console.warn('[FollowMode] 锁定请求发送失败:', err))

    ElMessage.success(`已锁定目标: ${target.className} (${Math.round(target.confidence * 100)}%)`)
  }

  /** 解除锁定 */
  function unlockTarget() {
    lockedTargetId.value = null
    rosApi.publishTopic(TOPIC_FOLLOW_LOCK, 'std_msgs/msg/Int32MultiArray', {
      data: [-1, -1, 0, 0, 0, 0],
    })
    ElMessage.info('目标锁定已解除')
  }

  // ================================================================
  //  切换跟随模式 → 发送到后端
  // ================================================================
  async function setFollowMode(mode: FollowModeType) {
    followMode.value = mode
    // 发送到 REST API
    try {
      await fetch(`${resolveFlaskApiBase()}/api/follow/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      })
    } catch (err) {
      console.warn('[FollowMode] 模式切换请求失败:', err)
    }
    const label = { parallel: '平行跟随', trace: '尾随追踪', orbit: '环绕监视' }[mode]
    ElMessage.info(`跟随模式: ${label}`)
  }

  // ================================================================
  //  图片尺寸更新（由 FollowCameraPopup img @load 触发）
  // ================================================================
  function updateStreamSize(w: number, h: number) {
    streamNaturalWidth.value = w
    streamNaturalHeight.value = h
  }

  function setFollowLoading(v: boolean) {
    followLoading.value = v
  }

  return {
    // 基础状态
    followActive,
    followLoading,
    // 图传尺寸
    streamNaturalWidth,
    streamNaturalHeight,
    // 目标扫描
    scanEnabled,
    detections,
    // 锁定
    lockedTargetId,
    lockedTarget,
    isLocked,
    // 跟随模式
    followMode,
    followModeLabel,
    // 框选 ROI
    roiBox,
    // 方法
    startFollow,
    stopFollow,
    enableScan,
    sendRoi,
    lockTarget,
    unlockTarget,
    setFollowMode,
    updateStreamSize,
    setFollowLoading,
  }
}
