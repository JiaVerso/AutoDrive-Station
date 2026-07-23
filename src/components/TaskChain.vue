<template>
  <div class="task-chain">
    <!-- ============ 左侧：任务节点库（Toolbox）=========== -->
    <aside class="tc-toolbox">
      <div class="tb-title">任务节点</div>
      <div class="tb-hint">拖拽卡片到中间画布</div>
      <div
        v-for="item in toolbox"
        :key="item.type"
        class="tb-card"
        :class="'tb-' + item.type"
        draggable="true"
        @dragstart="onToolDragStart($event, item.type)"
      >
        <el-icon :size="20"><component :is="item.icon" /></el-icon>
        <div class="tb-meta">
          <span class="tb-name">{{ item.label }}</span>
          <span class="tb-desc">{{ item.desc }}</span>
        </div>
      </div>
    </aside>

    <!-- ============ 中间：任务流画布 ============ -->
    <main class="tc-canvas" @dragover.prevent="onCanvasDragOver" @drop="onCanvasDrop($event)">
      <div v-if="store.nodes.length === 0" class="tc-empty">
        <el-icon :size="56"><Connection /></el-icon>
        <p>从左侧拖拽任务卡片到此处，开始编排你的任务链</p>
      </div>

      <div v-else class="tc-flow">
        <template v-for="(node, index) in store.nodes" :key="node.id">
          <!-- 节点卡片 -->
          <div
            class="tc-node"
            :class="[
              'node-' + node.type,
              {
                executing: store.currentStep === index + 1 && store.isRunning,
                done: store.currentStep > index + 1,
                dragover: dragOverIndex === index,
              },
            ]"
            @dragover.prevent="onCardDragOver($event, index)"
            @drop.stop="onCardDrop($event, index)"
          >
            <div class="node-head" draggable="true" @dragstart="onNodeDragStart($event, index)" @click="store.toggleExpand(node.id)">
              <span class="node-step">{{ index + 1 }}</span>
              <el-icon class="node-icon"><component :is="nodeMeta(node.type).icon" /></el-icon>
              <span class="node-title">{{ nodeMeta(node.type).label }}</span>
              <el-tag v-if="store.currentStep === index + 1 && store.isRunning" size="small" type="primary" effect="dark" class="node-state">执行中</el-tag>
              <el-tag v-else-if="store.currentStep > index + 1" size="small" type="success" effect="plain" class="node-state">已完成</el-tag>
              <span class="node-spacer" />
              <span class="node-actions" @click.stop>
                <el-button size="small" text :disabled="index === 0" @click="store.moveUp(node.id)"><el-icon><Top /></el-icon></el-button>
                <el-button size="small" text :disabled="index === store.nodes.length - 1" @click="store.moveDown(node.id)"><el-icon><Bottom /></el-icon></el-button>
                <el-button size="small" text type="danger" @click="store.removeNode(node.id)"><el-icon><Delete /></el-icon></el-button>
                <el-icon class="node-collapse"><component :is="node.expanded ? ArrowUp : ArrowDown" /></el-icon>
              </span>
            </div>

            <!-- 参数表单 -->
            <div v-if="node.expanded" class="node-body">
              <!-- 导航节点 -->
              <template v-if="node.type === 'nav'">
                <div class="param-row">
                  <label>路径类型</label>
                  <el-select v-model="node.params.pathType" size="small" style="flex: 1" @change="(v: any) => store.setNavPathType(node.id, v)">
                    <el-option label="单点导航" value="single" />
                    <el-option label="直线任务" value="linear" />
                    <el-option label="四方形任务" value="square" />
                    <el-option label="环形循环" value="loop" />
                  </el-select>
                </div>

                <!-- 单点模式：保持原 X/Y/Yaw 表单 -->
                <template v-if="node.params.pathType === 'single'">
                  <div class="param-row">
                    <label>目标 X (m)</label>
                    <el-input-number v-model="node.params.x" :step="0.1" :precision="2" controls-position="right" size="small" />
                  </div>
                  <div class="param-row">
                    <label>目标 Y (m)</label>
                    <el-input-number v-model="node.params.y" :step="0.1" :precision="2" controls-position="right" size="small" />
                  </div>
                  <div class="param-row">
                    <label>朝向 Yaw (rad)</label>
                    <el-input-number v-model="node.params.yaw" :step="0.1" :precision="2" controls-position="right" size="small" />
                  </div>
                </template>

                <!-- 多点模式：动态航点列表 -->
                <template v-else>
                  <div class="wp-list">
                    <div
                      v-for="(wp, wi) in node.params.waypoints"
                      :key="wi"
                      class="wp-item"
                    >
                      <span class="wp-idx">{{ wi + 1 }}</span>
                      <div class="wp-coords">
                        <div class="param-row tight">
                          <label>X</label>
                          <el-input-number v-model="wp.x" :step="0.1" :precision="2" controls-position="right" size="small" />
                        </div>
                        <div class="param-row tight">
                          <label>Y</label>
                          <el-input-number v-model="wp.y" :step="0.1" :precision="2" controls-position="right" size="small" />
                        </div>
                        <div class="param-row tight">
                          <label>Yaw</label>
                          <el-input-number v-model="wp.yaw" :step="0.1" :precision="2" controls-position="right" size="small" />
                        </div>
                      </div>
                      <el-button
                        size="small" text type="danger"
                        :disabled="node.params.waypoints.length <= 1"
                        @click="store.removeWaypoint(node.id, wi)"
                      >
                        <el-icon><Delete /></el-icon>
                      </el-button>
                    </div>
                  </div>
                  <el-button size="small" class="wp-add" @click="store.addWaypoint(node.id)">
                    <el-icon><Plus /></el-icon> 添加航点
                  </el-button>
                  <div class="wp-tip" v-if="node.params.pathType === 'loop'">
                    <el-icon><RefreshRight /></el-icon>
                    环形任务：到达最后一个点后自动回到第一个点循环，直到收到“紧急终止”。
                  </div>
                </template>
              </template>

              <!-- 延时节点 -->
              <template v-else-if="node.type === 'wait'">
                <div class="param-row">
                  <label>等待时长 (s)</label>
                  <el-slider v-model="node.params.duration" :min="0" :max="60" :step="1" show-input size="small" />
                </div>
                <div class="param-row">
                  <label>或定时启动</label>
                  <el-time-picker v-model="node.params.at" placeholder="指定启动时间" size="small" style="width: 100%" value-format="HH:mm:ss" format="HH:mm:ss" />
                </div>
              </template>

              <!-- 机器人巡检 -->
              <template v-else-if="node.type === 'robot'">
                <div class="param-row">
                  <label>巡检模式</label>
                  <el-select v-model="node.params.mode" size="small" style="width: 100%">
                    <el-option label="自动巡游" value="patrol" />
                    <el-option label="定点巡检" value="inspect" />
                    <el-option label="跟随模式" value="follow" />
                  </el-select>
                </div>
                <div class="param-row">
                  <label>速度上限 (m/s)</label>
                  <el-slider v-model="node.params.max_speed" :min="0.1" :max="2" :step="0.1" show-input size="small" />
                </div>
                <div class="param-row">
                  <label>巡检时长 (s)</label>
                  <el-input-number v-model="node.params.duration" :min="0" :step="5" controls-position="right" size="small" />
                </div>
              </template>

              <!-- 充电 -->
              <template v-else-if="node.type === 'charge'">
                <div class="param-tip">
                  <el-icon><Lightning /></el-icon>
                  触发机器人回充对接，无需参数。执行到此节点时后端将发布回充指令。
                </div>
              </template>
            </div>
          </div>

          <!-- 连接箭头 -->
          <div v-if="index < store.nodes.length - 1" class="tc-arrow">
            <el-icon><Bottom /></el-icon>
          </div>
        </template>

        <!-- 末尾拖放区（追加）-->
        <div
          class="tc-append"
          :class="{ dragover: dragOverIndex === store.nodes.length }"
          @dragover.prevent="onCardDragOver($event, store.nodes.length)"
          @drop.stop="onCardDrop($event, store.nodes.length)"
        >
          <el-icon><Plus /></el-icon>
          <span>拖拽到此处追加节点</span>
        </div>
      </div>
    </main>

    <!-- ============ 右侧：全局控制区 ============ -->
    <aside class="tc-console">
      <div class="con-status" :class="'con-' + store.status">
        <div class="con-status-label">任务链状态</div>
        <div class="con-status-value">{{ store.statusText }}</div>
        <div class="con-progress">
          <div
            v-for="(n, i) in store.nodes"
            :key="n.id"
            class="con-dot"
            :class="{
              active: store.currentStep === i + 1 && store.isRunning,
              passed: store.currentStep > i + 1,
            }"
          />
        </div>
      </div>

      <div class="con-section">
        <div class="con-title">任务链操作</div>
        <div class="con-btns">
          <el-button type="primary" class="con-start" :disabled="store.isRunning || store.nodes.length === 0" @click="store.startChain()">
            <el-icon><VideoPlay /></el-icon> 一键启动执行
          </el-button>
          <el-button
            v-if="store.canPause"
            type="warning"
            :disabled="store.nodes.length === 0"
            @click="store.pauseChain()"
          >
            <el-icon><VideoPause /></el-icon> 暂停
          </el-button>
          <el-button
            v-else-if="store.canResume"
            type="success"
            :disabled="store.nodes.length === 0"
            @click="store.resumeChain()"
          >
            <el-icon><VideoPlay /></el-icon> 恢复
          </el-button>
          <el-button type="danger" :disabled="!store.isRunning && !store.isPaused" @click="store.stopChain()">
            <el-icon><CircleClose /></el-icon> 紧急终止
          </el-button>
        </div>
        <div class="con-save">
          <el-input v-model="chainName" size="small" placeholder="任务链名称" class="con-name" />
          <el-button size="small" @click="handleSave">保存任务链</el-button>
        </div>
        <el-button size="small" text type="info" class="con-clear" @click="store.clearChain()">
          <el-icon><Delete /></el-icon> 清空画布
        </el-button>
      </div>

      <div v-if="store.savedChains.length" class="con-section">
        <div class="con-title">已保存任务链</div>
        <div class="con-chain-list">
          <div v-for="c in store.savedChains" :key="c.id" class="con-chain-item">
            <span class="con-chain-name">{{ c.name }} <em>({{ c.nodes.length }}步)</em></span>
            <span class="con-chain-actions">
              <el-button size="small" text type="primary" @click="store.loadChain(c.id)">加载</el-button>
              <el-button size="small" text type="danger" @click="store.deleteChain(c.id)">删除</el-button>
            </span>
          </div>
        </div>
      </div>

      <div class="con-section con-log-section">
        <div class="con-title">执行日志</div>
        <div class="con-log">
          <div v-for="(l, i) in store.logs" :key="i" class="con-log-item">{{ l }}</div>
        </div>
      </div>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, markRaw } from 'vue'
