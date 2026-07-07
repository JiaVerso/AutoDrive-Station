<template>
  <aside class="right-panel">
    <div class="panel-title">{{ panelTitle }}</div>
    <div class="panel-body">

      <!-- 建图 -->
      <template v-if="mapStore.activeTool === 'mapping'">
        <div class="panel-section">
          <h4>地图控制</h4>
          <div class="btn-group">
            <el-button size="small" :disabled="mapStore.mapping" @click="handleStartMapping">开始建图</el-button>
            <el-button size="small" :disabled="!mapStore.mapping" @click="mapStore.stopMapping()">停止建图</el-button>
          </div>
          <div class="btn-group">
            <el-button size="small" @click="handleSaveMap">保存地图</el-button>
            <el-button size="small" @click="mapStore.localize()">重定位</el-button>
          </div>
        </div>
        <div class="panel-section">
          <h4>地图管理</h4>
          <el-select v-model="selectedMap" size="small" placeholder="选择地图" class="full-width">
            <el-option v-for="m in mapStore.savedMaps" :key="m" :label="m" :value="m" />
          </el-select>
          <div class="btn-group" style="margin-top: 8px">
            <el-button size="small" @click="handleLoadMap">加载</el-button>
            <el-button size="small" @click="handleDeleteMap">删除</el-button>
          </div>
        </div>
        <div class="panel-section">
          <h4>点云数据</h4>
          <div class="info-row">
            <span>点云数量</span>
            <span class="info-value">{{ mapStore.pointCloudData.length }}</span>
          </div>
          <div class="info-row">
            <span>连接状态</span>
            <span v-if="!robotStore.status.connected" style="color: #f56c6c">未连接</span>
            <span v-else style="color: #67c23a">已订阅</span>
          </div>
          <div class="btn-group" style="margin-top: 8px">
            <el-button size="small" @click="clearPointCloud">清空点云</el-button>
          </div>
        </div>
        <div class="panel-section">
          <h4>3D 点云</h4>
          <div class="point-cloud-container">
            <PointCloud3D />
          </div>
        </div>
      </template>

      <!-- 导航 / 航点 / 路径 -->
      <template v-if="mapStore.activeTool === 'navigation' || mapStore.activeTool === 'waypoint' || mapStore.activeTool === 'path'">
        <div class="panel-section">
          <h4>航线控制</h4>
          <div class="btn-group">
            <el-button size="small" :disabled="!navStore.waypoints.length" @click="handleFinishRoute">完成航线</el-button>
            <el-button size="small" :disabled="!navStore.waypoints.length" @click="navStore.clearWaypoints()">清除航点</el-button>
          </div>
          <div class="btn-group" style="margin-top: 8px">
            <el-button size="small" :disabled="!navStore.waypoints.length || !robotStore.status.connected" type="primary" @click="handleSendWaypoints">发送航点</el-button>
            <el-button size="small" :disabled="!navStore.waypoints.length" @click="handleSaveWaypoints">保存JSON</el-button>
          </div>
        </div>
        <div class="panel-section">
          <h4>航点列表</h4>
          <div v-if="navStore.waypoints.length === 0" class="empty-state">
            <span>暂无航点</span>
          </div>
          <div v-else class="waypoint-list">
            <div v-for="wp in navStore.waypoints" :key="wp.id" class="waypoint-item">
              <span class="waypoint-name">{{ wp.name }}</span>
              <span class="waypoint-coord">({{ wp.x.toFixed(2) }}, {{ wp.y.toFixed(2) }})</span>
              <el-button size="small" type="danger" @click="navStore.removeWaypoint(wp.id)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
        <div class="panel-section">
          <h4>路线管理</h4>
          <el-input v-model="newPathName" size="small" placeholder="路线名称" class="full-width" />
          <div class="btn-group" style="margin-top: 8px">
            <el-button size="small" :disabled="!navStore.waypoints.length || !newPathName" @click="handleSavePath">保存路线</el-button>
          </div>
          <el-select v-model="selectedPath" size="small" placeholder="选择路线" class="full-width" style="margin-top: 8px">
            <el-option v-for="p in navStore.paths" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <div class="btn-group" style="margin-top: 8px">
            <el-button size="small" :disabled="!selectedPath" @click="handleLoadPath">加载路线</el-button>
            <el-button size="small" :disabled="!selectedPath" type="danger" @click="handleDeletePath">删除路线</el-button>
          </div>
        </div>
      </template>

      <!-- 导航状态（仅在 navigation 显示） -->
      <template v-if="mapStore.activeTool === 'navigation'">
        <div class="panel-section">
          <h4>导航状态</h4>
          <div class="info-row">
            <span>当前状态</span>
            <span :style="{ color: navStore.navStatus.active ? '#67c23a' : '#909399' }">{{ navStore.navStatus.active ? '运行中' : '停止' }}</span>
          </div>
          <div class="info-row">
            <span>当前航点</span>
            <span class="info-value">{{ navStore.navStatus.currentWaypointIndex + 1 }} / {{ navStore.waypoints.length }}</span>
          </div>
          <div class="progress-info">
            <span>进度</span>
            <el-progress :percentage="navStore.navStatus.progress" :stroke-width="8" :show-text="false" />
          </div>
          <div class="btn-group" style="margin-top: 8px">
            <el-button size="small" :disabled="navStore.navStatus.active || !navStore.waypoints.length" @click="navStore.startNavigation()">开始导航</el-button>
            <el-button size="small" :disabled="!navStore.navStatus.active" @click="navStore.stopNavigation()">停止导航</el-button>
          </div>
        </div>
      </template>

      <!-- 摄像头 -->
      <template v-if="mapStore.activeTool === 'camera'">
        <div class="panel-section">
          <h4>摄像头控制</h4>
          <div class="btn-group">
            <button class="camera-btn" :class="{ active: cameraConnected }" @click="toggleCamera">
              <el-icon :size="20">
                <VideoPlay v-if="!cameraConnected" />
                <VideoPause v-else />
              </el-icon>
              <span>{{ cameraConnected ? '关闭' : '开启' }}</span>
            </button>
          </div>

        </div>
        <div v-if="cameraConnected" class="panel-section">
          <h4>实时画面</h4>
          <div class="camera-view">
            <img v-if="cameraImage" :src="cameraImage" alt="Camera Feed" class="camera-img" />
            <div v-else class="camera-placeholder">
              <el-icon :size="48"><VideoPlay /></el-icon>
              <span>等待画面...</span>
            </div>
          </div>
          <div class="info-row" style="margin-top: 8px">
            <span>FPS</span>
            <span class="info-value">{{ cameraFps }}</span>
          </div>
        </div>
      </template>

      <!-- 定位 -->
      <template v-if="mapStore.activeTool === 'localization'">
        <div class="panel-section">
          <h4>SLAM云连接</h4>
          <div class="info-row">
            <span>连接状态</span>
            <span v-if="!robotStore.status.connected" style="color: #f56c6c">未连接</span>
            <span v-else style="color: #67c23a">已连接</span>
          </div>
          <div class="info-row">
            <span>机器人模式</span>
            <span class="info-value">{{ robotStore.status.mode }}</span>
          </div>
        </div>
        <div class="panel-section">
          <h4>系统信息</h4>
          <div class="info-row">
            <span>电池</span>
            <span class="info-value">{{ robotStore.status.battery }}%</span>
          </div>
          <div class="info-row">
            <span>电压</span>
            <span class="info-value">{{ robotStore.status.voltage }}V</span>
          </div>
          <div class="info-row">
            <span>速度</span>
            <span class="info-value">{{ robotStore.status.speed.toFixed(2) }} m/s</span>
          </div>
        </div>
        <div class="panel-section">
          <h4>手动控制</h4>
          <div class="safety-group">
            <button class="safety-btn" :class="{ active: robotStore.safetyStopped }" @click="handleSafetyStop">
              <span>{{ robotStore.safetyStopped ? '解除急停' : '急停' }}</span>
            </button>
          </div>
          <div class="direction-grid">
            <div></div>
            <button class="direction-btn" @mousedown="sendVel(1, 0)" @mouseup="sendVel(0, 0)"><el-icon><Top /></el-icon></button>
            <div></div>
            <button class="direction-btn" @mousedown="sendVel(0, 1)" @mouseup="sendVel(0, 0)"><el-icon><ArrowLeft /></el-icon></button>
            <button class="direction-btn stop" @click="sendVel(0, 0)"><span>停</span></button>
            <button class="direction-btn" @mousedown="sendVel(0, -1)" @mouseup="sendVel(0, 0)"><el-icon><ArrowRight /></el-icon></button>
            <div></div>
            <button class="direction-btn" @mousedown="sendVel(-1, 0)" @mouseup="sendVel(0, 0)"><el-icon><Bottom /></el-icon></button>
            <div></div>
          </div>
          <div class="slider-group">
            <label>线速度</label>
            <el-slider v-model="linearSpeed" :min="0" :max="2" :step="0.1" size="small" />
            <span class="speed-val">{{ linearSpeed.toFixed(1) }} m/s</span>
          </div>
          <div class="slider-group">
            <label>角速度</label>
            <el-slider v-model="angularSpeed" :min="-3" :max="3" :step="0.1" size="small" />
            <span class="speed-val">{{ angularSpeed.toFixed(1) }} rad/s</span>
          </div>
        </div>
      </template>

      <!-- 日志 -->
      <template v-if="mapStore.activeTool === 'log'">
        <div class="panel-section">
          <h4>当前状态</h4>
          <div class="info-row">
            <span>连接状态</span>
            <span v-if="!robotStore.status.connected" style="color: #f56c6c">离线</span>
            <span v-else style="color: #67c23a">在线</span>
          </div>
          <div class="info-row">
            <span>建图状态</span>
            <span class="info-value">{{ mapStore.mapping ? '运行中' : '停止' }}</span>
          </div>
          <div class="info-row">
            <span>导航状态</span>
            <span class="info-value">{{ navStore.navStatus.active ? '运行中' : '停止' }}</span>
          </div>
          <div class="info-row">
            <span>急停</span>
            <span class="info-value" :style="{ color: robotStore.safetyStopped ? '#f56c6c' : '#67c23a' }">{{ robotStore.safetyStopped ? '已触发' : '正常' }}</span>
          </div>
        </div>
        <div class="panel-section">
          <h4>系统日志</h4>
          <div class="log-list">
            <div v-for="(log, idx) in logs" :key="idx" class="log-item" :class="'log-' + log.level">
              <span class="log-time">{{ log.time }}</span>
              <span class="log-level">{{ log.level.toUpperCase() }}</span>
              <span class="log-source">[{{ log.source }}]</span>
              <span class="log-msg">{{ log.message }}</span>
            </div>
          </div>
        </div>
      </template>

      <!-- 设置 / 地图 -->
      <template v-if="mapStore.activeTool === 'settings' || mapStore.activeTool === 'map'">
        <div class="panel-section">
          <h4>设置</h4>
          <div class="setting-item">
            <span>自动重连</span>
            <el-switch v-model="autoReconnect" size="small" />
          </div>
          <div class="setting-item">
            <span>显示轨迹</span>
            <el-switch v-model="showTrail" size="small" />
          </div>
          <div class="setting-item">
            <span>显示激光</span>
            <el-switch v-model="showLidar" size="small" />
          </div>
          <div class="setting-item">
            <span>地图透明度</span>
            <el-slider v-model="mapOpacity" :min="20" :max="100" size="small" />
          </div>
        </div>
        <div class="panel-section">
          <h4>系统信息</h4>
          <div class="info-row">
            <span>电池</span>
            <span class="info-value">{{ robotStore.status.battery }}%</span>
          </div>
          <div class="info-row">
            <span>电压</span>
            <span class="info-value">{{ robotStore.status.voltage }}V</span>
          </div>
          <div class="info-row">
            <span>速度</span>
            <span class="info-value">{{ robotStore.status.speed.toFixed(2) }} m/s</span>
          </div>
        </div>
      </template>

    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Delete, Top, Bottom, ArrowLeft, ArrowRight, VideoPlay, VideoPause } from '@element-plus/icons-vue'
