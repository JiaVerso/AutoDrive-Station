<template>
  <div class="data-panel" :class="{ collapsed: !expanded }">
    <div class="panel-toggle" @click="expanded = !expanded">
      <el-icon><ArrowUp v-if="expanded" /><ArrowDown v-else /></el-icon>
      <span>数据面板</span>
    </div>

    <div v-show="expanded" class="panel-body">
      <el-tabs v-model="activeTab" size="small">
        <el-tab-pane label="机器人" name="robot">
          <div class="data-grid">
            <div class="data-cell">
              <span class="data-label">状态</span>
              <span class="data-value" :class="{ online: robotStore.status.connected }">
                {{ robotStore.status.connected ? '在线' : '离线' }}
              </span>
            </div>
            <div class="data-cell">
              <span class="data-label">电池</span>
              <span class="data-value">{{ robotStore.status.battery }}%</span>
            </div>
            <div class="data-cell">
              <span class="data-label">电压</span>
              <span class="data-value">{{ robotStore.status.voltage }}V</span>
            </div>
            <div class="data-cell">
              <span class="data-label">速度</span>
              <span class="data-value">{{ robotStore.status.speed.toFixed(2) }}m/s</span>
            </div>
            <div class="data-cell">
              <span class="data-label">模式</span>
              <span class="data-value">{{ robotStore.status.mode === 'AUTO' ? '自动' : robotStore.status.mode === 'MANUAL' ? '手动' : robotStore.status.mode }}</span>
            </div>
            <div class="data-cell">
              <span class="data-label">位置</span>
              <span class="data-value">({{ robotStore.status.x.toFixed(1) }}, {{ robotStore.status.y.toFixed(1) }})</span>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="地图" name="map">
          <div class="data-grid">
            <div class="data-cell">
              <span class="data-label">名称</span>
              <span class="data-value">{{ mapStore.currentMap.name }}</span>
            </div>
            <div class="data-cell">
              <span class="data-label">尺寸</span>
              <span class="data-value">{{ mapStore.currentMap.width }}x{{ mapStore.currentMap.height }}</span>
            </div>
            <div class="data-cell">
              <span class="data-label">分辨率</span>
              <span class="data-value">{{ mapStore.currentMap.resolution }}m/px</span>
            </div>
            <div class="data-cell">
              <span class="data-label">建图中</span>
              <span class="data-value">{{ mapStore.mapping ? '是' : '否' }}</span>
            </div>
            <div class="data-cell">
              <span class="data-label">缩放</span>
              <span class="data-value">100%</span>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="导航" name="navigation">
          <div class="data-grid">
            <div class="data-cell">
              <span class="data-label">导航中</span>
              <span class="data-value">{{ navStore.navStatus.active ? '是' : '否' }}</span>
            </div>
            <div class="data-cell">
              <span class="data-label">暂停</span>
              <span class="data-value">{{ navStore.navStatus.paused ? '是' : '否' }}</span>
            </div>
            <div class="data-cell">
              <span class="data-label">当前航点</span>
              <span class="data-value">{{ navStore.navStatus.currentWaypointIndex + 1 }}/{{ navStore.waypoints.length }}</span>
            </div>
            <div class="data-cell">
              <span class="data-label">进度</span>
              <span class="data-value">{{ navStore.navStatus.progress }}%</span>
            </div>
            <div class="data-cell">
              <span class="data-label">航点数</span>
              <span class="data-value">{{ navStore.waypoints.length }}</span>
            </div>
            <div class="data-cell">
              <span class="data-label">路线数</span>
              <span class="data-value">{{ navStore.paths.length }}</span>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="任务" name="task">
          <div class="data-grid">
            <div class="data-cell full">
              <span class="data-label">当前任务</span>
              <span class="data-value">{{ currentTask }}</span>
            </div>
            <div class="data-cell full">
              <span class="data-label">状态</span>
              <span class="data-value">{{ taskStatus }}</span>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="ROS话题" name="ros">
          <div class="ros-content">
            <div class="ros-toolbar">
              <el-button type="primary" size="small" @click="refreshTopics" :loading="loading">
                <el-icon><Refresh /></el-icon>
                刷新话题
              </el-button>
              <el-button size="small" @click="subscribeAllTopicsBtn">
                <el-icon><Plus /></el-icon>
                订阅全部
              </el-button>
              <el-button size="small" @click="unsubscribeAllTopicsBtn">
                <el-icon><Minus /></el-icon>
                取消订阅
              </el-button>
            </div>
            <div class="topic-list">
              <div
                v-for="topic in rosTopics"
                :key="topic.name"
                class="topic-item"
                :class="{ subscribed: topic.subscribed }"
                @click="toggleTopic(topic)"
              >
                <span class="topic-indicator">{{ topic.subscribed ? '●' : '○' }}</span>
                <span class="topic-name">{{ topic.name }}</span>
                <span class="topic-type">{{ topic.type }}</span>
                <span class="topic-time" v-if="topic.lastUpdate">{{ formatTime(topic.lastUpdate) }}</span>
              </div>
            </div>
            <div v-if="selectedTopic" class="topic-detail">
              <div class="detail-header">
                <span>{{ selectedTopic.name }}</span>
                <span class="detail-type">{{ selectedTopic.type }}</span>
              </div>
              <pre class="detail-data">{{ formatMessage(selectedTopic.message) }}</pre>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="控制台" name="console">
          <div class="log-list">
            <div
              v-for="(log, idx) in logs"
              :key="idx"
              class="log-item"
              :class="'log-' + log.level"
            >
              <span class="log-time">{{ log.time }}</span>
              <span class="log-level">{{ log.level.toUpperCase() }}</span>
              <span class="log-source">[{{ log.source }}]</span>
              <span class="log-msg">{{ log.message }}</span>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { ArrowUp, ArrowDown, Refresh, Plus, Minus } from '@element-plus/icons-vue'