import {
  Connection, LocationFilled, Lightning, Timer, Cpu,
  Top, Bottom, Delete, ArrowUp, ArrowDown, Plus, RefreshRight,
  VideoPlay, CircleClose, VideoPause,
} from '@element-plus/icons-vue'
import type { TaskNodeType } from '@/types'
import { useTaskChainStore } from '@/stores/taskChain'
import { useRobotStore } from '@/stores/robot'

const store = useTaskChainStore()
const robotStore = useRobotStore()
const chainName = ref('')
const dragOverIndex = ref<number | null>(null)

interface ToolboxItem {
  type: TaskNodeType
  label: string
  desc: string
  icon: any
}

const toolbox: ToolboxItem[] = [
  { type: 'nav', label: '📍 导航节点', desc: '移动到目标点 (X,Y,Yaw)', icon: markRaw(LocationFilled) },
  { type: 'charge', label: '🔋 自动充电', desc: '触发回充对接', icon: markRaw(Lightning) },
  { type: 'wait', label: '⏱️ 定时启动', desc: '等待 N 秒或定时启动', icon: markRaw(Timer) },
  { type: 'robot', label: '🤖 机器人巡检', desc: 'mode + 速度上限', icon: markRaw(Cpu) },
]

const metaMap: Record<TaskNodeType, { label: string; icon: any }> = {
  nav: { label: '导航节点', icon: markRaw(LocationFilled) },
  charge: { label: '自动充电', icon: markRaw(Lightning) },
  wait: { label: '定时启动', icon: markRaw(Timer) },
  robot: { label: '机器人巡检', icon: markRaw(Cpu) },
}

