/* Camera + screen recording for the test portal.
   Each recording is uploaded in 10-second pieces while the test runs, so nothing is lost if the browser closes. */

export const media = { camera: null, screen: null, acquiring: false }

/* Screen recording quality, set by the admin in Settings. */
const PROFILES = {
  high: { w: 1920, h: 1080, fps: 10, screenBps: 2500000, camBps: 600000, cw: 1280, ch: 720 },
  standard: { w: 1280, h: 720, fps: 8, screenBps: 1200000, camBps: 400000, cw: 960, ch: 540 },
  low: { w: 1280, h: 720, fps: 5, screenBps: 400000, camBps: 250000, cw: 640, ch: 360 },
}
let profile = PROFILES.high
export function setQuality(q) { profile = PROFILES[q] || PROFILES.high }

/* Only Chrome and Edge report what was shared and whether a second monitor is connected, so the test needs one of them. */
export function supportedBrowser() {
  const brands = navigator.userAgentData?.brands?.map(b => b.brand) || []
  if (brands.length) return brands.some(b => b === 'Google Chrome' || b === 'Microsoft Edge')
  const ua = navigator.userAgent
  return /(Chrome|Edg)\//.test(ua) && !/(OPR|Opera|Firefox|SamsungBrowser|YaBrowser|Vivaldi)/.test(ua)
}

/* true when Windows/macOS reports more than one monitor (Chrome and Edge only) */
export const hasSecondScreen = () => window.screen?.isExtended === true

export const isLive = s => !!s && s.getVideoTracks().some(t => t.readyState === 'live')

export async function getCamera(withAudio) {
  if (isLive(media.camera)) return media.camera
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('This browser cannot use the camera. Use Chrome or Edge.')
  media.acquiring = true
  try {
    media.camera = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: profile.cw }, height: { ideal: profile.ch }, frameRate: { ideal: 15, max: 15 } },
      audio: withAudio ? { echoCancellation: true, noiseSuppression: false } : false,
    })
    return media.camera
  } catch (e) {
    throw new Error(e && e.name === 'NotAllowedError'
      ? 'Camera access was blocked. Click the camera icon in the address bar, allow it, and try again.'
      : 'No camera or microphone was found. Ask your interviewer for help.')
  } finally { media.acquiring = false }
}

export async function getScreen() {
  if (isLive(media.screen)) return media.screen
  if (!navigator.mediaDevices?.getDisplayMedia) throw new Error('This browser cannot record the screen. Use Chrome or Edge.')
  if (hasSecondScreen()) throw new Error('A second monitor is connected. Unplug it (or set Windows to show only one screen), then try again.')
  media.acquiring = true
  try {
    const s = await navigator.mediaDevices.getDisplayMedia({
      video: { displaySurface: 'monitor', width: { ideal: profile.w }, height: { ideal: profile.h }, frameRate: { ideal: profile.fps, max: profile.fps } },
      audio: false, monitorTypeSurfaces: 'include', selfBrowserSurface: 'include', surfaceSwitching: 'exclude',
    })
    const track = s.getVideoTracks()[0]
    const surface = track?.getSettings?.().displaySurface
    if (surface !== 'monitor') {
      s.getTracks().forEach(t => t.stop())
      throw new Error(surface ? 'You shared a ' + (surface === 'browser' ? 'tab' : 'window') + '. Share your Entire screen instead.'
        : 'Your browser did not confirm that the entire screen is shared. Use Chrome or Edge and choose Entire screen.')
    }
    try { track.contentHint = 'detail' } catch { /* older browsers */ }
    media.screen = s
    return s
  } catch (e) {
    if (/Share your Entire|did not confirm/.test(e.message || '')) throw e
    throw new Error('Screen sharing was cancelled. You need to share your entire screen to take this test.')
  } finally { setTimeout(() => { media.acquiring = false }, 800) }
}

export function stopAll() {
  ;['camera', 'screen'].forEach(k => { media[k]?.getTracks().forEach(t => t.stop()); media[k] = null })
}

function pickMime(withAudio) {
  const options = withAudio
    ? ['video/webm;codecs=vp8,opus', 'video/webm;codecs=vp9,opus', 'video/webm']
    : ['video/webm;codecs=vp8', 'video/webm;codecs=vp9', 'video/webm']
  return options.find(m => window.MediaRecorder?.isTypeSupported?.(m)) || ''
}

/* Starts one recording on the server and streams chunks to it. Returns { stop(): Promise } */
export async function startRecording({ kind, stream, token, onError }) {
  const withAudio = stream.getAudioTracks().length > 0
  const mimeType = pickMime(withAudio)
  const res = await fetch('/api/portal/recording/start', {
    method: 'POST', headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, mime: mimeType || 'video/webm' }),
  })
  if (!res.ok) throw new Error('Could not start recording')
  const { id } = await res.json()
  const rec = new MediaRecorder(stream, {
    mimeType: mimeType || undefined,
    videoBitsPerSecond: kind === 'screen' ? profile.screenBps : profile.camBps,
    audioBitsPerSecond: 48000,
  })
  let seq = 0
  let chain = Promise.resolve()
  let failed = false
  const send = async (blob, n) => {
    for (let attempt = 0; attempt < 5; attempt++) {
      try {
        const r = await fetch(`/api/portal/recording/${id}/chunk?seq=${n}`, {
          method: 'POST', headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/octet-stream' }, body: blob,
        })
        if (r.ok || r.status === 409) return
        if (r.status === 410 || r.status === 403 || r.status === 404) return
      } catch { /* network blip */ }
      await new Promise(ok => setTimeout(ok, 1500 * (attempt + 1)))
    }
    if (!failed) { failed = true; onError?.(kind) }
  }
  rec.ondataavailable = e => {
    if (e.data && e.data.size > 0) { const n = seq++; chain = chain.then(() => send(e.data, n)) }
  }
  rec.start(10000)
  return {
    kind,
    stop: () => new Promise(resolve => {
      if (rec.state === 'inactive') return chain.then(resolve)
      rec.onstop = () => setTimeout(() => chain.then(resolve), 50)
      try { rec.stop() } catch { chain.then(resolve) }
    }),
  }
}
