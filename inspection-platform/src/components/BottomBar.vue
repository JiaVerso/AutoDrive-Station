<template>
  <footer class="bottom-bar">
    <div class="bar-left">
      <span class="bar-item">
        <span class="label">FPS</span>
        <span class="value">{{ fps }}</span>
      </span>
      <span class="bar-item">
        <span class="label">ROS</span>
        <span class="value" :class="{ online: robotStore.status.connected }">
          {{ robotStore.status.connected ? 'Connected' : 'Disconnected' }}
        </span>
      </span>
      <span class="bar-item">
        <span class="label">WebSocket</span>
        <span class="value" :class="{ online: robotStore.status.connected }">
          {{ robotStore.status.connected ? 'ws://ok' : 'N/A' }}
        </span>
      </span>
    </div>
    <div class="bar-right">
      <span class="bar-item">
        <span class="label">CPU</span>
        <span class="value">{{ cpu }}%</span>
      </span>
      <span class="bar-item">
        <span class="label">Mem</span>
        <span class="value">{{ memory }}%</span>
      </span>
      <span class="bar-item">
        <span class="label">{{ currentTime }}</span>
      </span>
    </div>
  </footer>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRobotStore } from '@/stores/robot'

const robotStore = useRobotStore()
const fps = ref(60)
const cpu = ref(12)
const memory = ref(34)
const currentTime = ref('')

let timeInterval: ReturnType<typeof setInterval>
let fpsInterval: ReturnType<typeof setInterval>

function updateTime() {
  const now = new Date()
  currentTime.value = now.toLocaleTimeString('zh-CN', { hour12: false })
}

onMounted(() => {
  updateTime()
  timeInterval = setInterval(updateTime, 1000)
  fpsInterval = setInterval(() => {
    fps.value = 58 + Math.floor(Math.random() * 4)
    cpu.value = 10 + Math.floor(Math.random() * 8)
    memory.value = 32 + Math.floor(Math.random() * 6)
  }, 2000)
})

onUnmounted(() => {
  clearInterval(timeInterval)
  clearInterval(fpsInterval)
})
</script>

<style lang="scss" scoped>
.bottom-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: $bottom-height;
  padding: 0 16px;
  background: $bg-secondary;
  border-top: 1px solid $border-color;
  font-size: 12px;
}

.bar-left, .bar-right {
  display: flex;
  align-items: center;
  gap: 20px;
}

.bar-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.label {
  color: $text-muted;
}

.value {
  color: $text-secondary;

  &.online {
    color: $accent-green;
  }
}
</style>