function nodeMeta(type: TaskNodeType) {
  return metaMap[type]
}

// ===== 拖拽逻辑 =====
function onToolDragStart(e: DragEvent, type: TaskNodeType) {
  if (e.dataTransfer) {
    e.dataTransfer.setData('text/plain', 'new:' + type)
    e.dataTransfer.effectAllowed = 'copy'
  }
}

function onNodeDragStart(e: DragEvent, index: number) {
  if (e.dataTransfer) {
    e.dataTransfer.setData('text/plain', 'move:' + index)
    e.dataTransfer.effectAllowed = 'move'
  }
}

function onCardDragOver(e: DragEvent, index: number) {
  dragOverIndex.value = index
}

function onCanvasDragOver() {
  if (dragOverIndex.value !== null) dragOverIndex.value = null
}

function onCardDrop(e: DragEvent, index: number) {
  e.preventDefault()
  handleDrop(e, index)
  dragOverIndex.value = null
}

function onCanvasDrop(e: DragEvent) {
  e.preventDefault()
  handleDrop(e, store.nodes.length)
  dragOverIndex.value = null
}

function handleDrop(e: DragEvent, targetIndex: number) {
  const data = e.dataTransfer?.getData('text/plain') || ''
  if (data.startsWith('new:')) {
    store.addNode(data.slice(4) as TaskNodeType, targetIndex)
  } else if (data.startsWith('move:')) {
    store.moveNode(parseInt(data.slice(5), 10), targetIndex)
  }
}

