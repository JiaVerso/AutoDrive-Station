<template>
  <aside class="right-panel">
    <div class="panel-title">{{ panelTitle }}</div>
    <div class="panel-body">

      <!-- ==================== 建图（二级菜单联动） ==================== -->
      <template v-if="mapStore.activeTool === 'mapping'">

        <!-- 二级【地图设置】 -->
        <div v-if="mapStore.currentMappingTab === 'settings'" class="panel-section">
          <h4>地图控制</h4>
          <div class="btn-group">
            <el-button size="small" :disabled="mapStore.mapping" @click="handleStartMapping">开始建图</el-button>
            <el-button size="small" :disabled="!mapStore.mapping" @click="mapStore.stopMapping()">停止建图</el-button>
          </div>
          <div class="btn-group" style="margin-top: 8px">
            <el-button size="small" @click="handleSaveMap">保存地图</el-button>
            <el-button size="small" type="primary" @click="handleSaveGridMap">保存为2D栅格地图</el-button>
          </div>
        </div>

        <!-- 二级【地图管理】 -->
        <div v-if="mapStore.currentMappingTab === 'manage'" class="panel-section">
          <h4>地图管理</h4>
          <el-select v-model="selectedMap" size="small" placeholder="选择地图" class="full-width">
            <el-option v-for="m in mapStore.savedMaps" :key="m" :label="m" :value="m" />
          </el-select>
          <div class="btn-group" style="margin-top: 8px">
            <el-button size="small" @click="handleLoadMap">加载</el-button>
            <el-button size="small" @click="handleDeleteMap">删除</el-button>
          </div>
        </div>

        <!-- 二级【实时控制】：摄像头 + 手动控制合并展示 -->
        <template v-if="mapStore.currentMappingTab === 'control'">
          <div class="panel-section">
            <h4>实时摄像头</h4>
            <el-select
              v-model="cameraTopic"
              size="small"
              placeholder="选择/输入图像话题"
              class="full-width"
              filterable
              allow-create
              default-first-option
              @change="onImageTopicChange"
            >
              <el-option
                v-for="t in cameraTopicOptions"
                :key="t"
                :label="t"
                :value="t"
              />
            </el-select>
            <div class="btn-group" style="margin-top: 8px">
              <el-button size="small" @click="refreshImageTopics">刷新话题列表</el-button>
            </div>
            <div class="camera-view" style="margin-top: 8px">
              <img
                v-if="cameraImage"
                :src="cameraImage"
                alt="Camera Feed"
                class="camera-img"
              />
              <div v-else class="camera-placeholder">
                <el-icon :size="48"><VideoCamera /></el-icon>
                <span>{{ cameraTopic ? '等待画面...' : '请选择图像话题' }}</span>
              </div>
            </div>
            <div v-if="cameraConnected" class="info-row" style="margin-top: 8px">
              <span>状态</span>
              <span class="info-value" style="color: #67c23a">接收中 ({{ cameraTopic }})</span>
            </div>
          </div>

          <div class="panel-section teleop-section">
            <h4>手动控制</h4>

            <!-- 十字方向键 -->
            <div class="dpad">
              <el-button
                class="dpad-btn dpad-up"
                :class="{ 'dpad-active': currentLinear === 'up' }"
                @mousedown.prevent="pressLinear('up')"
                @mouseup.prevent="releaseLinear"
                @mouseleave="releaseLinear"
                @touchstart.prevent="pressLinear('up')"
                @touchend.prevent="releaseLinear"
              >▲ 前</el-button>
              <el-button
                class="dpad-btn dpad-left"
                :class="{ 'dpad-active': currentAngular === 'left' }"
                @mousedown.prevent="pressAngular('left')"
                @mouseup.prevent="releaseAngular"
                @mouseleave="releaseAngular"
                @touchstart.prevent="pressAngular('left')"
                @touchend.prevent="releaseAngular"
              >◀ 左</el-button>
              <el-button
                class="dpad-btn dpad-stop"
                type="danger"
                @mousedown.prevent="stopTeleop"
                @touchstart.prevent="stopTeleop"
              >■ 停止</el-button>
              <el-button
                class="dpad-btn dpad-right"
                :class="{ 'dpad-active': currentAngular === 'right' }"
                @mousedown.prevent="pressAngular('right')"
                @mouseup.prevent="releaseAngular"
                @mouseleave="releaseAngular"
                @touchstart.prevent="pressAngular('right')"
                @touchend.prevent="releaseAngular"
              >右 ▶</el-button>
              <el-button
                class="dpad-btn dpad-down"
                :class="{ 'dpad-active': currentLinear === 'down' }"
                @mousedown.prevent="pressLinear('down')"
                @mouseup.prevent="releaseLinear"
                @mouseleave="releaseLinear"
                @touchstart.prevent="pressLinear('down')"
                @touchend.prevent="releaseLinear"
              >▼ 后</el-button>
            </div>

            <!-- 速度调节滑块 -->
            <div class="slider-group">
              <div class="slider-row">
                <span class="slider-label">线速度上限</span>
                <el-slider
                  v-model="linearSpeed"
                  :min="0"
                  :max="2"
                  :step="0.05"
                  :format-tooltip="(v: number) => v.toFixed(2) + ' m/s'"
                  size="small"
                  show-input
                />
              </div>
              <div class="slider-row">
                <span class="slider-label">角速度上限</span>
                <el-slider
                  v-model="angularSpeed"
                  :min="0"
                  :max="3"
                  :step="0.05"
                  :format-tooltip="(v: number) => v.toFixed(2) + ' rad/s'"
                  size="small"
                  show-input
                />
              </div>
            </div>

            <div class="info-row" style="margin-top: 6px">
              <span>速度话题</span>
              <el-select
                v-model="velTopicName"
                size="small"
                filterable
                allow-create
                default-first-option
                class="vel-topic-select"
                @change="onVelTopicChange"
              >
                <el-option v-for="t in velTopicCandidates" :key="t" :label="t" :value="t" />
              </el-select>
            </div>

            <div class="info-row">
              <span>话题状态</span>
              <span class="info-value" :style="{ color: robotStore.status.connected ? '#67c23a' : '#f56c6c' }">
                {{ robotStore.status.connected ? '已连接（可下发）' : '未连接' }}
              </span>
            </div>

            <div class="info-row">
              <span>键盘</span>
              <span class="info-value">W/A/S/D 或 方向键，空格停止</span>
            </div>
          </div>
        </template>

      </template>

      <!-- ==================== 地图处理（画笔/橡皮擦 修补栅格地图）—— 建图页始终显示，地图页仅“编辑地图”二级 ==================== -->
      <div
        v-if="isMapEditPage && (mapStore.activeTool !== 'map' || mapStore.currentMapTab === 'edit')"
        class="panel-section"
      >
        <h4>编辑地图</h4>

        <div class="btn-group map-tool-group">
          <el-button
            size="small"
            :type="mapStore.mapEditTool === 'pencil' ? 'primary' : 'default'"
            @click="mapStore.setMapEditTool('pencil')"
          ><el-icon><Edit /></el-icon> 画笔</el-button>
          <el-button
            size="small"
            :type="mapStore.mapEditTool === 'eraser' ? 'success' : 'default'"
            @click="mapStore.setMapEditTool('eraser')"
          ><el-icon><Delete /></el-icon> 橡皮擦</el-button>
          <el-button
            size="small"
            :type="mapStore.mapEditTool === 'none' ? 'danger' : 'default'"
            @click="mapStore.setMapEditTool('none')"
          ><el-icon><Close /></el-icon> 关闭</el-button>
        </div>

        <div class="map-edit-size">
          <div class="slider-row">
            <span class="slider-label">工具尺寸</span>
            <el-slider
              v-model="mapStore.brushSize"
              :min="1"
              :max="5"
              :step="2"
              :marks="{ 1: '1', 3: '3', 5: '5' }"
              size="small"
            />
          </div>

          <div class="map-edit-actions">
            <el-button
              class="undo-btn"
              size="small"
              :disabled="!mapStore.canUndoMap"
              @click="mapStore.undoMapEdit()"
            >↩ 撤销</el-button>
            <el-button
              class="save-btn"
              size="small"
              type="primary"
              :loading="savingMap"
              @click="saveMapEdit"
            >💾 保存修补地图</el-button>
          </div>

          <div class="map-edit-info">
            <div class="info-row">
              <span>地图尺寸</span>
              <span class="info-value">{{ mapStore.mapBuffer.width }}×{{ mapStore.mapBuffer.height }} · {{ mapStore.mapBuffer.resolution }}m</span>
            </div>
            <div class="info-row">
              <span>编辑状态</span>
              <span class="info-value" :style="{ color: mapStore.mapEditActive ? '#e6a23c' : '#909399' }">
                {{ mapStore.mapEditActive ? (mapStore.mapEditTool === 'pencil' ? '画笔涂抹中' : '橡皮擦除中') : '未编辑' }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- ==================== 导航（巡检任务 + 航点列表） ==================== -->
      <template v-if="mapStore.activeTool === 'navigation'">
        <!-- 巡检任务 -->
        <div v-if="robotStore.status.connected" class="panel-section">
          <h4>巡检任务</h4>
          <div class="status-tag-row">
            <el-tag
              :type="statusTagType"
              size="small"
              effect="dark"
            >{{ navStore.inspectionStatusText }}</el-tag>
          </div>
          <div class="btn-group" style="margin-top: 8px">
            <el-button
              size="small"
              :type="navStore.isAddingMode ? 'warning' : 'default'"
              :disabled="navStore.isRunning || navStore.isPausedState"
              @click="navStore.onAddWaypoints()"
            >📍 添加航点</el-button>
            <el-button
              size="small"
              type="danger"
              v-if="navStore.isRunning"
              @click="navStore.onStopInspection()"
            >⏹ 终止</el-button>
            <el-button
              size="small"
              type="success"
              v-if="navStore.isAddingMode"
              @click="navStore.onCompleteWaypoints()"
            >✅ 完成添加</el-button>
          </div>
          <div class="btn-group" style="margin-top: 6px">
            <el-button
              size="small"
              type="danger"
              :disabled="!navStore.waypointList.length"
              @click="handleClearInspectionWaypoints"
            >🗑 清空航点</el-button>
            <el-button
              size="small"
              :type="navStore.isInitialPoseMode ? 'success' : 'default'"
              @click="toggleInitialPoseMode"
            >🎯 初始定位</el-button>
            <el-button
              size="small"
              type="primary"
              :disabled="!navStore.isSaved && !navStore.isPausedState"
              @click="navStore.onStartInspection()"
              v-if="!navStore.isRunning"
            >▶ 开始巡检</el-button>
            <el-button
              size="small"
              type="warning"
              v-if="navStore.isRunning"
              @click="navStore.onPauseInspection()"
            >⏸ 暂停</el-button>
          </div>
          <div class="info-row" style="margin-top: 8px">
            <span>航点总数</span>
            <span class="info-value">{{ navStore.waypointList.length }}</span>
          </div>
          <div class="info-row">
            <span>状态</span>
            <span class="info-value" :style="{ color: statusColor }">{{ navStore.currentStatus }}</span>
          </div>
        </div>

        <!-- 航点列表 -->
        <div class="panel-section">
          <h4>航点列表</h4>
          <div v-if="navStore.waypointList.length === 0" class="empty-state">
            <span>暂无航点</span>
          </div>
          <div v-else class="waypoint-list">
            <div v-for="(wp, idx) in navStore.waypointList" :key="idx" class="waypoint-item">
              <span class="wp-index">{{ idx + 1 }}</span>
              <span class="wp-coord">X {{ wp.x.toFixed(2) }}</span>
              <span class="wp-coord">Y {{ wp.y.toFixed(2) }}</span>
              <span class="wp-yaw">{{ (wp.yaw * 180 / Math.PI).toFixed(0) }}°</span>
              <el-button size="small" type="danger" @click="removeWaypointFromList(idx)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </div>

        <!-- 预设航线库 -->
        <div class="panel-section">
          <h4>预设航线库</h4>
          
          <!-- 保存当前航线 -->
          <div v-if="navStore.isSaved || navStore.waypointList.length > 0" class="save-route-row">
            <el-input
              v-model="newRouteName"
              size="small"
              placeholder="输入航线名称（如：一楼大厅巡检线）"
              class="route-name-input"
            />
            <el-button
              size="small"
              type="primary"
              :disabled="!newRouteName.trim()"
              @click="handleSaveRoute"
            >保存当前航线</el-button>
          </div>

          <!-- 航线列表 -->
          <div v-if="navStore.savedRoutes.length === 0" class="empty-state" style="margin-top: 8px">
            <span>暂无保存的航线</span>
          </div>
          <div v-else class="route-list">
            <div v-for="route in navStore.savedRoutes" :key="route.id" class="route-item">
              <div class="route-info">
                <span class="route-name">{{ route.name }}</span>
                <span class="route-meta">{{ route.waypoints.length }} 个航点 · {{ route.createdAt }}</span>
              </div>
              <div class="route-actions">
                <el-button size="small" type="success" @click="handleLoadRoute(route.id)">使用</el-button>
                <el-button size="small" type="danger" @click="handleDeleteRoute(route.id)">删除</el-button>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ==================== 日志 ==================== -->
      <template v-if="mapStore.activeTool === 'log'">
        <div class="panel-section">
          <h4>当前状态</h4>
          <div class="status-grid">
            <div class="status-item">
              <span class="status-label">连接状态</span>
              <el-tag :type="robotStore.status.connected ? 'success' : 'danger'" size="small" effect="dark">
                {{ robotStore.status.connected ? '在线' : '离线' }}
              </el-tag>
            </div>
            <div class="status-item">
              <span class="status-label">建图状态</span>
              <el-tag :type="mapStore.mapping ? 'warning' : 'info'" size="small" effect="plain">
                {{ mapStore.mapping ? '正在建图' : '未建图' }}
              </el-tag>
            </div>
            <div class="status-item">
              <span class="status-label">导航状态</span>
              <el-tag :type="navStore.navStatus.active ? 'primary' : 'info'" size="small" effect="plain">
                {{ navStore.navStatus.active ? '运行中' : '停止' }}
              </el-tag>
            </div>
            <div class="status-item">
              <span class="status-label">急停</span>
              <el-tag
                v-if="robotStore.safetyStopped"
                type="danger"
                size="small"
                effect="dark"
                class="e-stop-tag"
              >⚠ 已急停(危险)</el-tag>
              <el-tag v-else type="success" size="small" effect="plain">正常</el-tag>
            </div>
            <div class="status-item">
              <span class="status-label">巡检状态</span>
              <el-tag :type="statusTagType" size="small" effect="dark" class="inspection-tag">
                {{ navStore.inspectionStatusText }}
              </el-tag>
            </div>
            <div class="status-item">
              <span class="status-label">航点总数</span>
              <el-tag type="info" size="small" effect="plain">{{ navStore.waypointList.length }} 个</el-tag>
            </div>
          </div>
        </div>
        <div class="panel-section">
          <h4>系统日志</h4>
          <div class="log-list" ref="logListRef">
            <div v-for="(log, idx) in navStore.consoleLogs" :key="idx" class="log-item" :class="logLevelClass(log)">
              <span class="log-text">{{ log }}</span>
            </div>
          </div>
        </div>
      </template>

      <!-- ==================== 设置 ==================== -->
      <template v-if="mapStore.activeTool === 'settings'">
        <div class="panel-section">
          <h4>网络连接</h4>
          <div class="setting-item">
            <span>IP 地址</span>
            <el-input v-model="robotStore.ip" size="small" class="setting-input" />
          </div>
          <div class="setting-item">
            <span>端口</span>
            <el-input v-model.number="robotStore.port" size="small" class="setting-input" />
          </div>
          <div class="setting-item">
            <span>自动重连</span>
            <el-switch v-model="autoReconnect" size="small" />
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

      <!-- ==================== 地图（二级菜单联动） ==================== -->
      <template v-if="mapStore.activeTool === 'map'">
        <!-- 二级【地图信息】 -->
        <div v-if="mapStore.currentMapTab === 'info'" class="panel-section">
          <h4>地图信息</h4>
          <div class="info-row">
            <span>名称</span>
            <span class="info-value">{{ mapStore.currentMap.name }}</span>
          </div>
          <div class="info-row">
            <span>分辨率</span>
            <span class="info-value">{{ mapStore.currentMap.resolution.toFixed(2) }} m/cell</span>
          </div>
          <div class="info-row">
            <span>尺寸</span>
            <span class="info-value">{{ mapStore.currentMap.width }}x{{ mapStore.currentMap.height }}</span>
          </div>
          <div class="info-row">
            <span>建图状态</span>
            <span class="info-value" :style="{ color: mapStore.mapping ? '#67c23a' : '#909399' }">{{ mapStore.mapping ? '运行中' : '停止' }}</span>
          </div>
        </div>

        <!-- 二级【连接状态】 -->
        <div v-if="mapStore.currentMapTab === 'connection'" class="panel-section">
          <h4>连接状态</h4>
          <div class="info-row">
            <span>ROS Bridge</span>
            <span :style="{ color: robotStore.status.connected ? '#67c23a' : '#f56c6c' }">
              {{ robotStore.status.connected ? '在线' : '离线' }}
            </span>
          </div>
          <div class="info-row">
            <span>端点</span>
            <span class="info-value">{{ robotStore.ip }}:{{ robotStore.port }}</span>
          </div>
        </div>

        <!-- 二级【编辑地图】无额外内容时（地图处理工具块已在上方按 currentMapTab==='edit' 渲染）的占位提示 -->
        <div v-if="mapStore.currentMapTab === 'edit' && !mapStore.mapEditActive" class="panel-hint">
          选择左侧「编辑地图」中的画笔 / 橡皮擦工具即可修补当前栅格地图。
        </div>
      </template>

    </div>

    <div class="panel-footer">
      <button class="start-task-btn" @click="navStore.onStartInspection()">
        <el-icon><VideoPlay /></el-icon>
        开始任务
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, shallowRef, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { Delete, VideoCamera, VideoPlay } from '@element-plus/icons-vue'
import { useMapStore } from '@/stores/map'
import { useRobotStore } from '@/stores/robot'
import { useNavigationStore } from '@/stores/navigation'
import { ElMessage } from 'element-plus'
import { rosApi, VEL_TOPIC_NAME } from '@/api/ros'
import type { ActiveTool } from '@/types'

const mapStore = useMapStore()
const robotStore = useRobotStore()
const navStore = useNavigationStore()

const panelLabels: Record<ActiveTool, string> = {
  map: '地图',
  mapping: '建图',
  navigation: '导航',
  taskchain: '任务链',
  log: '日志',
  settings: '设置',
}

const mapTabLabels: Record<'edit' | 'info' | 'connection', string> = {
  edit: '编辑地图',
  info: '地图信息',
  connection: '连接状态',
}

const mappingTabLabels: Record<'settings' | 'manage' | 'control', string> = {
  settings: '地图设置',
  manage: '地图管理',
  control: '实时控制',
}

const panelTitle = computed(() => {
  if (mapStore.activeTool === 'map') return mapTabLabels[mapStore.currentMapTab]
  if (mapStore.activeTool === 'mapping') return mappingTabLabels[mapStore.currentMappingTab]
  return panelLabels[mapStore.activeTool] || '建图'
})

// 仅“建图”页面（activeTool === 'mapping'）显示手动控制模块
const isMappingPage = computed(() => mapStore.activeTool === 'mapping')

// 地图处理（画笔/橡皮擦）模块仅在“地图”页面（二级【编辑地图】）显示
const isMapEditPage = computed(() => mapStore.activeTool === 'map')

// 保存修补后的栅格地图到后端
const savingMap = ref(false)
async function saveMapEdit() {
  savingMap.value = true
  try {
    await mapStore.saveEditedMap()
    ElMessage.success('修补地图已保存，正在重载地图…')
    // 后端已触发 map_server 重载新地图。保存成功即视为编辑结束，
    // 释放编辑锁；重载锁由 mapReloading 控制，给小车留出重载时间后自动释放，
    // 避免长时间拦截新地图（若重载失败也能在超时后恢复订阅）。
    await new Promise((resolve) => setTimeout(resolve, 2500))
    mapStore.finishMapReload()
  } catch (err) {
    // 保存失败时也要释放锁，恢复正常的地图话题订阅
    mapStore.finishMapReload()
    ElMessage.error(`保存失败：${(err as Error).message}`)
  } finally {
    savingMap.value = false
  }
}

const selectedMap = ref('')
const autoReconnect = ref(true)
const logListRef = ref<HTMLDivElement>()
const newRouteName = ref('')

// ===== Mapping =====

function handleStartMapping() {
  mapStore.startMapping()
  ElMessage.success('建图已开始')
}

function handleSaveMap() {
  const name = mapStore.currentMap.name + '_new'
  mapStore.saveMap(name)
  ElMessage.success('地图已保存: ' + name)
}

// 触发后端真实建图命令链：pcd2pgm 转换 -> map_saver_cli 存图
// （后端 inspection_controller.py 监听 /map_convert_cmd，返回 /map_convert_status）
function handleSaveGridMap() {
  if (!robotStore.status.connected) {
    ElMessage.warning('请先连接 ROS Bridge 后再保存栅格地图')
    return
  }
  rosApi.publishTopic('/map_convert_cmd', 'std_msgs/msg/String', {
    data: JSON.stringify({ cmd: 'save_map' }),
  })
  ElMessage.info('已发送建图指令，后端正在执行 pcd2pgm -> map_saver ...')
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

// ===== Navigation / Waypoint =====

function handleClearInspectionWaypoints() {
  navStore.waypointList.splice(0, navStore.waypointList.length)
  navStore.addLog('系统提示: 已清空所有航点')
  navStore.updateInspectionUI()
}

function toggleInitialPoseMode() {
  if (navStore.isInitialPoseMode) {
    navStore.exitInitialPoseMode()
  } else {
    navStore.enterInitialPoseMode()
  }
}

function removeWaypointFromList(index: number) {
  navStore.waypointList.splice(index, 1)
  navStore.addLog(`已删除航点 #${index + 1}`)
  navStore.updateInspectionUI()
}

function handleSaveRoute() {
  if (!newRouteName.value.trim()) {
    ElMessage.warning('请输入航线名称')
    return
  }
  const result = navStore.saveCurrentRoute(newRouteName.value.trim())
  if (result) {
    ElMessage.success(`航线 "${newRouteName.value.trim()}" 已保存`)
    newRouteName.value = ''
  }
}

function handleLoadRoute(id: string) {
  const success = navStore.loadRoute(id)
  if (success) {
    ElMessage.success('航线已加载')
  }
}

function handleDeleteRoute(id: string) {
  const success = navStore.deleteRoute(id)
  if (success) {
    ElMessage.success('航线已删除')
  }
}

const statusTagType = computed(() => {
  switch (navStore.currentStatus) {
    case 'IDLE': return 'info'
    case 'ADDING': return 'warning'
    case 'SAVED': return 'success'
    case 'RUNNING': return 'primary'
    case 'PAUSED': return 'warning'
    default: return 'info'
  }
})

const statusColor = computed(() => {
  switch (navStore.currentStatus) {
    case 'IDLE': return '#909399'
    case 'ADDING': return '#e6a23c'
    case 'SAVED': return '#67c23a'
    case 'RUNNING': return '#409eff'
    case 'PAUSED': return '#ef6c00'
    default: return '#909399'
  }
})

// ===== Camera (WebWorker offloaded, 话题自选) =====

const presetImageTopics = ['/image_raw', '/camera/color/image_raw', '/compressed_image']
const availableImageTopics = ref<{ name: string; type: string }[]>([])
const cameraTopic = ref('')
const cameraImage = shallowRef<string | null>(null)
const cameraConnected = ref(false)
const currentCameraTopic = ref('')

const cameraTopicOptions = computed(() => {
  const set = new Set<string>(presetImageTopics)
  availableImageTopics.value.forEach((t) => set.add(t.name))
  return Array.from(set)
})

let cameraWorker: Worker | null = null

function initCameraWorker() {
  if (cameraWorker) return
  cameraWorker = new Worker(new URL('@/workers/camera.worker.ts', import.meta.url), { type: 'module' })
  cameraWorker.onmessage = (e: MessageEvent) => {
    const { type, data } = e.data
    if (type === 'frame-ready') {
      cameraImage.value = data
      if (!cameraConnected.value) cameraConnected.value = true
    }
  }
}

function getImageMessageType(topic: string): string {
  return /compressed/i.test(topic)
    ? 'sensor_msgs/msg/CompressedImage'
    : 'sensor_msgs/msg/Image'
}

// 将 sensor_msgs/msg/Image（原始字节）转换为可显示的 data URL
function buildRawImageUrl(msg: any): string | null {
  try {
    const width = msg.width
    const height = msg.height
    const encoding: string = (msg.encoding || 'rgb8').toLowerCase()
    const raw = msg.data && Array.isArray(msg.data.data) ? msg.data.data : (Array.isArray(msg.data) ? msg.data : null)
    if (!width || !height || !raw) return null

    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')!
    const imgData = ctx.createImageData(width, height)
    const step = encoding.includes('rgba') || encoding.includes('bgra') ? 4 : 3

    for (let i = 0, j = 0; i + 2 < raw.length; i += step, j += 4) {
      let r: number, g: number, b: number
      if (encoding.includes('bgr')) {
        b = raw[i]; g = raw[i + 1]; r = raw[i + 2]
      } else {
        r = raw[i]; g = raw[i + 1]; b = raw[i + 2]
      }
      imgData.data[j] = r
      imgData.data[j + 1] = g
      imgData.data[j + 2] = b
      imgData.data[j + 3] = 255
    }
    ctx.putImageData(imgData, 0, 0)
    return canvas.toDataURL('image/jpeg')
  } catch (e) {
    console.error('[Camera] 原始图像转换失败:', e)
    return null
  }
}

function refreshImageTopics() {
  rosApi.getTopics((topics) => {
    availableImageTopics.value = topics.filter(t =>
      /compressedimage/i.test(t.type) ||
      /image/i.test(t.type) ||
      /\/image_raw/i.test(t.name) ||
      /\/compressed/i.test(t.name)
    )
  })
  ElMessage.info('话题列表已刷新')
}

// 切换话题：先 unsubscribe 旧实例，再订阅新话题
function onImageTopicChange(topicName: string) {
  if (currentCameraTopic.value) {
    rosApi.unsubscribeTopic(currentCameraTopic.value)
  }
  cameraImage.value = null
  cameraConnected.value = false
  currentCameraTopic.value = ''
  if (!topicName) return

  const messageType = getImageMessageType(topicName)
  initCameraWorker()

  rosApi.subscribeTopic(topicName, messageType, (msg: any) => {
    if (!msg) return
    if (messageType === 'sensor_msgs/msg/CompressedImage') {
      if (msg.data && cameraWorker) {
        cameraWorker.postMessage({ type: 'frame', data: msg.data })
      }
    } else {
      const url = buildRawImageUrl(msg)
      if (url) cameraImage.value = url
    }
    if (!cameraConnected.value) cameraConnected.value = true
  })

  currentCameraTopic.value = topicName
  cameraConnected.value = true
}

// ===== 手动控制 (Teleop) =====

const linearSpeed = ref(0.5)
const angularSpeed = ref(1.0)

// 线/角速度独立维度：前后互斥、左右互斥，但两者可同时激活（复合控制）
type LinearDir = 'up' | 'down' | null
type AngularDir = 'left' | 'right' | null
const currentLinear = ref<LinearDir>(null)
const currentAngular = ref<AngularDir>(null)

// 仅转向（无线速度）时注入的微小基础前进速度，用于激活轮胎转向机制
const MIN_TURN_LINEAR = 0.05

// 可配置的速度话题（默认 /cmd_vel，真实底盘常需 /cmd_vel_teleop 等 mux 输入端）
const velTopicName = ref(VEL_TOPIC_NAME)
const velTopicCandidates = ref<string[]>([VEL_TOPIC_NAME, '/cmd_vel_teleop', '/twist_mux/input/teleop', '/cmd_vel_joy'])

let teleopTimer: number | null = null
const TELEOP_HZ = 15

// 构造 ROS 2 标准 Twist 消息（linear/angular 均为完整三维向量）
// 所有数值用 Number() 强制转数值，杜绝 Vue 响应式 Proxy / 滑块字符串导致
// roslibjs 序列化后 ROS 2 端反序列化字段类型不匹配而丢弃消息。
function buildTwist(linear: number, angular: number) {
  const lx = Number(linear)
  const az = Number(angular)
  // [控制台抓包] 点左/右时，确认 angular 是否有明显的正/负数值输出
  console.log(`[Teleop] buildTwist - 线速度 linear.x: ${lx}, 角速度 angular.z: ${az}`)
  return {
    linear: { x: isNaN(lx) ? 0 : lx, y: 0.0, z: 0.0 },
    angular: { x: 0.0, y: 0.0, z: isNaN(az) ? 0 : az },
  }
}

// 使用已连接的 ros 实例发布速度到当前配置的话题
function publishCmdVel(linear: number, angular: number) {
  if (!robotStore.status.connected) {
    console.error('[Teleop] 拒绝发布：ROS Bridge 未连接')
    return
  }
  const twist = buildTwist(linear, angular)
  console.log(`[Teleop] 发布速度 -> ${velTopicName.value} (geometry_msgs/msg/Twist):`, {
    linear: twist.linear,
    angular: twist.angular,
  })
  rosApi.publishTopic(velTopicName.value, 'geometry_msgs/msg/Twist', twist)
}

// 合成当前线/角速度并下发；前后与左右独立叠加，互不影响
function updateMovement() {
  let vx = 0
  let wz = 0

  // 1. 线速度（前后互斥）
  if (currentLinear.value === 'up') vx = linearSpeed.value
  else if (currentLinear.value === 'down') vx = -linearSpeed.value

  // 2. 角速度（左右互斥）
  if (currentAngular.value === 'left') wz = angularSpeed.value
  else if (currentAngular.value === 'right') wz = -angularSpeed.value

  // 🔴 关键修复：仅转向、无前进时，注入微小基础前进速度，驱动轮胎转向
  if (vx === 0 && wz !== 0) {
    vx = MIN_TURN_LINEAR
  }

  console.log(
    `[运动复合发送] 状态: 前后=${currentLinear.value}, 左右=${currentAngular.value} -> 实发 linear.x=${vx}, angular.z=${wz}`
  )
  publishCmdVel(vx, wz)
}

// 确保以固定频率持续下发当前合成状态（ROS 需持续收到指令，否则按超时停车）
function ensureTeleopTimer() {
  if (teleopTimer) return
  updateMovement()
  teleopTimer = window.setInterval(updateMovement, 1000 / TELEOP_HZ)
}

function pressLinear(dir: 'up' | 'down') {
  if (!robotStore.status.connected) {
    ElMessage.warning('请先连接到 ROS Bridge')
    return
  }
  // 前后互斥：设置即覆盖（'up' 清除 'down'，反之亦然）
  currentLinear.value = dir
  ensureTeleopTimer()
}

function releaseLinear() {
  if (currentLinear.value === null) return
  currentLinear.value = null
  if (currentAngular.value === null) stopTeleop()
  else updateMovement()
}

function pressAngular(dir: 'left' | 'right') {
  if (!robotStore.status.connected) {
    ElMessage.warning('请先连接到 ROS Bridge')
    return
  }
  // 左右互斥：设置即覆盖
  currentAngular.value = dir
  ensureTeleopTimer()
}

function releaseAngular() {
  if (currentAngular.value === null) return
  currentAngular.value = null
  if (currentLinear.value === null) stopTeleop()
  else updateMovement()
}

function sendZeroVelocity() {
  publishCmdVel(0, 0)
}

function stopTeleop() {
  console.log('[Teleop] stopTeleop -> 下发停止 (0,0) 到', velTopicName.value)
  currentLinear.value = null
  currentAngular.value = null
  if (teleopTimer) {
    clearInterval(teleopTimer)
    teleopTimer = null
  }
  // 连续下发 3 帧清零指令，防止单帧网络丢包导致后端漏收“停止”而产生物理漂移
  sendZeroVelocity()
  window.setTimeout(sendZeroVelocity, 60)
  window.setTimeout(sendZeroVelocity, 120)
}

// 切换话题：立即下发 0 速即可，无需探测订阅者（roslibjs 无稳定的 getNumSubscribers 实现）
function onVelTopicChange(name: string) {
  velTopicName.value = name
  sendZeroVelocity()
}

// 键盘监听（W/A/S/D 或 方向键，空格停止）
// 注意：绑定在 window 上，即使鼠标点击了面板其它区域/失去焦点也能捕获。
// 仅当焦点在输入框/文本域/下拉框时不拦截，避免影响正常输入。
function isTypingTarget(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null
  if (!t) return false
  const tag = t.tagName
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    t.isContentEditable
  )
}

function handleKeydown(e: KeyboardEvent) {
  // 焦点在输入框时不触发遥控，避免误操控
  if (isTypingTarget(e)) return
  // 键盘监听仅在“建图”页面注册（见 registerTeleopKeys），此处再校验一次防止遗漏
  if (!isMappingPage.value) return
  if (!robotStore.status.connected) return

  const k = e.key.toLowerCase()
  if (k === 'w' || k === 'arrowup') { e.preventDefault(); if (!e.repeat) pressLinear('up') }
  else if (k === 's' || k === 'arrowdown') { e.preventDefault(); if (!e.repeat) pressLinear('down') }
  else if (k === 'a' || k === 'arrowleft') { e.preventDefault(); if (!e.repeat) pressAngular('left') }
  else if (k === 'd' || k === 'arrowright') { e.preventDefault(); if (!e.repeat) pressAngular('right') }
  else if (k === ' ') { e.preventDefault(); stopTeleop() }
}

function handleKeyup(e: KeyboardEvent) {
  if (!isMappingPage.value) return
  if (isTypingTarget(e)) return
  const k = e.key.toLowerCase()
  if (k === 'w' || k === 'arrowup') releaseLinear()
  else if (k === 's' || k === 'arrowdown') releaseLinear()
  else if (k === 'a' || k === 'arrowleft') releaseAngular()
  else if (k === 'd' || k === 'arrowright') releaseAngular()
}

// ===== 生命周期 / 清理 =====

// 仅在“建图”页面注册键盘遥控监听，离开页面即移除，避免后台误操控
function registerTeleopKeys() {
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('keyup', handleKeyup)
  window.addEventListener('blur', stopTeleop)
}

function unregisterTeleopKeys() {
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('keyup', handleKeyup)
  window.removeEventListener('blur', stopTeleop)
  stopTeleop()
}

watch(() => mapStore.activeTool, (tool) => {
  if (tool !== 'mapping') {
    if (currentCameraTopic.value) rosApi.unsubscribeTopic(currentCameraTopic.value)
    currentCameraTopic.value = ''
    cameraImage.value = null
    cameraConnected.value = false
    unregisterTeleopKeys()
  } else {
    registerTeleopKeys()
  }
})

onMounted(() => {
  // 仅当当前处于建图页面时才挂载键盘遥控
  if (isMappingPage.value) registerTeleopKeys()
})

onBeforeUnmount(() => {
  unregisterTeleopKeys()
  if (currentCameraTopic.value) rosApi.unsubscribeTopic(currentCameraTopic.value)
})

function logLevelClass(log: string): string {
  if (log.includes('[ERROR]') || log.includes('[FATAL]')) return 'log-error'
  if (log.includes('[WARN]')) return 'log-warn'
  return ''
}

// Auto-scroll log to bottom
watch(() => navStore.consoleLogs.length, () => {
  nextTick(() => {
    const el = logListRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
})

// 确保导航 store 订阅巡检状态话题
navStore.subscribeInspectionStatus()
watch(() => robotStore.status.connected, (connected) => {
  if (connected) {
    setTimeout(() => navStore.subscribeInspectionStatus(), 500)
  }
})
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
  box-sizing: border-box;
  /* 预留底部安全空间，避免最下方按钮被底部状态栏遮挡 */
  padding-bottom: 8px;
}

.panel-title {
  font-size: 14px;
  font-weight: 700;
  color: $text-primary;
  padding: 12px 16px 10px;
  border-bottom: 1px solid $border-color;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 12px 24px;
}

.panel-section {
  margin-bottom: 14px;
  padding: 14px 4px;

  h4 {
    font-size: 13px;
    font-weight: 600;
    color: $text-primary;
    margin-bottom: 12px;
    padding-left: 9px;
    border-left: 3px solid $theme-primary;
    line-height: 1.2;
  }
}

// 仅显示单一子模块的地图页面：去除分割线，增加上下留白，营造呼吸感
.panel-hint {
  padding: 18px 8px;
  color: $text-muted;
  font-size: 12px;
  line-height: 1.6;
  background: $bg-card;
  border-radius: 6px;
}

.btn-group {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;

  .el-button {
    flex: 1;
    min-width: 0;
    background: $bg-card;
    border-color: $border-color;
    color: $text-primary;
    font-weight: 500;
    border-radius: 6px;
    height: 32px;
    transition: all $transition;

    &.el-button--primary {
      background: $btn-primary-bg;
      border-color: $btn-primary-bg;
      color: #ffffff;

      &:hover {
        background: $theme-primary-hover;
        border-color: $theme-primary-hover;
      }
    }

    &.el-button--danger {
      background: var(--bg-card);
      border-color: #f56c6c;
      color: #f56c6c;

      &:hover {
        background: rgba(245, 108, 108, 0.1);
      }
    }

    &.el-button--success {
      background: var(--bg-card);
      border-color: #67c23a;
      color: #67c23a;

      &:hover {
        background: rgba(103, 194, 58, 0.1);
      }
    }

    &.el-button--warning {
      background: var(--bg-card);
      border-color: #e6a23c;
      color: #e6a23c;

      &:hover {
        background: rgba(230, 162, 60, 0.1);
      }
    }

    &:disabled {
      background: var(--bg-card-2);
      border-color: var(--border-color);
      color: var(--text-muted);
      cursor: not-allowed;
    }
  }
}

// 地图处理工具组：取消“等宽挤压”，让按钮按内容自适应宽度并在空间不足时整行换行，
// 杜绝窄屏下文字折行 / 重叠错位。
.map-tool-group {
  .el-button {
    flex: 0 1 auto;
    min-width: auto;
    white-space: nowrap;

    .el-icon {
      margin-right: 4px;
      vertical-align: -2px;
    }
  }
}

// ===== 编辑地图：工具尺寸模块（消除滑块刻度与按钮的纵向重叠） =====
.map-edit-size {
  display: flex;
  flex-direction: column;
  gap: 0;

  // 第一层：标题 + 滑块（滑块刻度数字 / Tooltip 均为组件库绝对定位元素，
  // 必须强行用上下外边距把上、下两组按钮推开，撑出垂直安全隔离带）
  .slider-row {
    display: flex;
    flex-direction: column;
    // 核心：上下垂直安全区 —— 上方推离“画笔/橡皮擦/关闭”按钮，给弹出的数字气泡留空间；
    // 下方压开“撤销/保存”按钮，给刻度数字留呼吸感。
    margin-top: 24px;
    margin-bottom: 32px;
    padding: 0 8px;
    position: relative;

    .slider-label {
      font-size: 12px;
      color: $text-secondary;
      margin-bottom: 12px;
    }

    :deep(.el-slider) {
      // 取消任何过矮的固定高度限制，让滑块高度自适应，
      // 底部刻度线与数字自然垂直舒展，不再紧贴轨道。
      height: auto !important;
      margin: 0;

      .el-slider__runway {
        margin-top: 16px;
        margin-bottom: 16px;
      }

      .el-slider__marks-text {
        margin-top: 8px;
        font-size: 11px;
        color: $text-muted;
      }
    }
  }

  // 第三层：撤销 / 保存按钮组 —— 并排拉伸、主次分明，强制回归正常文档流
  .map-edit-actions {
    display: flex;
    gap: 12px;
    width: 100%;
    position: relative; /* 确保不是 absolute/fixed，回到正常流 */
    clear: both;
    margin-top: 16px;

    .undo-btn {
      flex: 0 0 38%;
      background: var(--bg-card-2);
      border-color: var(--border-color);
      color: var(--text-secondary);

      &:hover:not(:disabled) {
        background: var(--theme-primary-soft);
        border-color: var(--theme-primary);
        color: var(--theme-primary);
      }

      &:disabled {
        background: var(--bg-card-2);
        border-color: var(--border-color);
        color: var(--text-muted);
        cursor: not-allowed;
      }
    }

    .save-btn {
      flex: 1 1 62%;
    }
  }

  // 信息区：与上方按钮拉开间距，用淡虚线分隔，层次分明
  .map-edit-info {
    margin-top: 20px;
    padding-top: 14px;
    border-top: 1px dashed $border-color;
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
    color: $theme-primary;
    font-weight: 500;
  }
}

.status-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.status-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 0;

  .status-label {
    color: $text-secondary;
    font-size: 13px;
  }
}

.e-stop-tag {
  animation: pulse-bg 1.2s ease-in-out infinite;
}

.inspection-tag {
  min-width: 60px;
  text-align: center;
}

@keyframes pulse-bg {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.empty-state {
  text-align: center;
  padding: 16px;
  color: $text-muted;
  background: $bg-card;
  border-radius: 6px;
}

.waypoint-list {
  max-height: 200px;
  overflow-y: auto;
}

.waypoint-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 6px;
  background: $bg-card;
  border-radius: 4px;
  margin-bottom: 3px;
  font-size: 11px;

  .wp-index {
    font-weight: 700;
    color: $theme-primary;
    min-width: 18px;
    text-align: center;
  }

  .wp-coord {
    color: $text-secondary;
    font-family: monospace;
  }

  .wp-yaw {
    color: $accent-yellow;
    font-family: monospace;
    min-width: 32px;
    text-align: right;
  }

  .el-button {
    flex: none;
    margin-left: auto;
    width: 22px;
    height: 22px;
    padding: 0;
  }
}

.status-tag-row {
  margin-bottom: 4px;
}

.setting-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  font-size: 13px;
  color: $text-secondary;

  .setting-input {
    width: 140px;
  }
}

