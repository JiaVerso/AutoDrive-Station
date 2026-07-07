<template>
  <div class="app-container dark">
    <AppHeader />
    <div class="main-content">
      <LeftToolbar />
      <MapCanvas />
      <RightPanel v-if="mapStore.activeTool !== 'map'" />
    </div>
    <BottomBar />
    <DataPanel />
  </div>
</template>

<script setup lang="ts">
import AppHeader from '@/components/Header.vue'
import LeftToolbar from '@/components/LeftToolbar.vue'
import MapCanvas from '@/components/MapCanvas.vue'
import RightPanel from '@/components/RightPanel.vue'
import BottomBar from '@/components/BottomBar.vue'
import DataPanel from '@/components/DataPanel.vue'
import { useMapStore } from '@/stores/map'

const mapStore = useMapStore()
</script>

<style lang="scss">
.app-container {
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