import { useMapStore } from '@/stores/map'
import { useRobotStore } from '@/stores/robot'
import { useNavigationStore } from '@/stores/navigation'
import { ElMessage } from 'element-plus'
import { rosApi } from '@/api/ros'
import PointCloud3D from './PointCloud3D.vue'
import type { ActiveTool } from '@/types'
import { mockLogs } from '@/mock/data'

const mapStore = useMapStore()
const robotStore = useRobotStore()
const navStore = useNavigationStore()

const panelLabels: Record<ActiveTool, string> = {
  map: '地图',
  mapping: '建图',
  localization: '定位',
  navigation: '导航',
  waypoint: '航点',
  path: '路径',
  camera: '摄像头',
  log: '日志',
  settings: '设置',
}

const panelTitle = computed(() => panelLabels[mapStore.activeTool] || '建图')

const selectedMap = ref('')
const selectedPath = ref('')
const newPathName = ref('')
const linearSpeed = ref(0.5)
const angularSpeed = ref(0)
const autoReconnect = ref(true)
const showTrail = ref(true)
const showLidar = ref(true)
const mapOpacity = ref(80)

const logs = ref(mockLogs)

const cameraImage = ref<string | null>(null)
const cameraConnected = ref(false)
const cameraFps = ref(0)

function clearPointCloud() {
  mapStore.clearPointCloud()
  ElMessage.info('点云已清空')
}

