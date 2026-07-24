import type { RobotStatus, MapInfo, Waypoint, Path, LogEntry } from '@/types'

export const mockRobotStatus: RobotStatus = {
  connected: true,
  battery: 85,
  voltage: 24.2,
  speed: 0.5,
  angularVelocity: 0.1,
  latency: 24,
  mode: 'AUTO',
  navStatus: 'navigating',
  x: 5.0,
  y: 3.0,
  theta: 0,
  poseSource: 'mock',
}

export const mockMap: MapInfo = {
  name: 'map',
  width: 800,
  height: 600,
  resolution: 0.05,
  origin: { x: -20, y: -15, theta: 0 },
  occupied: [],
  data: [],
}

export const mockWaypoints: Waypoint[] = [
  { id: 'wp1', x: 2, y: 2, yaw: 0, qz: 0, qw: 1, name: '入口', order: 1 },
  { id: 'wp2', x: 8, y: 2, yaw: 0, qz: 0, qw: 1, name: 'A区', order: 2 },
  { id: 'wp3', x: 8, y: 8, yaw: 0, qz: 0, qw: 1, name: 'B区', order: 3 },
  { id: 'wp4', x: 2, y: 8, yaw: 0, qz: 0, qw: 1, name: 'C区', order: 4 },
  { id: 'wp5', x: 5, y: 5, yaw: 0, qz: 0, qw: 1, name: '中心', order: 5 },
]

export const mockPaths: Path[] = [
  {
    id: 'path1',
    name: '巡检路线A',
    waypoints: [mockWaypoints[0], mockWaypoints[1], mockWaypoints[2], mockWaypoints[3]],
  },
  {
    id: 'path2',
    name: '巡检路线B',
    waypoints: [mockWaypoints[0], mockWaypoints[4], mockWaypoints[2]],
  },
]

export const mockLogs: LogEntry[] = [
  { time: '14:32:01', level: 'info', source: 'ROS', message: 'Connected to ROS2 bridge' },
  { time: '14:32:02', level: 'info', source: 'Nav2', message: 'Navigation server ready' },
  { time: '14:32:05', level: 'warn', source: 'SLAM', message: 'Low localization confidence: 0.72' },
  { time: '14:32:10', level: 'info', source: 'Map', message: 'Map loaded' },
  { time: '14:32:15', level: 'debug', source: 'Sensor', message: 'Lidar scan received: 360 points' },
  { time: '14:32:20', level: 'info', source: 'Nav', message: 'Waypoint navigation started' },
  { time: '14:32:25', level: 'error', source: 'Driver', message: 'Motor timeout on left wheel' },
  { time: '14:32:30', level: 'info', source: 'System', message: 'Emergency stop released' },
]

export function generateMockOccupiedGrid(width: number, height: number): boolean[][] {
  const grid: boolean[][] = []
  for (let y = 0; y < height; y++) {
    const row: boolean[] = []
    for (let x = 0; x < width; x++) {
      const border = x === 0 || y === 0 || x === width - 1 || y === height - 1
      const wallX = (x > 100 && x < 120 && y > 100 && y < 400)
      const wallY = (y > 200 && y < 220 && x > 200 && x < 500)
      const obstacle = Math.random() < 0.02 && x > 50 && y > 50
      row.push(border || wallX || wallY || obstacle)
    }
    grid.push(row)
  }
  return grid
}
