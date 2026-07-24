<template>
  <header class="app-header">
    <div class="header-left">
      <div class="logo">
        <img src="@/assets/logo.png" alt="AutoDrive-Station" class="system-logo" />
        <span class="logo-text">
          <span class="logo-text-main">AutoDrive</span><span class="logo-text-accent">-Station</span>
        </span>
      </div>

      <div class="robot-info">
        <span class="info-item">
          <el-icon><Monitor /></el-icon>
          <span class="info-text">电池 {{ robotStore.status.battery }}%</span>
        </span>
        <span class="info-item">
          <el-icon><Lightning /></el-icon>
          <span class="info-text">{{ robotStore.status.voltage }}V</span>
        </span>
        <span class="info-item">
          <el-icon><Odometer /></el-icon>
          <span class="info-text">{{ robotStore.status.speed.toFixed(1) }}m/s</span>
        </span>
        <span class="info-item latency" :class="latencyClass">
          <el-icon><Timer /></el-icon>
          <span class="info-text">
            {{ robotStore.status.latency >= 0 ? robotStore.status.latency + 'ms' : '超时' }}
          </span>
        </span>
        <span class="info-item nav" :class="navClass">
          <el-icon><Position /></el-icon>
          <span class="info-text">{{ navLabel }}</span>
        </span>
        <span class="info-item mode" :class="modeClass">
          {{ robotStore.status.mode }}
        </span>
      </div>
    </div>

    <div class="header-right">
      <div class="inspect-actions">
        <button
          v-if="navStore.isSaved || navStore.isPausedState"
          class="inspect-btn start"
          @click="navStore.onStartInspection()"
        >开始巡检</button>
        <button
          v-if="navStore.isRunning"
          class="inspect-btn pause"
          @click="navStore.onPauseInspection()"
        >暂停巡检</button>
      </div>

      <button
        class="follow-btn"
        :class="{ active: followActive, loading: followLoading }"
        :disabled="followLoading"
        :title="followActive ? '停止智能跟随' : '智能跟随'"
        @click="handleFollow"
      >
        <el-icon v-if="followLoading" class="spin"><Loading /></el-icon>
        <el-icon v-else><VideoPlay /></el-icon>
        <span>{{ followLoading ? '启动中...' : followActive ? '停止跟随' : '智能跟随' }}</span>
      </button>

      <button
        class="theme-toggle"
        :title="isDark ? '切换为亮色主题' : '切换为暗色主题'"
        @click="toggleTheme"
      >
        <el-icon v-if="isDark"><Sunny /></el-icon>
        <el-icon v-else><Moon /></el-icon>
      </button>

      <div class="connection-group">
        <el-button
          v-if="!robotStore.status.connected"
          type="primary"
          size="small"
          :loading="robotStore.connecting"
          @click="openConnectDialog"
        >
          连接
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
        <span class="badge" :class="{ online: robotStore.status.connected }">
          <span class="dot" />
          {{ robotStore.status.connected ? '在线' : '离线' }}
        </span>
      </div>
    </div>

    <!-- 机器人连接配置弹窗 -->
    <el-dialog
      v-model="connectDialogVisible"
      title="机器人连接配置"
      width="420px"
      align-center
      append-to-body
      class="connect-dialog"
    >
      <div class="connect-form">
        <div class="connect-field">
          <label>IP 地址</label>
          <el-input
            v-model="dialogIp"
            placeholder="localhost"
            size="default"
            @keyup.enter="confirmConnect"
          />
        </div>
        <div class="connect-field">
          <label>端口</label>
          <el-input
            v-model="dialogPort"
            placeholder="9090"
            size="default"
            @keyup.enter="confirmConnect"
          />
        </div>
      </div>
      <template #footer>
        <el-button size="default" @click="connectDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          size="default"
          :loading="robotStore.connecting"
          @click="confirmConnect"
        >
          开始连接
        </el-button>
      </template>
    </el-dialog>
  </header>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { computed } from 'vue'
import { Monitor, Lightning, Odometer, Timer, Position, Sunny, Moon, VideoPlay, Loading } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import { useRobotStore } from '@/stores/robot'
import { useNavigationStore } from '@/stores/navigation'
import { useTheme } from '@/composables/useTheme'
import { useFollowMode } from '@/composables/useFollowMode'

const robotStore = useRobotStore()
const navStore = useNavigationStore()
const { isDark, toggleTheme } = useTheme()
const { followActive, followLoading, startFollow, stopFollow, setFollowLoading } = useFollowMode()

