export interface PointCloudField {
  name: string
  offset: number
  datatype: number
  count: number
}

export interface PointCloud2Message {
  header: {
    seq: number
    stamp: { sec: number; nanosec: number }
    frame_id: string
  }
  height: number
  width: number
  fields: PointCloudField[]
  is_bigendian: boolean
  point_step: number
  row_step: number
  data: string | number[] | Uint8Array | ArrayBuffer
  is_dense: boolean
}

export interface Point3D {
  x: number
  y: number
  z: number
  intensity?: number
  nx?: number
  ny?: number
  nz?: number
  curvature?: number
}

export interface PointCloudData {
  points: Point3D[]
  frameId: string
  timestamp: number
}

function getBytesFromData(data: string | number[] | Uint8Array | ArrayBuffer): Uint8Array | null {
  if (typeof data === 'string') {
    const bin = atob(data)
    const bytes = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) {
      bytes[i] = bin.charCodeAt(i)
    }
    return bytes
  } else if (data instanceof Uint8Array) {
    return data
  } else if (Array.isArray(data)) {
    return new Uint8Array(data)
  } else if (data instanceof ArrayBuffer) {
    return new Uint8Array(data)
  } else {
    return null
  }
}

export function parsePointCloud2(message: any): PointCloudData {
  if (!message || !message.data) {
    console.warn('[PointCloud] Message or data is null')
    return { points: [], frameId: '', timestamp: 0 }
  }

  try {
    const bytes = getBytesFromData(message.data)
    if (!bytes) {
      console.warn('[PointCloud] Unsupported data format:', typeof message.data)
      return { points: [], frameId: '', timestamp: 0 }
    }

    const fields = message.fields || []
    const pointStep = message.point_step || 12
    const height = message.height || 1
    const width = message.width || 0
    const isBigEndian = message.is_bigendian || false

    const count = height * width
    if (count === 0 || bytes.length === 0) {
      console.warn('[PointCloud] No points to parse, count:', count, 'bytes:', bytes.length)
      return { points: [], frameId: '', timestamp: 0 }
    }

    console.log('[PointCloud] Parsing points:', count, 'point_step:', pointStep, 'bytes:', bytes.length)

    let xOff = 0, yOff = 4, zOff = 8
    if (fields.length > 0) {
      for (const f of fields) {
        if (f.name === 'x') xOff = f.offset
        if (f.name === 'y') yOff = f.offset
        if (f.name === 'z') zOff = f.offset
      }
      console.log('[PointCloud] Using fields offsets - x:', xOff, 'y:', yOff, 'z:', zOff)
    } else {
      console.log('[PointCloud] Using default offsets - x:', xOff, 'y:', yOff, 'z:', zOff)
    }

    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    const points: Point3D[] = []
    const le = !isBigEndian
    const maxRead = count
    let valid = 0

    for (let i = 0; i < maxRead; i++) {
      const base = i * pointStep
      if (base + 12 > bytes.length) break

      const x = view.getFloat32(base + xOff, le)
      const y = view.getFloat32(base + yOff, le)
      const z = view.getFloat32(base + zOff, le)

      if (!isFinite(x) || !isFinite(y) || !isFinite(z)) continue

      const point: Point3D = { x, y, z }

      for (const f of fields) {
        if (f.name === 'intensity') {
          const intensityOffset = base + f.offset
          if (intensityOffset + 4 <= bytes.length) {
            point.intensity = view.getFloat32(intensityOffset, le)
          }
        }
      }

      points.push(point)
      valid++
    }

    console.log('[PointCloud] Valid points parsed:', valid)

    const frameId = message.header?.frame_id || ''
    const timestamp = message.header?.stamp?.sec
      ? message.header.stamp.sec * 1000 + Math.floor(message.header.stamp.nanosec / 1e6)
      : Date.now()

    return { points, frameId, timestamp }
  } catch (error) {
    console.error('[PointCloud] Parse error:', error)
    return { points: [], frameId: '', timestamp: 0 }
  }
}