.log-list {
  max-height: 350px;
  overflow-y: auto;
  font-family: monospace;
  font-size: 12px;
}

.log-item {
  padding: 2px 8px;
  border-radius: 2px;
  color: $text-secondary;

  &:hover {
    background: $bg-hover;
  }

  &.log-error {
    color: #f56c6c;
    background: rgba(245, 108, 108, 0.06);
  }

  &.log-warn {
    color: #e6a23c;
    background: rgba(230, 162, 60, 0.06);
  }
}

.save-route-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;

  .route-name-input {
    flex: 1;
  }
}

.route-list {
  max-height: 200px;
  overflow-y: auto;
}

.route-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 8px;
  background: $bg-card;
  border-radius: 4px;
  margin-bottom: 4px;

  .route-info {
    flex: 1;
    min-width: 0;

    .route-name {
      display: block;
      font-size: 13px;
      font-weight: 500;
      color: $text-primary;
      margin-bottom: 2px;
    }

    .route-meta {
      display: block;
      font-size: 11px;
      color: $text-muted;
    }
  }

  .route-actions {
    display: flex;
    gap: 4px;
    flex-shrink: 0;

    .el-button {
      padding: 0 8px;
      height: 24px;
      font-size: 11px;
    }
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
  object-fit: contain;
}

