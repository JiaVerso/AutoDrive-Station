import type { MapInfo } from '@/types'

export function physicalToMapPixel(
  physicalX: number,
  physicalY: number,
  map: MapInfo
): { x: number; y: number } {
  const mapX = (physicalX - map.origin.x) / map.resolution
  const mapY = (physicalY - map.origin.y) / map.resolution
  return { x: mapX, y: mapY }
}

export function mapPixelToPhysical(
  mapX: number,
  mapY: number,
  map: MapInfo
): { x: number; y: number } {
  const physicalX = mapX * map.resolution + map.origin.x
  const physicalY = mapY * map.resolution + map.origin.y
  return { x: physicalX, y: physicalY }
}

export function physicalToScreen(
  physicalX: number,
  physicalY: number,
  map: MapInfo,
  cellSize: number,
  offsetX: number,
  offsetY: number,
  zoom: number
): { x: number; y: number } {
  const { x: mapX, y: mapY } = physicalToMapPixel(physicalX, physicalY, map)
  return {
    x: (mapX * cellSize + offsetX) * zoom,
    y: (mapY * cellSize + offsetY) * zoom
  }
}

export function screenToPhysical(
  screenX: number,
  screenY: number,
  map: MapInfo,
  cellSize: number,
  offsetX: number,
  offsetY: number,
  zoom: number
): { x: number; y: number } {
  const mapX = (screenX / zoom - offsetX) / cellSize
  const mapY = (screenY / zoom - offsetY) / cellSize
  return mapPixelToPhysical(mapX, mapY, map)
}