import { useRobotStore } from '@/stores/robot'
import { useMapStore } from '@/stores/map'
import { useNavigationStore } from '@/stores/navigation'
import { mockLogs } from '@/mock/data'
import { rosApi, type TopicInfo } from '@/api/ros'

const robotStore = useRobotStore()
const mapStore = useMapStore()
const navStore = useNavigationStore()

const expanded = ref(false)
const activeTab = ref('robot')
const logs = ref(mockLogs)
const loading = ref(false)
const rosTopics = ref<TopicInfo[]>([])
const selectedTopic = ref<TopicInfo | null>(null)

const subscribedTopics = ref<Set<string>>(new Set())

const currentTask = computed(() => {
  if (navStore.navStatus.active) return '自动巡检 - ' + (navStore.currentPath?.name || '未知路线')
  if (mapStore.mapping) return 'SLAM建图'
  return '待命'
})

const taskStatus = computed(() => {
  if (navStore.navStatus.active) return navStore.navStatus.paused ? '已暂停' : '执行中'
  if (mapStore.mapping) return '建图中'
  return '空闲'
})

function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

function formatMessage(message: any): string {
  if (!message) return '无数据'
  return JSON.stringify(message, null, 2)
}

async function refreshTopics() {
  loading.value = true
  console.log('[DataPanel] Refreshing topics...')
  rosApi.getTopics((topics) => {
    console.log('[DataPanel] Topics received:', topics)
    topics.forEach((topic) => {
      const existing = rosTopics.value.find(t => t.name === topic.name)
      if (existing) {
        topic.subscribed = subscribedTopics.value.has(topic.name)
        topic.message = existing.message
        topic.lastUpdate = existing.lastUpdate
      } else {
        topic.subscribed = false
      }
    })
    rosTopics.value = [...topics]
    loading.value = false
  })
}

function subscribeAllTopicsBtn() {
  rosApi.subscribeAllTopics((topic) => {
    const existing = rosTopics.value.find(t => t.name === topic.name)
    if (existing) {
      existing.message = topic.message
      existing.lastUpdate = topic.lastUpdate
      existing.subscribed = true
    } else {
      topic.subscribed = true
      rosTopics.value.push(topic)
    }
    subscribedTopics.value.add(topic.name)
  })
}

function unsubscribeAllTopicsBtn() {
  rosApi.unsubscribeAllTopics()
  rosTopics.value.forEach(topic => {
    topic.subscribed = false
    topic.message = null
  })
  subscribedTopics.value.clear()
  selectedTopic.value = null
}

function toggleTopic(topic: TopicInfo) {
  if (topic.subscribed) {
    rosApi.unsubscribeTopic(topic.name)
    topic.subscribed = false
    subscribedTopics.value.delete(topic.name)
    if (selectedTopic.value?.name === topic.name) {
      selectedTopic.value = null
    }
  } else {
    topic.subscribed = true
    subscribedTopics.value.add(topic.name)
    rosApi.subscribeTopic(topic.name, topic.type, (message: any) => {
      topic.message = message
      topic.lastUpdate = Date.now()
      if (selectedTopic.value?.name === topic.name) {
        selectedTopic.value = { ...topic }
      }
    })
  }
  selectedTopic.value = topic
}