.camera-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #999;
}

// ===== 模块 B：手动控制 =====
.vel-topic-select {
  width: 160px;
}

.dpad {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-template-areas:
    '.    up    .'
    'left stop  right'
    '.    down  .';
  gap: 6px;
  margin-top: 4px;

  .dpad-btn {
    margin: 0;
    height: 40px;
    font-weight: 600;
    background: var(--bg-card-2) !important;
    border-color: var(--border-color) !important;
    color: $text-secondary !important;

    &:hover {
      background: var(--bg-hover) !important;
      color: $text-primary !important;
    }
  }

  .dpad-up { grid-area: up; }
  .dpad-down { grid-area: down; }
  .dpad-left { grid-area: left; }
  .dpad-right { grid-area: right; }

  .dpad-stop {
    grid-area: stop;
    background: $accent-red !important;
    border-color: $accent-red !important;
    color: #ffffff !important;

    &:hover {
      background: #d95454 !important;
      color: #ffffff !important;
    }
  }

  .dpad-active {
    background: $theme-primary !important;
    border-color: $theme-primary !important;
    color: #ffffff !important;
  }
}

.slider-group {
  margin-top: 12px;

  .slider-row {
    display: flex;
    flex-direction: column;
    margin-bottom: 6px;

    .slider-label {
      font-size: 12px;
      color: $text-secondary;
      margin-bottom: 2px;
    }

    .el-slider {
      width: 100%;
    }
  }
}

// ===== 右下角悬浮：开始任务 =====
.panel-footer {
  flex-shrink: 0;
  margin-top: 8px;
  padding: 12px 12px 14px;
  border-top: 1px solid $border-color;
  background: $bg-secondary;
}

.start-task-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  height: 40px;
  border: none;
  border-radius: $radius;
  background: $btn-primary-bg;
  color: #ffffff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;

  .el-icon {
    font-size: 16px;
  }

  &:hover {
    background: $theme-primary-hover;
  }

  &:active {
    background: $theme-primary-active;
  }
}
</style>