function toggleCamera() {
  if (cameraConnected.value) {
    cameraConnected.value = false
    cameraImage.value = null
    rosApi.unsubscribeTopic('/camera/image_raw')
  } else {
    cameraConnected.value = true
    rosApi.subscribeTopic('/camera/image_raw', 'sensor_msgs/msg/CompressedImage', (message: any) => {
      if (message && message.data) {
        let frameCount = 0
        cameraImage.value = 'data:image/jpeg;base64,' + message.data
        frameCount++
        if (frameCount % 30 === 1 && cameraFps.value === 0) {
          cameraFps.value = 30
        }
      }
    })
  }
}

function handleSafetyStop() {
  robotStore.triggerSafetyStop(!robotStore.safetyStopped)
}

function handleStartMapping() {
  mapStore.startMapping()
  ElMessage.success('建图已开始')
}

function handleSaveMap() {
  const name = mapStore.currentMap.name + '_new'
  mapStore.saveMap(name)
  ElMessage.success('地图已保存: ' + name)
}

function handleLoadMap() {
  if (selectedMap.value) {
    mapStore.loadMap(selectedMap.value)
    ElMessage.success('地图已加载: ' + selectedMap.value)
  }
}

function handleDeleteMap() {
  if (selectedMap.value) {
    mapStore.deleteMap(selectedMap.value)
    selectedMap.value = ''
    ElMessage.success('地图已删除')
  }
}

