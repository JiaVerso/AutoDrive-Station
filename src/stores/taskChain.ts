import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import type { TaskNode, TaskNodeType, TaskChainStatus } from '@/types'
import { rosApi } from '@/api/ros'
import { useRobotStore } from '@/stores/robot'

function defaultParams(type: TaskNodeType): Record<string, any> {
  switch (type) {
    case 'nav':
      // pathType: single(单点) / linear(直线多点) / square(四边形) / loop(环形循环)
      return { pathType: 'single', x: 0, y: 0, yaw: 0, waypoints: [{ x: 0, y: 0, yaw: 0 }] }
    case 'wait':
      return { duration: 5 }
    case 'robot':
      return { mode: 'patrol', max_speed: 0.5 }
    case 'charge':
      return {}
    default:
      return {}
  }
}

// 根据路径类型自动生成默认航点（用于 square/loop/linear 初始化）
function autoWaypoints(pathType: string): { x: number; y: number; yaw: number }[] {
  switch (pathType) {
    case 'square':
      return [
        { x: 1.0, y: 2.0, yaw: 0.0 },
        { x: 5.0, y: 2.0, yaw: 1.57 },
        { x: 5.0, y: 6.0, yaw: 3.14 },
        { x: 1.0, y: 6.0, yaw: -1.57 },
      ]
    case 'loop':
      return [
        { x: 0.0, y: 0.0, yaw: 0.0 },
        { x: 4.0, y: 0.0, yaw: 1.57 },
        { x: 4.0, y: 4.0, yaw: 3.14 },
        { x: 0.0, y: 4.0, yaw: -1.57 },
      ]
    case 'linear':
      return [
        { x: 0.0, y: 0.0, yaw: 0.0 },
        { x: 4.0, y: 0.0, yaw: 0.0 },
      ]
    default:
      return [{ x: 0, y: 0, yaw: 0 }]
  }
}

export type NavPathType = 'single' | 'linear' | 'square' | 'loop'

let nodeSeq = 0
function genId(): string {
  nodeSeq += 1
  return 'tn_' + Date.now().toString(36) + '_' + nodeSeq
}