// ===== 连接配置弹窗（隐藏顶部平铺表单，改为弹窗交互） =====
const connectDialogVisible = ref(false)
const dialogIp = ref('localhost')
const dialogPort = ref('9090')

function openConnectDialog() {
  // 预填当前已保存的地址（首次为默认值 localhost / 9090）
  dialogIp.value = robotStore.ip || 'localhost'
  dialogPort.value = robotStore.port || '9090'
  connectDialogVisible.value = true
}

function confirmConnect() {
  // 写回 store 后发起后端连接（逻辑保持不变）
  robotStore.ip = dialogIp.value?.trim() || 'localhost'
  robotStore.port = dialogPort.value?.trim() || '9090'
  connectDialogVisible.value = false

  // 记录发起时刻，用于在超时未连上时给出明确失败提示
  const startAt = Date.now()
  robotStore.connect()

  // 非侵入式失败检测：若 6s 内既未 connected 也非 connecting 中，则弹窗告警
  window.setTimeout(() => {
    if (!robotStore.status.connected && !robotStore.connecting) {
      const waited = Math.round((Date.now() - startAt) / 1000)
      ElMessageBox.alert(
        `连接失败，请检查网络或配置后重新连接。\n（已等待约 ${waited}s 仍未建立 ROS Bridge 连接）`,
        '连接失败',
        { type: 'error', confirmButtonText: '我知道了' }
      )
    }
  }, 6000)
}

const modeClass = computed(() => ({
  'mode-auto': robotStore.status.mode === 'AUTO',
  'mode-manual': robotStore.status.mode === 'MANUAL',
}))

const navLabel = computed(() => {
  switch (robotStore.status.navStatus) {
    case 'navigating': return '巡检中'
    case 'paused': return '已暂停'
    case 'error': return '异常'
    default: return '空闲'
  }
})

const navClass = computed(() => ({
  'nav-navigating': robotStore.status.navStatus === 'navigating',
  'nav-paused': robotStore.status.navStatus === 'paused',
  'nav-error': robotStore.status.navStatus === 'error',
  'nav-idle': robotStore.status.navStatus === 'idle',
}))

const latencyClass = computed(() => {
  const l = robotStore.status.latency
  if (l < 0) return 'latency-timeout'
  if (l <= 100) return 'latency-good'
  if (l <= 300) return 'latency-warn'
  return 'latency-bad'
})

function handleReconnect() {
  robotStore.disconnect()
  setTimeout(() => robotStore.connect(), 500)
}

// ===== 智能跟随（启动前检查前置条件） =====
async function handleFollow() {
  // 如果正在跟随中，点击即停止
  if (followActive.value) {
    await stopFollow()
    return
  }

  // 1. 检查连接状态
  if (!robotStore.status.connected) {
    ElMessageBox.alert('请先连接到机器人再开启跟随模式', '未连接', {
      type: 'warning',
      confirmButtonText: '我知道了',
    })
    return
  }

  // 2. 检查是否已重定位（navStatus 为 idle/空闲 表示定位完成）
  if (robotStore.status.navStatus === 'error') {
    ElMessageBox.alert('机器人定位异常，请先完成重定位再开启跟随模式', '定位异常', {
      type: 'warning',
      confirmButtonText: '我知道了',
    })
    return
  }

  // 3. 前方障碍物检测提示（基于激光雷达数据，此处做基础占位提示）
  // TODO: 接入 /scan 话题的实时距离数据，判断前方 0.5m 内是否有障碍物
  // 目前仅给出安全提示

  // 4. 调用后端启动跟随 → 弹出摄像头画面 → 用户框选/点击目标
  await startFollow()
}
</script>

<style lang="scss" scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  height: $header-height;
  padding: 0 20px;
  background: var(--bg-panel);
  border-bottom: 1px solid $border-color;
  box-shadow: var(--shadow-header);
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-shrink: 0;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;

  .system-logo {
    height: 32px;
    width: auto;
    flex-shrink: 0;
    object-fit: contain;
    display: block;
    /* 图片已处理为透明背景 PNG，无需混合滤镜，直接保留原始黄/红色彩 */
    background: transparent;
  }
}

// ===== 系统名称（AgileX 风：硬朗无衬线 + 半粗 + 字距） =====
.logo-text {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 0.5px;
  font-family: 'Inter', 'Roboto', 'Segoe UI', system-ui, sans-serif;
  line-height: 1;
  white-space: nowrap;
  user-select: none;

  .logo-text-main {
    color: $text-primary;
  }

  // 局部高亮：随主题绑定（暗色红 / 亮色蓝）
  .logo-text-accent {
    color: $theme-primary;
  }
}

