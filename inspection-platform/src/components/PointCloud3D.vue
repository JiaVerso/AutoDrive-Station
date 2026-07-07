<template>
  <div class="point-cloud-3d-container" ref="containerRef">
    <div class="point-cloud-info">
      <span>{{ pointCount }} 个点</span>
    </div>
    <div class="point-cloud-controls-hint">
      <span>🖱️ 左键拖动旋转 | 滚轮缩放</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as THREE from 'three'
import { useMapStore } from '@/stores/map'

const mapStore = useMapStore()
const containerRef = ref<HTMLDivElement>()

let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let renderer: THREE.WebGLRenderer | null = null
let points: THREE.Points | null = null
let isSceneReady = false

const orbit = ref({
  theta: 0.8,
  phi: 0.8,
  radius: 10,
  target: new THREE.Vector3(0, 0, 0)
})

const isDragging = ref(false)
const mouse = ref({ x: 0, y: 0 })

const pointCount = ref(0)

function initScene() {
  if (isSceneReady || !containerRef.value) return

  const rect = containerRef.value.getBoundingClientRect()
  const w = rect.width || 400
  const h = rect.height || 400

  scene = new THREE.Scene()
  camera = new THREE.PerspectiveCamera(55, w / h, 0.01, 500)
  updateCamera()

  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(w, h)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setClearColor(0x000000)
  containerRef.value.appendChild(renderer.domElement)

  const grid = new THREE.GridHelper(50, 50, 0x007acc, 0x007acc22)
  grid.position.y = -0.6
  scene.add(grid)

  const axes = new THREE.AxesHelper(2)
  scene.add(axes)

  const ambient = new THREE.AmbientLight(0x404060)
  scene.add(ambient)

  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
  geo.setDrawRange(0, 0)

  points = new THREE.Points(
    geo,
    new THREE.PointsMaterial({
      color: 0x00ccff,
      size: 0.15,
      sizeAttenuation: false,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    })
  )
  scene.add(points)

  containerRef.value.addEventListener('mousedown', (e) => {
    isDragging.value = true
    mouse.value.x = e.clientX
    mouse.value.y = e.clientY
  })

  window.addEventListener('mouseup', () => { isDragging.value = false })

  window.addEventListener('mousemove', (e) => {
    if (!isDragging.value) return
    const dx = e.clientX - mouse.value.x
    const dy = e.clientY - mouse.value.y
    orbit.value.theta -= dx * 0.008
    orbit.value.phi = Math.max(0.01, Math.min(Math.PI - 0.01, orbit.value.phi + dy * 0.008))
    mouse.value.x = e.clientX
    mouse.value.y = e.clientY
    updateCamera()
  })

  containerRef.value.addEventListener('wheel', (e) => {
    orbit.value.radius = Math.max(0.5, Math.min(200, orbit.value.radius + e.deltaY * 0.015))
    e.preventDefault()
    updateCamera()
  }, { passive: false })

  const ro = new ResizeObserver(() => {
    if (!containerRef.value || !renderer || !camera) return
    const r = containerRef.value.getBoundingClientRect()
    if (r.width > 0 && r.height > 0) {
      camera.aspect = r.width / r.height
      camera.updateProjectionMatrix()
      renderer.setSize(r.width, r.height)
    }
  })
  ro.observe(containerRef.value)

  isSceneReady = true
  animate()
}

function updateCamera() {
  if (!camera) return
  const { theta, phi, radius, target } = orbit.value
  camera.position.set(
    radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi) + 0.5,
    radius * Math.sin(phi) * Math.sin(theta)
  )
  camera.lookAt(target)
}

function animate() {
  if (!isSceneReady || !renderer || !scene) return
  requestAnimationFrame(animate)
  renderer.render(scene, camera!)
}

function updatePointCloud(positions: Float32Array) {
  console.log('[PointCloud3D] updatePointCloud called, positions length:', positions.length, 'points:', positions.length / 3)
  if (!isSceneReady) initScene()
  if (!points) {
    console.warn('[PointCloud3D] points is null')
    return
  }

  const geo = points.geometry
  const count = positions.length / 3

  const attr = geo.attributes.position as THREE.BufferAttribute
  const array = attr.array as Float32Array
  
  if (array.length >= positions.length) {
    array.set(positions)
  } else {
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  }
  
  attr.needsUpdate = true
  geo.setDrawRange(0, count)
  pointCount.value = count
  console.log('[PointCloud3D] updatePointCloud completed, pointCount:', pointCount.value)
}

function clearPointCloud() {
  if (!isSceneReady || !points) return
  const geo = points.geometry
  geo.setDrawRange(0, 0)
  pointCount.value = 0
}

watch(() => mapStore.pointCloud3DData, (data) => {
  console.log('[PointCloud3D] watch triggered, data:', data ? `Float32Array(${data.length})` : null)
  if (data) {
    updatePointCloud(data)
  } else {
    clearPointCloud()
  }
}, { deep: false })

onMounted(() => {
  initScene()
  if (mapStore.pointCloud3DData) {
    updatePointCloud(mapStore.pointCloud3DData)
  }
})

onUnmounted(() => {
  isSceneReady = false
  if (renderer) {
    renderer.dispose()
    if (containerRef.value && renderer.domElement.parentNode === containerRef.value) {
      containerRef.value.removeChild(renderer.domElement)
    }
  }
  if (points && points.geometry) {
    points.geometry.dispose()
  }
})
</script>

<style lang="scss" scoped>
.point-cloud-3d-container {
  width: 100%;
  height: 300px;
  background: #000;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  cursor: grab;

  &:active {
    cursor: grabbing;
  }
}

.point-cloud-info {
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 12px;
  color: #00ccff;
  background: rgba(0, 0, 0, 0.6);
  padding: 4px 12px;
  border-radius: 12px;
  font-weight: bold;
  pointer-events: none;
}

.point-cloud-controls-hint {
  position: absolute;
  bottom: 8px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 11px;
  color: #666;
  pointer-events: none;
}
</style>