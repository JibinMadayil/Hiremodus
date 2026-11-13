/* Watches the candidate's camera during the test and flags: a phone in view, nobody at the screen,
   more than one person, and looking away for too long. It only flags; the panel decides.
   Everything runs in the candidate's browser; models are served by HireModus from /models/. */

const GAP_MS = 15000 // the same flag is reported at most once every 15 seconds

const MESSAGES = {
  phone_detected: 'A phone is visible. Put it away until you submit.',
  no_face: "We can't see you. Stay in front of the camera.",
  multiple_faces: 'More than one person is in view. You need to take the test alone.',
  looking_away: 'Keep your eyes on the test screen.',
}

export async function startDetector({ video, settings, onFlag, onUnavailable }) {
  let human
  try {
    const { default: Human } = await import('@vladmandic/human')
    human = new Human({
      modelBasePath: '/models/',
      backend: 'humangl',
      debug: false,
      cacheSensitivity: 0,
      filter: { enabled: false },
      face: {
        enabled: true,
        detector: { modelPath: 'blazeface.json', rotation: false, maxDetected: 3, minConfidence: 0.5, return: false },
        mesh: { enabled: true, modelPath: 'facemesh.json' },
        iris: { enabled: true, modelPath: 'iris.json' },
        attention: { enabled: false }, emotion: { enabled: false }, description: { enabled: false },
        antispoof: { enabled: false }, liveness: { enabled: false },
      },
      object: { enabled: settings.phone !== false, modelPath: 'centernet.json', minConfidence: 0.35, maxDetected: 5 },
      body: { enabled: false }, hand: { enabled: false }, gesture: { enabled: false }, segmentation: { enabled: false },
    })
    await human.load()
    await human.warmup()
  } catch (e) {
    onUnavailable?.(String(e?.message || e).slice(0, 200))
    return { stop() {} }
  }

  const awayLimit = (Number(settings.away_s) || 5) * 1000
  const noFaceLimit = (Number(settings.noface_s) || 5) * 1000
  const since = { away: 0, noface: 0 }
  const lastSent = {}
  let stopped = false
  let busy = false

  const flag = async (type, detail) => {
    const now = Date.now()
    if (lastSent[type] && now - lastSent[type] < GAP_MS) return
    lastSent[type] = now
    onFlag(type, detail, MESSAGES[type], await snapshot(video))
  }

  const tick = async () => {
    if (stopped || busy || !video.videoWidth || video.readyState < 2) return
    busy = true
    try {
      const r = await human.detect(video)
      const now = Date.now()
      const faces = r.face || []
      if (faces.length === 0) {
        since.noface = since.noface || now
        if (now - since.noface >= noFaceLimit) flag('no_face', `No face for ${Math.round((now - since.noface) / 1000)}s`)
      } else since.noface = 0
      if (faces.length > 1) flag('multiple_faces', `${faces.length} faces`)
      if (faces.length >= 1) {
        const a = faces[0].rotation?.angle || {}
        const g = faces[0].rotation?.gaze || {}
        const yaw = Math.abs(a.yaw || 0), pitch = a.pitch || 0
        // head turned more than ~30 degrees, tilted down towards a lap or desk, or eyes strongly to one side
        const away = yaw > 0.52 || pitch > 0.42 || (g.strength || 0) > 0.6
        if (away) {
          since.away = since.away || now
          if (now - since.away >= awayLimit) flag('looking_away', `Looking away for ${Math.round((now - since.away) / 1000)}s`)
        } else since.away = 0
      } else since.away = 0
      const phone = (r.object || []).filter(o => o.label === 'cell phone').sort((x, y) => y.score - x.score)[0]
      if (phone) flag('phone_detected', `Phone ${Math.round(phone.score * 100)}% sure`)
    } catch { /* one bad frame; keep going */ }
    busy = false
  }
  const iv = setInterval(tick, 1000)
  return { stop() { stopped = true; clearInterval(iv) } }
}

function snapshot(video) {
  return new Promise(resolve => {
    try {
      const w = 480, h = Math.round(480 * (video.videoHeight / video.videoWidth || 0.5625))
      const c = document.createElement('canvas')
      c.width = w; c.height = h
      c.getContext('2d').drawImage(video, 0, 0, w, h)
      c.toBlob(b => resolve(b), 'image/jpeg', 0.75)
    } catch { resolve(null) }
  })
}
