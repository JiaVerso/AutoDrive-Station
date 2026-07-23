<template>
  <aside class="left-toolbar">
    <div class="tool-buttons">
      <!-- 地图：可展开的一级菜单（树状） -->
      <div class="tool-tree">
        <button
          class="tool-btn tree-parent"
          :class="{ active: mapStore.activeTool === 'map' }"
          :title="'地图'"
          @click="toggleMapExpand"
        >
          <el-icon :size="20"><MapLocation /></el-icon>
          <span class="tool-label">地图</span>
          <el-icon class="tree-arrow" :size="14"><ArrowDown v-if="openedMenuKey === 'map'" /><ArrowRight v-else /></el-icon>
        </button>

        <div v-show="openedMenuKey === 'map'" class="tree-children">
          <button
            v-for="sub in mapSubItems"
            :key="sub.id"
            class="sub-btn"
            :class="{ active: mapStore.activeTool === 'map' && mapStore.currentMapTab === sub.id }"
            @click="selectMapTab(sub.id)"
          >
            <span class="sub-label">{{ sub.label }}</span>
          </button>
        </div>
      </div>

      <!-- 建图：可展开的一级菜单（树状），原右侧堆叠模块拆为二级 -->
      <div class="tool-tree">
        <button
          class="tool-btn tree-parent"
          :class="{ active: mapStore.activeTool === 'mapping' }"
          :title="'建图'"
          @click="toggleMappingExpand"
        >
          <el-icon :size="20"><Edit /></el-icon>
          <span class="tool-label">建图</span>
          <el-icon class="tree-arrow" :size="14"><ArrowDown v-if="openedMenuKey === 'mapping'" /><ArrowRight v-else /></el-icon>
        </button>

        <div v-show="openedMenuKey === 'mapping'" class="tree-children">
          <button
            v-for="sub in mappingSubItems"
            :key="sub.id"
            class="sub-btn"
            :class="{ active: mapStore.activeTool === 'mapping' && mapStore.currentMappingTab === sub.id }"
            @click="selectMappingTab(sub.id)"
          >
            <span class="sub-label">{{ sub.label }}</span>
          </button>
        </div>
      </div>

      <button
        v-for="tool in flatTools"
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

    <div class="sidebar-footer">
      <button
        class="tool-btn data-toggle"
        :class="{ active: dataExpanded }"
        @click="toggleDataPanel"
        :title="dataExpanded ? '收起数据面板' : '展开数据面板'"
      >
        <el-icon :size="20"><DataAnalysis /></el-icon>
        <span class="tool-label">数据面板</span>
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { markRaw, ref } from 'vue'
import {
  MapLocation,
  Edit,
  Document,
  Connection,
  Memo,
  Setting,
  DataAnalysis,
  ArrowDown,
  ArrowRight,
} from '@element-plus/icons-vue'
import { useMapStore } from '@/stores/map'
import type { ActiveTool } from '@/types'

const mapStore = useMapStore()
const dataExpanded = ref(false)

// 手风琴互斥：同一时刻仅允许“地图”或“建图”其中一个二级菜单展开，
// 值为 'map' / 'mapping' 表示对应一级展开，'' 表示全部收起。
const openedMenuKey = ref<'map' | 'mapping' | ''>('map')

function toggleMapExpand() {
  // 再次点击已展开项则收起；否则互斥展开“地图”并收起“建图”
  openedMenuKey.value = openedMenuKey.value === 'map' ? '' : 'map'
  mapStore.setMapTab(mapStore.currentMapTab)
}

function selectMapTab(tab: 'edit' | 'info' | 'connection') {
  openedMenuKey.value = 'map'
  mapStore.setMapTab(tab)
}

function toggleMappingExpand() {
  openedMenuKey.value = openedMenuKey.value === 'mapping' ? '' : 'mapping'
  mapStore.setMappingTab(mapStore.currentMappingTab)
}

function selectMappingTab(tab: 'settings' | 'manage' | 'control') {
  openedMenuKey.value = 'mapping'
  mapStore.setMappingTab(tab)
}

function handleToolClick(toolId: ActiveTool) {
  // 点击无二级菜单的常规一级项：互斥收起所有已展开的子菜单
  openedMenuKey.value = ''
  mapStore.activeTool = toolId
  mapStore.setDrawMode('none')
}

function toggleDataPanel() {
  dataExpanded.value = !dataExpanded.value
  window.dispatchEvent(new CustomEvent('toggle-data-panel'))
}

const mapSubItems: { id: 'edit' | 'info' | 'connection'; label: string }[] = [
  { id: 'edit', label: '编辑地图' },
  { id: 'info', label: '地图信息' },
  { id: 'connection', label: '连接状态' },
]

const mappingSubItems: { id: 'settings' | 'manage' | 'control'; label: string }[] = [
  { id: 'settings', label: '地图设置' },
  { id: 'manage', label: '地图管理' },
  { id: 'control', label: '实时控制' },
]

// 其余一级菜单（地图 / 建图已拆为树状菜单）
const flatTools: { id: ActiveTool; label: string; icon: any }[] = [
  { id: 'navigation', label: '导航', icon: markRaw(Document) },
  { id: 'taskchain', label: '任务链', icon: markRaw(Connection) },
  { id: 'log', label: '日志', icon: markRaw(Memo) },
  { id: 'settings', label: '设置', icon: markRaw(Setting) },
]
</script>

<style lang="scss" scoped>
.left-toolbar {
  width: $left-toolbar-width;
  flex-shrink: 0;
  background: var(--bg-sidebar);
  border-right: 1px solid $border-color;
  display: flex;
  flex-direction: column;
  padding: 10px 0;
}

.tool-buttons {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
  flex: 1;
  padding: 0 8px;
  overflow-y: auto;
}

.tool-btn {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: flex-start;
  gap: 12px;
  padding: 12px 14px;
  border: none;
  background: transparent;
  color: $text-secondary;
  cursor: pointer;
  transition: all $transition;
  border-radius: $radius;
  border-left: 3px solid transparent;

  &:hover {
    background: $bg-hover;
    color: $text-primary;
  }

  &.active {
    background: $active-menu-bg;
    color: $theme-primary;
    border-left: 3px solid $theme-primary;
  }
}

// ===== 树状一级菜单（地图） =====
.tool-tree {
  display: flex;
  flex-direction: column;
}

.tree-parent {
  position: relative;

  .tree-arrow {
    margin-left: auto;
    color: $text-muted;
    transition: transform $transition;
  }
}

.tree-children {
  display: flex;
  flex-direction: column;
  padding: 4px 0 4px 22px;
  gap: 2px;

  .sub-btn {
    display: flex;
    align-items: center;
    padding: 9px 14px;
    border: none;
    background: transparent;
    color: $text-muted;
    cursor: pointer;
    transition: all $transition;
    border-radius: $radius;
    border-left: 2px solid transparent;
    font-size: 12px;

    &:hover {
      background: $bg-hover;
      color: $text-primary;
    }

    &.active {
      background: $active-menu-bg;
      color: $theme-primary;
      border-left: 2px solid $theme-primary;
    }
  }

  .sub-label {
    white-space: nowrap;
  }
}

.tool-label {
  font-size: 13px;
  white-space: nowrap;
}

.sidebar-footer {
  width: 100%;
  margin-top: auto;
  padding: 8px;
  border-top: 1px solid $border-color;
}

.data-toggle {
  width: 100%;
  padding: 12px 14px;

  &.active {
    background: $active-menu-bg;
    color: $theme-primary;
    border-left: 3px solid $theme-primary;
  }
}
</style>