export function projectTo2D(points: Point3D[], mapOrigin: { x: number; y: number }, mapResolution: number): { x: number; y: number; z: number; intensity?: number }[] {
  return points.map(point => ({
    x: (point.x - mapOrigin.x) / mapResolution,
    y: (point.y - mapOrigin.y) / mapResolution,
    z: point.z,
    intensity: point.intensity
  }))
}

export function parseLivoxCustomMsg(message: any): PointCloudData {
  if (!message || !message.points || !Array.isArray(message.points)) {
    console.warn('[Livox] Message or points array is null')
    return { points: [], frameId: '', timestamp: 0 }
  }

  try {
    const points: Point3D[] = []
    const rawPoints = message.points

    for (const p of rawPoints) {
      const x = typeof p.x === 'number' ? p.x : 0
      const y = typeof p.y === 'number' ? p.y : 0
      const z = typeof p.z === 'number' ? p.z : 0

      if (!isFinite(x) || !isFinite(y) || !isFinite(z)) continue

      const point: Point3D = { x, y, z }

      if (typeof p.reflectivity === 'number') {
        point.intensity = p.reflectivity
      }

      points.push(point)
    }

    console.log('[Livox] Parsed points:', points.length)

    const frameId = message.header?.frame_id || ''
    const timestamp = message.header?.stamp?.sec
      ? message.header.stamp.sec * 1000 + Math.floor(message.header.stamp.nanosec / 1e6)
      : Date.now()

    return { points, frameId, timestamp }
  } catch (error) {
    console.error('[Livox] Parse error:', error)
    return { points: [], frameId: '', timestamp: 0 }
  }
}

export function parsePointCloud2ToFloat32Array(message: any): Float32Array | null {
  if (!message || !message.data) {
    console.warn('[PointCloud3D] Message or data is null')
    return null
  }

  const bytes = getBytesFromData(message.data)
  if (!bytes) {
    console.warn('[PointCloud3D] Unsupported data format:', typeof message.data)
    return null
  }

  const ps = message.point_step || 12
  const height = message.height || 1
  const width = message.width || 0
  const count = width * height
  
  console.log('[PointCloud3D] parsePointCloud2ToFloat32Array - width:', width, 'height:', height, 'count:', count, 'point_step:', ps, 'bytes.length:', bytes.length)

  if (count === 0 || bytes.length === 0) {
    console.warn('[PointCloud3D] No points to parse, count:', count, 'bytes:', bytes.length)
    return null
  }

  let xOff = 0, yOff = 4, zOff = 8
  if (message.fields && Array.isArray(message.fields)) {
    for (const f of message.fields) {
      if (f.name === 'x') xOff = f.offset
      if (f.name === 'y') yOff = f.offset
      if (f.name === 'z') zOff = f.offset
    }
    console.log('[PointCloud3D] Using fields offsets - x:', xOff, 'y:', yOff, 'z:', zOff)
  } else {
    console.log('[PointCloud3D] Using default offsets - x:', xOff, 'y:', yOff, 'z:', zOff)
  }

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const pos = new Float32Array(count * 3)
  const le = !message.is_bigendian
  const maxRead = count
  let valid = 0

  for (let i = 0; i < maxRead; i++) {
    const base = i * ps
    if (base + 12 > bytes.length) {
      console.warn('[PointCloud3D] Out of bounds at index:', i, 'base:', base, 'bytes.length:', bytes.length)
      break
    }
    const x = view.getFloat32(base + xOff, le)
    const y = view.getFloat32(base + yOff, le)
    const z = view.getFloat32(base + zOff, le)
    if (!isFinite(x) || !isFinite(y) || !isFinite(z)) continue
    pos[valid * 3] = x
    pos[valid * 3 + 1] = z
    pos[valid * 3 + 2] = -y
    valid++
  }

  console.log('[PointCloud3D] Valid points:', valid)

  if (valid > 0) {
    const validPos = pos.slice(0, valid * 3)
    let minY = Infinity
    for (let i = 0; i < valid; i++) {
      if (validPos[i * 3 + 1] < minY) {
        minY = validPos[i * 3 + 1]
      }
    }
    const offset = -minY + 0.0
    for (let i = 0; i < valid; i++) {
      validPos[i * 3 + 1] += offset
    }
    return validPos
  }
  return null
}