export const useTaskChainStore = defineStore('taskChain', () => {
  const robotStore = useRobotStore()

  const nodes = ref<TaskNode[]>([])
  const status = ref<TaskChainStatus>('idle')
  const currentStep = ref(0) // 1-based index of the executing node; 0 = none
  const logs = ref<string[]>([])
  const savedChains = ref<{ id: string; name: string; nodes: TaskNode[] }[]>([])

  const total = computed(() => nodes.value.length)
  const isRunning = computed(() => status.value === 'running')
  const isPaused = computed(() => status.value === 'paused')
  // 暂停/恢复按钮可见性：运行中可暂停，已暂停可恢复
  const canPause = computed(() => status.value === 'running')
  const canResume = computed(() => status.value === 'paused')
  const statusText = computed(() => {
    switch (status.value) {
      case 'idle':
        return nodes.value.length === 0 ? '未开始（空链条）' : '未开始'
      case 'running':
        return `执行中：第 ${currentStep.value}/${total.value} 步`
      case 'paused':
        return '已暂停'
      case 'completed':
        return '已完成'
      case 'error':
        return '执行出错'
      default:
        return '未知'
    }
  })

  let statusTopicSubscribed = false

  function addLog(text: string) {
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    logs.value.unshift(`[${time}] ${text}`)
    if (logs.value.length > 200) logs.value.splice(200)
  }

  function addNode(type: TaskNodeType, atIndex?: number) {
    const node: TaskNode = {
      id: genId(),
      type,
      params: defaultParams(type),
      expanded: true,
    }
    const arr = [...nodes.value]
    if (atIndex === undefined || atIndex < 0 || atIndex > arr.length) {
      arr.push(node)
    } else {
      arr.splice(atIndex, 0, node)
    }
    nodes.value = arr
  }

  function removeNode(id: string) {
    nodes.value = nodes.value.filter((n) => n.id !== id)
    if (currentStep.value > nodes.value.length) currentStep.value = nodes.value.length
  }

  function moveNode(from: number, to: number) {
    const arr = [...nodes.value]
    if (from < 0 || from >= arr.length) return
    if (to < 0 || to > arr.length) return
    const [item] = arr.splice(from, 1)
    let insertAt = to
    if (to > from) insertAt = to - 1
    insertAt = Math.max(0, Math.min(insertAt, arr.length))
    arr.splice(insertAt, 0, item)
    nodes.value = arr
  }

  function moveUp(id: string) {
    const idx = nodes.value.findIndex((n) => n.id === id)
    if (idx > 0) moveNode(idx, idx - 1)
  }

  function moveDown(id: string) {
    const idx = nodes.value.findIndex((n) => n.id === id)
    if (idx >= 0 && idx < nodes.value.length - 1) moveNode(idx, idx + 1)
  }

  function updateParam(id: string, key: string, value: any) {
    const node = nodes.value.find((n) => n.id === id)
    if (node) node.params[key] = value
  }

  // 切换导航节点的路径类型：切换时自动重建航点列表（保留 single 时的 x/y/yaw）
  function setNavPathType(id: string, pathType: NavPathType) {
    const node = nodes.value.find((n) => n.id === id)
    if (!node) return
    node.params.pathType = pathType
    if (pathType === 'single') {
      // 单点模式：用航点列表第一个点回填 x/y/yaw，保证原逻辑兼容
      const wp = Array.isArray(node.params.waypoints) && node.params.waypoints[0]
      if (wp) {
        node.params.x = wp.x
        node.params.y = wp.y
        node.params.yaw = wp.yaw
      }
      node.params.waypoints = [{ x: node.params.x ?? 0, y: node.params.y ?? 0, yaw: node.params.yaw ?? 0 }]
    } else {
      node.params.waypoints = autoWaypoints(pathType).map((w) => ({ ...w }))
    }
  }

  function addWaypoint(id: string) {
    const node = nodes.value.find((n) => n.id === id)
    if (!node) return
    if (!Array.isArray(node.params.waypoints)) node.params.waypoints = []
    node.params.waypoints.push({ x: 0, y: 0, yaw: 0 })
  }

  function removeWaypoint(id: string, index: number) {
    const node = nodes.value.find((n) => n.id === id)
    if (!node || !Array.isArray(node.params.waypoints)) return
    if (node.params.waypoints.length <= 1) return // 至少保留一个点
    node.params.waypoints.splice(index, 1)
  }

  function toggleExpand(id: string) {
    const node = nodes.value.find((n) => n.id === id)
    if (node) node.expanded = !node.expanded
  }

  function clearChain() {
    nodes.value = []
    currentStep.value = 0
  }

  function buildPayload() {
    return nodes.value.map((n) => ({ type: n.type, params: { ...n.params } }))
  }

  function startChain() {
    if (nodes.value.length === 0) {
      ElMessage.warning('任务链为空，请先从左侧拖入节点')
      return
    }
    if (!robotStore.status.connected) {
      ElMessage.warning('请先连接 ROS Bridge 后再下发任务链')
      return
    }
    ensureStatusSubscription()
    const payload = buildPayload()
    rosApi.publishTopic('/task_chain/command', 'std_msgs/msg/String', {
      data: JSON.stringify(payload),
    })
    status.value = 'running'
    currentStep.value = 0
    addLog(`已下发任务链（${nodes.value.length} 步）到 /task_chain/command`)
  }

  function stopChain() {
    if (!robotStore.status.connected) {
      ElMessage.warning('未连接到 ROS Bridge')
      return
    }
    ensureStatusSubscription()
    rosApi.publishTopic('/task_chain/command', 'std_msgs/msg/String', {
      data: JSON.stringify({ cmd: 'stop' }),
    })
    addLog('已发送紧急终止指令到 /task_chain/command')
  }

  function pauseChain() {
    if (!robotStore.status.connected) {
      ElMessage.warning('未连接到 ROS Bridge')
      return
    }
    ensureStatusSubscription()
    rosApi.publishTopic('/task_chain/command', 'std_msgs/msg/String', {
      data: JSON.stringify({ cmd: 'pause' }),
    })
    addLog('已发送暂停指令到 /task_chain/command')
  }

  function resumeChain() {
    if (!robotStore.status.connected) {
      ElMessage.warning('未连接到 ROS Bridge')
      return
    }
    ensureStatusSubscription()
    rosApi.publishTopic('/task_chain/command', 'std_msgs/msg/String', {
      data: JSON.stringify({ cmd: 'resume' }),
    })
    addLog('已发送恢复指令到 /task_chain/command')
  }

  function ensureStatusSubscription() {
    if (statusTopicSubscribed) return
    statusTopicSubscribed = true
    rosApi.subscribeTopic('/task_chain/status', 'std_msgs/msg/String', (msg: any) => {
      if (!msg || !msg.data) return
      try {
        const p = JSON.parse(msg.data)
        const s = p.status
        // note 提示（如“拍照成功”）单独落日志，避免被 executing 覆盖丢失
        if (p.note) {
          const stepTag = p.current_step
            ? `[第 ${p.current_step}/${p.total || total.value} 步提示]`
            : '[提示]'
          addLog(`${stepTag} ${p.note}`)
        }
        if (s === 'executing') {
          status.value = 'running'
          currentStep.value = p.current_step || 0
        } else if (s === 'running') {
          status.value = 'running'
        } else if (s === 'paused') {
          status.value = 'paused'
        } else if (s === 'completed') {
          status.value = 'completed'
          currentStep.value = p.total || nodes.value.length
          addLog('任务链执行完成 ✅')
        } else if (s === 'stopped' || s === 'idle') {
          status.value = 'idle'
          currentStep.value = 0
          if (s === 'stopped') addLog('任务链已终止')
        } else if (s === 'error') {
          status.value = 'error'
          addLog('任务链执行出错：' + (p.reason || '未知错误'))
        }
      } catch {
        /* ignore malformed */
      }
    })
  }

  // ===== 本地持久化：保存 / 加载任务链 =====
  function loadSavedChains() {
    try {
      const raw = localStorage.getItem('task_chain_saved')
      if (raw) savedChains.value = JSON.parse(raw)
    } catch {
      savedChains.value = []
    }
  }

  function persistSavedChains() {
    try {
      localStorage.setItem('task_chain_saved', JSON.stringify(savedChains.value))
    } catch {
      /* ignore */
    }
  }

  function saveChain(name: string) {
    if (!name.trim()) {
      ElMessage.warning('请输入任务链名称')
      return
    }
    if (nodes.value.length === 0) {
      ElMessage.warning('当前任务链为空，无法保存')
      return
    }
    const entry = {
      id: 'tc_' + Date.now().toString(36),
      name: name.trim(),
      nodes: nodes.value.map((n) => ({ ...n, expanded: false })),
    }
    savedChains.value.push(entry)
    persistSavedChains()
    ElMessage.success(`任务链「${entry.name}」已保存`)
    addLog(`已保存任务链「${entry.name}」(${entry.nodes.length} 步)`)
  }

  function loadChain(id: string) {
    const entry = savedChains.value.find((c) => c.id === id)
    if (!entry) return
    nodes.value = entry.nodes.map((n) => ({ ...n, params: { ...n.params }, expanded: true }))
    currentStep.value = 0
    status.value = 'idle'
    addLog(`已加载任务链「${entry.name}」`)
  }

  function deleteChain(id: string) {
    savedChains.value = savedChains.value.filter((c) => c.id !== id)
    persistSavedChains()
  }

  function resetData() {
    nodes.value = []
    status.value = 'idle'
    currentStep.value = 0
    logs.value = []
  }

  return {
    nodes,
    status,
    currentStep,
    logs,
    savedChains,
    total,
    isRunning,
    isPaused,
    canPause,
    canResume,
    statusText,
    addNode,
    removeNode,
    moveNode,
    moveUp,
    moveDown,
    updateParam,
    setNavPathType,
    addWaypoint,
    removeWaypoint,
    toggleExpand,
    clearChain,
    startChain,
    stopChain,
    pauseChain,
    resumeChain,
    subscribeStatus: ensureStatusSubscription,
    loadSavedChains,
    saveChain,
    loadChain,
    deleteChain,
    addLog,
    resetData,
  }
})
