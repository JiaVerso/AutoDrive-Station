<template>
  <aside class="left-toolbar">
    <div class="tool-buttons">
      <button
        v-for="tool in tools"
        :key="tool.id"
        class="tool-btn"
        :class="{ active: mapStore.activeTool === tool.id }"
        :title="tool.label"
        @click="handleToolClick(tool.id)"
      >
        <el-icon :size="20"><component :is="tool.icon" /></el-icon>
        <span class="tool-label">{{ tool.label }}</span>
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { markRaw } from 'vue'
import {
  MapLocation,
  Edit,
  Position,
  Document,
  VideoPlay,
  Share,
  Grid,
  Memo,
  Setting,
} from '@element-plus/icons-vue'
import { useMapStore } from '@/stores/map'
import type { ActiveTool } from '@/types'
import { ElMessage } from 'element-plus'

const mapStore = useMapStore()

function handleToolClick(toolId: ActiveTool) {
  mapStore.activeTool = toolId
  
  if (toolId === 'waypoint') {
    mapStore.setDrawMode('point')
    ElMessage.info('已进入航点绘制模式，点击地图添加航点')
  } else if (toolId === 'path') {
    mapStore.setDrawMode('line')
    ElMessage.info('已进入路径绘制模式，点击地图添加路径点')
  } else {
    mapStore.setDrawMode('none')
  }
}

const tools: { id: ActiveTool; label: string; icon: any }[] = [
  { id: 'map', label: '地图', icon: markRaw(MapLocation) },
  { id: 'mapping', label: '建图', icon: markRaw(Edit) },
  { id: 'localization', label: '定位', icon: markRaw(Position) },
  { id: 'navigation', label: '导航', icon: markRaw(Document) },
  { id: 'waypoint', label: '航点', icon: markRaw(Position) },
  { id: 'path', label: '路径', icon: markRaw(Share) },
  { id: 'camera', label: '摄像头', icon: markRaw(VideoPlay) },
  { id: 'log', label: '日志', icon: markRaw(Memo) },
  { id: 'settings', label: '设置', icon: markRaw(Setting) },
]
</script>

<style lang="scss" scoped>
.left-toolbar {
  width: $left-toolbar-width;
  background: $bg-secondary;
  border-right: 1px solid $border-color;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 0;
}

.tool-buttons {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
}

.tool-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 10px 4px;
  border: none;
  background: transparent;
  color: $text-secondary;
  cursor: pointer;
  transition: all $transition;
  border-radius: 0;

  &:hover {
    background: $bg-hover;
    color: $text-primary;
  }

  &.active {
    background: rgba($accent-blue, 0.15);
    color: $accent-blue;
    border-right: 3px solid $accent-blue;
  }
}

.tool-label {
  font-size: 10px;
  white-space: nowrap;
}
</style>