function handleSave() {
  store.saveChain(chainName.value)
  chainName.value = ''
}

// ===== 状态订阅（连接后）=====
onMounted(() => {
  store.loadSavedChains()
  if (robotStore.status.connected) store.subscribeStatus()
})

watch(
  () => robotStore.status.connected,
  (c) => {
    if (c) store.subscribeStatus()
  }
)

onBeforeUnmount(() => {
  /* 订阅保留，便于断线重连后继续接收 */
})
</script>

<style lang="scss" scoped>
.task-chain {
  flex: 1;
  display: flex;
  min-width: 0;
  background: $bg-primary;
}

// ===== 左侧节点库 =====
.tc-toolbox {
  width: 200px;
  flex-shrink: 0;
  background: $bg-secondary;
  border-right: 1px solid $border-color;
  padding: 14px 12px;
  overflow-y: auto;

  .tb-title {
    font-size: 14px;
    font-weight: 700;
    color: $text-primary;
  }

  .tb-hint {
    font-size: 11px;
    color: $text-muted;
    margin: 4px 0 12px;
  }

  .tb-card {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px;
    margin-bottom: 10px;
    border: 1px solid $border-color;
    border-left: 3px solid #555;
    border-radius: $radius;
    background: $bg-card;
    cursor: grab;
    transition: all $transition;

    &:hover {
      background: $bg-hover;
      border-color: $border-active;
    }

    &:active {
      cursor: grabbing;
    }

    .el-icon {
      color: $text-secondary;
      flex-shrink: 0;
    }

    .tb-meta {
      display: flex;
      flex-direction: column;
      min-width: 0;
    }

    .tb-name {
      font-size: 13px;
      font-weight: 600;
      color: $text-primary;
    }

    .tb-desc {
      font-size: 11px;
      color: $text-muted;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    &.tb-charge { border-left-color: #3a8a5c; .el-icon { color: #3a8a5c; } }
    &.tb-wait { border-left-color: #b09220; .el-icon { color: #b09220; } }
    &.tb-robot { border-left-color: #5b8abf; .el-icon { color: #5b8abf; } }
  }
}

// ===== 中间画布 =====
.tc-canvas {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 24px;
  background:
    radial-gradient(circle, rgba(255, 255, 255, 0.04) 1px, transparent 1px);
  background-size: 18px 18px;
  background-color: $bg-primary;
}

.tc-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  color: $text-muted;

  .el-icon { color: #bfc6cf; }
  p { font-size: 14px; }
}

.tc-flow {
  max-width: 520px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.tc-node {
  width: 420px;
  min-width: 380px;
  max-width: 420px;
  flex: 0 0 auto;
  background: $bg-card;
  border: 1px solid $border-color;
  border-radius: $radius;
  box-shadow: $shadow;
  overflow: hidden;
  transition: all $transition;

  &.dragover {
    border-color: $theme-primary;
    background: color-mix(in srgb, $bg-hover 80%, $bg-card);
  }

  &.executing {
    border-left: 3px solid $theme-primary;
    background: color-mix(in srgb, $bg-hover 70%, $bg-card);
  }

  &.done {
    opacity: 0.65;
  }

  .node-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    cursor: pointer;
    user-select: none;

    .node-step {
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: $theme-primary;
      color: #fff;
      font-size: 12px;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }

    .node-icon {
      color: $theme-primary;
      flex-shrink: 0;
    }

    .node-title {
      font-size: 13px;
      font-weight: 600;
      color: $text-primary;
    }

    .node-spacer { flex: 1; }

    .node-actions {
      display: flex;
      align-items: center;
      gap: 2px;

      .el-button {
        margin: 0;
        padding: 2px 4px;
      }

      .node-collapse {
        color: $text-muted;
        margin-left: 2px;
      }
    }
  }

  .node-body {
    padding: 4px 14px 14px 44px;
    border-top: 1px dashed $border-color;

    .param-row {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 10px;

      label {
        font-size: 12px;
        color: $text-secondary;
        width: 96px;
        flex-shrink: 0;
      }

      .el-slider,
      .el-select,
      .el-input-number,
      .el-input {
        flex: 1;
        min-width: 0;
      }

      .el-input-number {
        width: 100%;
      }
    }

    .param-tip {
      display: flex;
      align-items: flex-start;
      gap: 6px;
      margin-top: 10px;
      font-size: 12px;
      color: $text-secondary;
      background: $bg-card-2;
      border: 1px solid $border-color;
      border-radius: $radius;
      padding: 8px 10px;
      line-height: 1.5;

      .el-icon {
        color: #3a8a5c;
        margin-top: 2px;
        flex-shrink: 0;
      }
    }
  }

  // 多点航点列表
  .wp-list {
    margin-top: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .wp-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    background: $bg-card-2;
    border: 1px solid $border-color;
    border-radius: $radius;

    .wp-idx {
      width: 20px;
      height: 20px;
      border-radius: 50%;
      background: $theme-primary;
      color: #fff;
      font-size: 11px;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }

    .wp-coords {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;

      .param-row.tight {
        margin-top: 0;
        gap: 6px;

        label {
          width: 30px;
          font-size: 11px;
        }

        .el-input-number {
          width: 100%;
        }
      }
    }
  }

  .wp-add {
    margin-top: 8px;
  }

  .wp-tip {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    margin-top: 8px;
    font-size: 11px;
    color: $theme-primary;
    background: color-mix(in srgb, $theme-primary 6%, transparent);
    border: 1px solid color-mix(in srgb, $theme-primary 25%, transparent);
    border-radius: $radius;
    padding: 6px 8px;
    line-height: 1.5;

    .el-icon {
      margin-top: 2px;
      flex-shrink: 0;
    }
  }

  &.node-charge .node-icon { color: #3a8a5c; }
  &.node-wait .node-icon { color: #b09220; }
  &.node-robot .node-icon { color: #5b8abf; }
}

.tc-arrow {
  color: #9aa3ad;
  font-size: 18px;
  line-height: 1;
  padding: 4px 0;
}

.tc-append {
  width: 100%;
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 14px;
  border: 1px dashed $border-color;
  border-radius: $radius;
  color: $text-muted;
  font-size: 13px;
  transition: all $transition;

  &.dragover {
    border-color: $theme-primary;
    color: $theme-primary;
    background: color-mix(in srgb, $theme-primary 5%, transparent);
  }
}

// ===== 右侧控制区 =====
.tc-console {
  width: 320px;
  flex-shrink: 0;
  background: $bg-secondary;
  border-left: 1px solid $border-color;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.con-status {
  padding: 16px;
  border-bottom: 1px solid $border-color;

  .con-status-label {
    font-size: 12px;
    color: $text-muted;
  }

  .con-status-value {
    font-size: 18px;
    font-weight: 700;
    margin-top: 4px;
    color: $text-primary;
  }

  .con-progress {
    display: flex;
    gap: 4px;
    margin-top: 12px;
    flex-wrap: wrap;

    .con-dot {
      width: 14px;
      height: 6px;
      border-radius: 3px;
      background: #e0e3e9;
      transition: all $transition;

      &.active {
        background: $theme-primary;
      }

      &.passed {
        background: #67c23a;
      }
    }
  }

  &.con-running { .con-status-value { color: $theme-primary; } }
  &.con-completed { .con-status-value { color: #3a8a5c; } }
  &.con-error { .con-status-value { color: #c0392b; } }
  &.con-paused { .con-status-value { color: #b09220; } }
}

.con-section {
  padding: 14px 16px;
  border-bottom: 1px solid $border-color;

  .con-title {
    font-size: 13px;
    font-weight: 600;
    color: $text-primary;
    margin-bottom: 10px;
    padding-left: 9px;
    border-left: 3px solid $theme-primary;
  }
}

.con-btns {
  display: flex;
  flex-direction: column;
  gap: 8px;

  .el-button {
    width: 100%;
    margin: 0;
    height: 38px;
  }

  .con-start {
    font-weight: 600;
  }
}

.con-save {
  display: flex;
  gap: 8px;
  margin-top: 10px;

  .con-name {
    flex: 1;
  }
}

.con-clear {
  margin-top: 8px;
  padding-left: 0;
}

.con-chain-list {
  display: flex;
  flex-direction: column;
  gap: 6px;

  .con-chain-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 10px;
    background: $bg-card-2;
    border: 1px solid $border-color;
    border-radius: $radius;

    .con-chain-name {
      font-size: 12px;
      color: $text-primary;

      em {
        color: $text-muted;
        font-style: normal;
      }
    }

    .con-chain-actions .el-button {
      margin: 0;
      padding: 2px 6px;
    }
  }
}

.con-log-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 160px;
}

.con-log {
  flex: 1;
  overflow-y: auto;
  font-family: monospace;
  font-size: 11px;
  color: $text-secondary;
  background: $bg-card-2;
  border: 1px solid $border-color;
  border-radius: $radius;
  padding: 8px;
  max-height: 240px;

  .con-log-item {
    padding: 2px 0;
    border-bottom: 1px solid var(--border-subtle);
    line-height: 1.5;
  }
}
</style>


