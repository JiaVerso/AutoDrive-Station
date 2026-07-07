<template>
  <header class="app-header">
    <div class="header-left">
      <div class="logo">
        <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" />
          <path d="M8 12h8M12 8v8" />
        </svg>
        <span class="logo-text">智能巡检平台</span>
      </div>
    </div>

    <div class="header-center">
      <div class="connection-group">
        <el-input
          v-model="robotStore.ip"
          placeholder="IP"
          size="small"
          class="ip-input"
          :disabled="robotStore.status.connected"
        />
        <el-input
          v-model="robotStore.port"
          placeholder="Port"
          size="small"
          class="port-input"
          :disabled="robotStore.status.connected"
        />
        <el-button
          v-if="!robotStore.status.connected"
          type="primary"
          size="small"
          :loading="robotStore.connecting"
          @click="robotStore.connect()"
        >
          开始连接
        </el-button>
        <el-button
          v-else
          type="danger"
          size="small"
          @click="robotStore.disconnect()"
        >
          断开连接
        </el-button>
        <el-button size="small" @click="handleReconnect">重连</el-button>
      </div>

      <div class="status-badges">
        <span class="badge" :class="{ online: robotStore.status.connected }">
          <span class="dot" />
          {{ robotStore.status.connected ? '在线' : '离线' }}
        </span>
      </div>
    </div>

    <div class="header-right">
      <div class="robot-info">
        <span class="info-item">
          <el-icon><Monitor /></el-icon>
          电池 {{ robotStore.status.battery }}%
        </span>
        <span class="info-item">
          <el-icon><Lightning /></el-icon>
          {{ robotStore.status.voltage }}V
        </span>
        <span class="info-item">
          <el-icon><Odometer /></el-icon>
          {{ robotStore.status.speed.toFixed(1) }}m/s
        </span>
        <span class="info-item mode" :class="modeClass">
          {{ robotStore.status.mode }}
        </span>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Monitor, Lightning, Odometer } from '@element-plus/icons-vue'
import { useRobotStore } from '@/stores/robot'

const robotStore = useRobotStore()

const modeClass = computed(() => ({
  'mode-auto': robotStore.status.mode === 'AUTO',
  'mode-manual': robotStore.status.mode === 'MANUAL',
}))

function handleReconnect() {
  robotStore.disconnect()
  setTimeout(() => robotStore.connect(), 500)
}
</script>

<style lang="scss" scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: $header-height;
  padding: 0 16px;
  background: $bg-secondary;
  border-bottom: 1px solid $border-color;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  color: $accent-cyan;
}

.logo-text {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 1px;
}

.header-center {
  display: flex;
  align-items: center;
  gap: 20px;
}

.connection-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ip-input {
  width: 140px;
}

.port-input {
  width: 80px;
}

.status-badges {
  display: flex;
  gap: 8px;
}

.badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  background: $bg-card;
  color: $text-muted;
  transition: all $transition;

  &.online {
    color: $accent-green;
    background: rgba($accent-green, 0.1);
  }
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: $text-muted;
  transition: all $transition;

  .online & {
    background: $accent-green;
    box-shadow: 0 0 6px $accent-green;
  }
}

.header-right {
  display: flex;
  align-items: center;
}

.robot-info {
  display: flex;
  align-items: center;
  gap: 16px;
}

.info-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: $text-secondary;

  .el-icon {
    font-size: 14px;
  }
}

.mode {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.mode-auto {
  background: rgba($accent-blue, 0.15);
  color: $accent-blue;
}

.mode-manual {
  background: rgba($accent-yellow, 0.15);
  color: $accent-yellow;
}
</style>