function handleFinishRoute() {
  if (mapStore.tempLinePoints.length >= 2) {
    mapStore.tempLinePoints.forEach((point, idx) => {
      navStore.addWaypoint({ x: point.x, y: point.y, name: `航点${navStore.waypoints.length + 1}` })
    })
    mapStore.finishDrawLine()
    ElMessage.success(`已添加 ${mapStore.tempLinePoints.length} 个航点`)
  } else {
    ElMessage.warning('至少需要2个点才能创建航线')
  }
}

function handleSendWaypoints() {
  if (!robotStore.status.connected) {
    ElMessage.warning('请先连接到 ROS Bridge')
    return
  }
  const success = navStore.sendWaypointsToRos()
  if (success) {
    ElMessage.success('航点已发送到后端')
  } else {
    ElMessage.warning('没有航点可发送')
  }
}

function handleSaveWaypoints() {
  const success = navStore.saveWaypointsToFile()
  if (success) {
    ElMessage.success('航点JSON文件已保存')
  } else {
    ElMessage.warning('没有航点可保存')
  }
}

function handleSavePath() {
  if (newPathName.value) {
    navStore.savePath(newPathName.value)
    ElMessage.success('路线已保存: ' + newPathName.value)
    newPathName.value = ''
  }
}

function handleLoadPath() {
  if (selectedPath.value) {
    navStore.loadPath(selectedPath.value)
    ElMessage.success('路线已加载')
  }
}

function handleDeletePath() {
  if (selectedPath.value) {
    navStore.deletePath(selectedPath.value)
    selectedPath.value = ''
    ElMessage.success('路线已删除')
  }
}

function sendVel(linear: number, angular: number) {
  robotStore.sendVelocity(linear * linearSpeed.value, angular * angularSpeed.value)
}
</script>

<style lang="scss" scoped>
.right-panel {
  width: $right-panel-width;
  background: $bg-secondary;
  border-left: 1px solid $border-color;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: $text-primary;
  padding: 12px 16px 8px;
  border-bottom: 1px solid $border-color;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
}

