export interface RobotStatus {
  connected: boolean
  battery: number
  voltage: number
  speed: number
  mode: string
  x: number
  y: number
  theta: number
}

export interface MapInfo {
  name: string
  width: number
  height: number
  resolution: number
  origin: { x: number; y: number; theta: number }
  occupied: boolean[][]
  data: number[][]
}

export interface Waypoint {
  id: string
  x: number
  y: number
  name: string
  order: number
}

export interface Path {
  id: string
  name: string
  waypoints: Waypoint[]
}

export interface NavigationStatus {
  active: boolean
  paused: boolean
  currentWaypointIndex: number
  progress: number
}

export interface LogEntry {
  time: string
  level: 'info' | 'warn' | 'error' | 'debug'
  source: string
  message: string
}

export type ActiveTool = 'map' | 'mapping' | 'localization' | 'navigation' | 'waypoint' | 'path' | 'camera' | 'log' | 'settings'

export interface DrawPoint {
  id: string
  x: number
  y: number
}

export interface DrawLine {
  id: string
  points: { x: number; y: number }[]
}

export type DrawMode = 'none' | 'point' | 'line'
