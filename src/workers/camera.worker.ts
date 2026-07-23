const TARGET_FPS = 15
const FRAME_INTERVAL = 1000 / TARGET_FPS

let lastFrameTime = 0

self.onmessage = (e: MessageEvent) => {
  const { type, data } = e.data
  if (type !== 'frame') return

  const now = Date.now()
  if (now - lastFrameTime < FRAME_INTERVAL) {
    self.postMessage({ type: 'dropped' })
    return
  }
  lastFrameTime = now

  const dataUrl = 'data:image/jpeg;base64,' + data
  self.postMessage({ type: 'frame-ready', data: dataUrl })
}