.panel-section {
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid $border-color;

  &:last-child {
    border-bottom: none;
  }

  h4 {
    font-size: 13px;
    font-weight: 500;
    color: $text-secondary;
    margin-bottom: 10px;
  }
}

.btn-group {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;

  .el-button {
    flex: 1;
    min-width: 0;
    background: #ffffff;
    border-color: #e0e0e0;
    color: #333333;
    font-weight: 500;
    border-radius: 6px;
    height: 32px;
    transition: all $transition;

    &:hover {
      background: #f0f0f0;
      border-color: #cccccc;
      color: #111111;
    }

    &.el-button--primary {
      background: #ffffff;
      border-color: #409eff;
      color: #409eff;

      &:hover {
        background: #ecf5ff;
      }
    }

    &.el-button--danger {
      background: #ffffff;
      border-color: #f56c6c;
      color: #f56c6c;

      &:hover {
        background: #fef0f0;
      }
    }

    &.el-button--success {
      background: #ffffff;
      border-color: #67c23a;
      color: #67c23a;

      &:hover {
        background: #f0f9eb;
      }
    }

    &:disabled {
      background: #f5f5f5;
      border-color: #e0e0e0;
      color: #c0c4cc;
      cursor: not-allowed;
    }
  }
}

.full-width {
  width: 100%;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;

  .info-value {
    color: $accent-blue;
    font-weight: 500;
  }
}

.empty-state {
  text-align: center;
  padding: 16px;
  color: $text-muted;
  background: $bg-card;
  border-radius: 6px;
}

.waypoint-list {
  max-height: 150px;
  overflow-y: auto;
}

.waypoint-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px;
  background: $bg-card;
  border-radius: 4px;
  margin-bottom: 4px;

  .waypoint-name {
    flex: 1;
    font-size: 12px;
    color: $text-primary;
  }

  .waypoint-coord {
    font-size: 11px;
    color: $text-muted;
  }
}

.progress-info {
  display: flex;
  align-items: center;
  gap: 8px;

  .el-progress {
    flex: 1;
  }
}

.camera-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 20px;
  background: #ffffff;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  cursor: pointer;
  transition: all $transition;
  color: #333333;

  &:hover {
    background: #f0f0f0;
  }

  &.active {
    background: #ecf5ff;
    border-color: #409eff;
    color: #409eff;
  }
}

.camera-view {
  width: 100%;
  aspect-ratio: 4/3;
  background: #000;
  border-radius: 6px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.camera-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.camera-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #666;
}

.safety-group {
  display: flex;
  gap: 12px;
  align-items: center;
}

.safety-btn {
  padding: 12px 24px;
  background: #fef0f0;
  border: 2px solid #f56c6c;
  border-radius: 8px;
  color: #f56c6c;
  font-weight: bold;
  cursor: pointer;
  transition: all $transition;

  &:hover {
    background: #fde2e2;
  }

  &.active {
    background: #f0f9eb;
    border-color: #67c23a;
    color: #67c23a;
  }
}

.direction-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  max-width: 150px;
  margin: 12px auto;
}

.direction-btn {
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #ffffff;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  cursor: pointer;
  transition: all $transition;
  color: #333333;

  &:hover {
    background: #f0f0f0;
  }

  &.stop {
    background: #f5f5f5;
    border-color: #d9d9d9;
    color: #666;
  }
}

.slider-group {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;

  label {
    font-size: 12px;
    color: $text-secondary;
    min-width: 60px;
  }

  .el-slider {
    flex: 1;
  }

  .speed-val {
    font-size: 12px;
    color: $accent-blue;
    min-width: 60px;
    text-align: right;
  }
}

.setting-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  font-size: 13px;
  color: $text-secondary;
}

.point-cloud-container {
  width: 100%;
  height: 200px;
  background: #000;
  border-radius: 6px;
  overflow: hidden;
}

.log-list {
  max-height: 350px;
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
}

.log-info .log-level { color: $accent-blue; }
.log-warn .log-level { color: $accent-yellow; }
.log-error .log-level { color: $accent-red; }
.log-debug .log-level { color: $text-muted; }

.log-source {
  color: $accent-cyan;
}

.log-msg {
  color: $text-secondary;
}
</style>