watch(() => robotStore.status.connected, (connected) => {
  console.log('[DataPanel] Robot connected changed:', connected)
  if (connected) {
    setTimeout(() => {
      refreshTopics()
    }, 1000)
  } else {
    rosTopics.value = []
    subscribedTopics.value.clear()
    selectedTopic.value = null
  }
})

function handleTopicsRefresh() {
  console.log('[DataPanel] Topics refresh event received')
  if (robotStore.status.connected) {
    refreshTopics()
  }
}

onMounted(() => {
  console.log('[DataPanel] Mounted, connected:', robotStore.status.connected)
  if (robotStore.status.connected) {
    refreshTopics()
  }
  window.addEventListener('ros-topics-refresh', handleTopicsRefresh)
})

onUnmounted(() => {
  unsubscribeAllTopicsBtn()
  window.removeEventListener('ros-topics-refresh', handleTopicsRefresh)
})
</script>

<style lang="scss" scoped>
.data-panel {
  position: fixed;
  bottom: $bottom-height;
  left: 0;
  right: 0;
  background: $bg-secondary;
  border-top: 1px solid $border-color;
  z-index: 50;
  transition: all $transition;

  &.collapsed {
    .panel-body {
      display: none;
    }
  }
}

.panel-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  cursor: pointer;
  color: $text-muted;
  font-size: 12px;
  transition: color $transition;

  &:hover {
    color: $text-primary;
  }
}

.panel-body {
  padding: 0 16px 12px;
  max-height: 250px;
  overflow-y: auto;

  :deep(.el-tabs__header) {
    margin-bottom: 8px;
  }

  :deep(.el-tabs__item) {
    color: $text-muted;
    font-size: 12px;
    height: 30px;
    line-height: 30px;

    &.is-active {
      color: $accent-blue;
    }
  }
}

.data-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 8px;
}

.data-cell {
  padding: 8px 12px;
  background: $bg-card;
  border-radius: 4px;

  &.full {
    grid-column: 1 / -1;
  }
}

.data-label {
  display: block;
  font-size: 11px;
  color: $text-muted;
  margin-bottom: 2px;
}

.data-value {
  font-size: 13px;
  color: $text-primary;
  font-weight: 500;

  &.online {
    color: $accent-green;
  }
}

.ros-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ros-toolbar {
  display: flex;
  gap: 8px;
}

.topic-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 120px;
  overflow-y: auto;
}

.topic-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  background: $bg-card;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: all $transition;

  &:hover {
    background: $bg-hover;
  }

  &.subscribed {
    background: rgba($accent-blue, 0.1);
  }
}

.topic-indicator {
  font-size: 8px;

  &:not(.subscribed) {
    color: $text-muted;
  }
}

.topic-name {
  flex: 1;
  color: $accent-cyan;
  font-family: monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topic-type {
  color: $text-muted;
  font-family: monospace;
  font-size: 10px;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topic-time {
  color: $accent-green;
  font-size: 10px;
  min-width: 60px;
  text-align: right;
}

.topic-detail {
  padding: 8px;
  background: $bg-card;
  border-radius: 4px;
  margin-top: 4px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  font-size: 12px;
  color: $accent-cyan;
  font-family: monospace;
}

.detail-type {
  font-size: 10px;
  color: $text-muted;
}

.detail-data {
  font-family: monospace;
  font-size: 11px;
  color: $text-secondary;
  max-height: 80px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-list {
  max-height: 180px;
  overflow-y: auto;
  font-family: monospace;
  font-size: 12px;
}

.log-item {
  display: flex;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 2px;

  &:hover {
    background: $bg-hover;
  }
}

.log-time {
  color: $text-muted;
  min-width: 60px;
}

.log-level {
  min-width: 44px;
  font-weight: 600;

  .log-info & { color: $accent-blue; }
  .log-warn & { color: $accent-yellow; }
  .log-error & { color: $accent-red; }
  .log-debug & { color: $text-muted; }
}

.log-source {
  color: $accent-cyan;
}

.log-msg {
  color: $text-secondary;
}
</style>