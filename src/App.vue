<template>
  <div class="app-container">
    <AppHeader />
    <div class="main-content">
      <LeftToolbar />
      <MapCanvas v-if="mapStore.activeTool !== 'taskchain'" />
      <TaskChain v-else />
      <RightPanel v-if="mapStore.activeTool !== 'taskchain'" />
    </div>
    <BottomBar />
    <DataPanel />
    <!-- 一键跟随：摄像头悬浮弹窗（draggable，跟随模式激活时显示） -->
    <FollowCameraPopup />
  </div>
</template>

<script setup lang="ts">
import { onErrorCaptured } from 'vue'
import AppHeader from '@/components/Header.vue'
import LeftToolbar from '@/components/LeftToolbar.vue'
import MapCanvas from '@/components/MapCanvas.vue'
import RightPanel from '@/components/RightPanel.vue'
import BottomBar from '@/components/BottomBar.vue'
import DataPanel from '@/components/DataPanel.vue'
import TaskChain from '@/components/TaskChain.vue'
import FollowCameraPopup from '@/components/FollowCameraPopup.vue'
import { useMapStore } from '@/stores/map'
import { useTheme } from '@/composables/useTheme'

const mapStore = useMapStore()
const { initTheme } = useTheme()
initTheme()

// 严格按当前激活视图（activeTool）隔离渲染：
//  - taskchain 视图独占中央主视口，且 RightPanel 只在非 taskchain 时渲染，
//    杜绝跨页面右侧面板重叠污染。
//  - 组件内未捕获异常在此拦截，确保路由/视图切换始终畅通、不卡死。
onErrorCaptured((err, _instance, info) => {
  console.error('[App onErrorCaptured]', info, err)
  return false
})
</script>

<style lang="scss">
.app-container {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100vh;
  background: $bg-primary;
  color: $text-primary;
}

.main-content {
  display: flex;
  flex: 1;
  overflow: hidden;
}
</style>