// 🌙 暗色：白字 + 红高亮（白红硬朗工业风）
html.dark .logo-text .logo-text-main {
  color: #ffffff;
}

// ☀️ 亮色：深黑字 + 蓝高亮（黑蓝科技风）
html.light .logo-text .logo-text-main {
  color: #1a1a1a;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-left: auto;
  flex-shrink: 0;
}

// 工业级半圆角胶囊：电池/电压/速度
.robot-info {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 14px;
  background: var(--bg-card-2);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}

.info-item {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 2px 10px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  color: $text-secondary;

  .el-icon {
    font-size: 15px;
    color: $theme-primary;
  }
}

.info-text {
  color: $text-secondary;
}

.mode {
  margin-left: 4px;
  padding: 3px 12px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
  border: 1px solid transparent;
}

.mode-auto {
  background: rgba($accent-green, 0.1);
  color: $accent-green;
  border-color: rgba($accent-green, 0.4);
}

.mode-manual {
  background: rgba($accent-yellow, 0.15);
  color: $accent-yellow;
  border-color: rgba($accent-yellow, 0.4);
}

// 网络延时指示
.latency {
  .el-icon { color: $accent-green; }
  &.latency-good .el-icon { color: $accent-green; }
  &.latency-warn {
    .el-icon { color: $accent-yellow; }
    .info-text { color: $accent-yellow; }
  }
  &.latency-bad {
    .el-icon { color: #e06c75; }
    .info-text { color: #e06c75; }
  }
  &.latency-timeout {
    .el-icon { color: #e06c75; }
    .info-text { color: #e06c75; }
  }
}

// 巡检状态指示
.nav {
  .el-icon { color: $theme-primary; }
  &.nav-navigating {
    .el-icon { color: $accent-green; }
    .info-text { color: $accent-green; }
  }
  &.nav-paused {
    .el-icon { color: $accent-yellow; }
    .info-text { color: $accent-yellow; }
  }
  &.nav-error {
    .el-icon { color: #e06c75; }
    .info-text { color: #e06c75; }
  }
  &.nav-idle .info-text { color: $text-muted; }
}

// 一键跟随按钮（与顶部栏统一扁平风格）
.follow-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border: 1px solid $border-color;
  border-radius: 6px;
  background: var(--bg-card-2);
  color: $text-secondary;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all $transition;
  white-space: nowrap;

  .el-icon {
    font-size: 13px;
  }

  .spin {
    animation: spin 1s linear infinite;
  }

  &:hover {
    border-color: $theme-primary;
    color: $theme-primary;
    background: var(--theme-primary-soft);
  }

  &.active {
    background: $theme-primary;
    border-color: $theme-primary;
    color: #fff;

    &:hover {
      background: $theme-primary-hover;
    }
  }

  &.loading {
    opacity: 0.7;
    cursor: wait;
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

// 主题切换按钮（无边框圆形 + 悬浮旋转）
.theme-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  font-size: 16px;
  color: $text-secondary;
  background: transparent;
  transition: all $transition;

  .el-icon {
    font-size: 17px;
    transition: transform $transition, color $transition;
  }

  &:hover {
    background: var(--accent-blue-soft);
    color: $theme-primary;

    .el-icon {
      transform: rotate(20deg) scale(1.12);
    }
  }

  &:active {
    transform: scale(0.92);
  }
}

// 扁平化连接控制栏（最右侧）
.connection-group {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  background: var(--bg-card-2);
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border: 1px solid $border-color;
  border-radius: 14px;
  font-size: 12px;
  background: var(--bg-card-2);
  color: $text-muted;
  transition: all $transition;
  white-space: nowrap;

  &.online {
    color: $accent-green;
    border-color: rgba($accent-green, 0.4);
    background: rgba($accent-green, 0.08);
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

.inspect-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.inspect-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 14px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  transition: background 0.2s;
  white-space: nowrap;

  &.start {
    background: $btn-primary-bg;
    &:hover { background: $theme-primary-hover; }
  }

  &.pause {
    background: $accent-yellow;
    &:hover { background: #d4912f; }
  }
}

// ===== 连接配置弹窗 =====
.connect-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px 2px;
}

.connect-field {
  display: flex;
  flex-direction: column;
  gap: 6px;

  label {
    font-size: 13px;
    font-weight: 500;
    color: var(--text-secondary);
  }
}
</style>
