import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Logo, usePublicBrand } from '../brand'
import { media, isLive, getCamera, getScreen, startRecording, stopAll, setQuality, supportedBrowser, hasSecondScreen } from '../recorder'
import { startDetector } from '../detector'

/* The candidate test portal. It never links to the staff app, and a candidate token can only call /api/portal. */

const SKEY = 'hm_portal'
const store = {
  get() { try { return JSON.parse(sessionStorage.getItem(SKEY)) || {} } catch { return {} } },
  set(v) { try { sessionStorage.setItem(SKEY, JSON.stringify(v)) } catch { /* ignore */ } },
  clear() { try { sessionStorage.removeItem(SKEY) } catch { /* ignore */ } },
}
const call = (path, opts = {}) => api('/api/portal' + path, { ...opts, token: opts.token ?? store.get().token ?? null })

function inFullscreen() { return !!(document.fullscreenElement || document.webkitFullscreenElement) }
function goFullscreen() {
  const el = document.documentElement
  const fn = el.requestFullscreen || el.webkitRequestFullscreen
  try { const p = fn && fn.call(el); if (p && p.catch) p.catch(() => {}) } catch { /* ignore */ }
}

export default function Portal() {
  const brand = usePublicBrand()
  const [phase, setPhase] = useState('loading') // loading | login | code | test | done
  const [info, setInfo] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    const s = store.get()
    if (!s.token) return setPhase('login')
    if (s.scope === 'cand-test') {
      call('/test').then(() => setPhase('test'), e => { if (e.status === 410) { store.clear(); setPhase('done') } else { store.clear(); setPhase('login') } })
    } else {
      call('/state').then(st => { setInfo(st); setPhase('code') }, () => { store.clear(); setPhase('login') })
    }
  }, [])

  return (
    <div className="portal">
      {phase !== 'test' && <div className="portal-top"><Logo brand={brand} height={36} /><span className="muted">{info?.first_name ? `Assessment for ${info.first_name}` : 'Assessment portal'}</span></div>}
      {phase === 'loading' && <div className="empty">Loading…</div>}
      {phase === 'login' && <Login onDone={st => { setInfo(st); setPhase('code') }} err={err} setErr={setErr} />}
      {phase === 'code' && <CodeEntry info={info} onDone={() => setPhase('test')} onSignOut={() => { store.clear(); setPhase('login') }} />}
      {phase === 'test' && <TestRunner onDone={() => { store.clear(); setPhase('done') }} />}
      {phase === 'done' && <div className="portal-body"><div className="q" style={{ textAlign: 'center' }}><h1>Test submitted</h1><p className="muted">Thank you. Your answers have been saved and sent to the interview panel. You can close this window.</p></div></div>}
    </div>
  )
}

function Login({ onDone }) {
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async e => {
    e.preventDefault(); setBusy(true); setErr('')
    try {
      const r = await call('/login', { method: 'POST', body: { username: u, password: p }, token: null })
      store.set({ token: r.token, scope: 'cand-login' })
      onDone(r)
    } catch (e2) { setErr(e2.message) } finally { setBusy(false) }
  }
  return (
    <div className="portal-body" style={{ maxWidth: 420 }}>
      <form className="q col" onSubmit={submit}>
        <h1>Sign in</h1>
        <div className="muted">Use the username and password from your interview email.</div>
        <label className="f">Username<input autoFocus autoComplete="off" value={u} onChange={e => setU(e.target.value)} /></label>
        <label className="f">Password<input type="password" autoComplete="off" value={p} onChange={e => setP(e.target.value)} /></label>
        {err && <div className="alert bad">{err}</div>}
        <button className="primary" disabled={busy || !u || !p}>Sign in</button>
      </form>
    </div>
  )
}

function CodeEntry({ info, onDone, onSignOut }) {
  const [code, setCode] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [agree, setAgree] = useState(false)
  const [consent, setConsent] = useState(false)
  const [mediaErr, setMediaErr] = useState('')
  const [, force] = useState(0)
  const preview = useRef(null)
  const rec = info?.record || {}
  const needs = rec.camera || rec.screen
  const integ = info?.integrity || {}
  const browserOk = !needs || supportedBrowser()
  useEffect(() => { setQuality(integ.quality) }, [integ.quality])
  const camOk = !rec.camera || isLive(media.camera)
  const scrOk = !rec.screen || isLive(media.screen)
  useEffect(() => { if (preview.current && media.camera) preview.current.srcObject = media.camera })

  const turnOn = async () => {
    setMediaErr('')
    try {
      if (rec.camera) await getCamera(rec.audio)
      force(x => x + 1)
      if (rec.screen) await getScreen()
    } catch (e) { setMediaErr(e.message) }
    force(x => x + 1)
  }
  const start = async () => {
    setErr(''); setBusy(true)
    goFullscreen() // must happen inside the click
    try {
      const r = await call('/unlock', { method: 'POST', body: { code } })
      store.set({ token: r.token, scope: 'cand-test' })
      onDone()
    } catch (e) {
      setErr(e.message); setBusy(false)
      if (inFullscreen()) document.exitFullscreen?.().catch(() => {})
    }
  }
  const resuming = info?.status === 'in_progress'
  const what = [rec.camera && (rec.audio ? 'your camera and microphone' : 'your camera'), rec.screen && 'your entire screen'].filter(Boolean).join(' and ')
  return (
    <div className="portal-body">
      <div className="q col">
        <h1>{info?.test_name}</h1>
        <div className="muted">{info?.question_count} questions · {info?.duration_min} minutes{info?.allow_file_upload ? ' · includes a file upload' : ''}</div>
        {info?.instructions && <div className="pre">{info.instructions}</div>}
        <div className="alert">
          <b>Before you start</b><br />
          The test opens in full screen and the timer starts as soon as you enter the code. It can't be paused.<br />
          Leaving full screen, switching tabs or windows, copying, pasting and right-clicking are blocked or recorded and shown to the panel.<br />
          Answers save automatically. When time runs out the test submits itself.
        </div>
        {!browserOk && <div className="alert bad"><b>Open this page in Google Chrome or Microsoft Edge.</b><br />This test records your entire screen, which only works in Chrome or Edge on a computer. Copy the address, open it in Chrome or Edge, and sign in again.</div>}
        {browserOk && needs && <div className="card col" style={{ gap: 10 }}>
          <b>Recording</b>
          <div>This test records {what} from the moment it starts until you submit. The recording is only viewed by the Novamodus interview panel to confirm the test was taken fairly, and it is <b>permanently deleted at midnight tonight</b>.</div>
          <label className="check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} /> I agree to be recorded during this test</label>
          <div className="row">
            <button disabled={!consent || (camOk && scrOk)} onClick={turnOn}>{camOk && scrOk ? 'Recording is ready' : 'Turn on camera and screen sharing'}</button>
            {rec.camera && <span className={'badge ' + (camOk ? 'ok' : '')}>{camOk ? '✓' : '○'} Camera{rec.audio ? ' and microphone' : ''}</span>}
            {rec.screen && <span className={'badge ' + (scrOk ? 'ok' : '')}>{scrOk ? '✓' : '○'} Entire screen</span>}
          </div>
          {rec.screen && !scrOk && consent && <div className="small muted">When the browser asks what to share, choose <b>Entire screen</b>. A browser tab or a single window won't be accepted. If you have two monitors, unplug the second one first.</div>}
          {rec.camera && integ.detect && <div className="small muted">During the test your camera is also checked for a phone in view, other people in the room, and looking away from the screen for long stretches. You'll see a warning if something is noticed, and the panel sees the same note.</div>}
          {rec.camera && isLive(media.camera) && <video ref={preview} autoPlay muted playsInline style={{ width: 200, borderRadius: 8, background: '#000' }} />}
          {mediaErr && <div className="alert bad">{mediaErr}</div>}
        </div>}
        {resuming && <div className="alert warn">Your test is already running. Ask your interviewer for a new code to continue; the timer has kept going.</div>}
        <label className="check"><input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)} /> I understand and I'm ready</label>
        <label className="f">Start code from your interviewer
          <input inputMode="numeric" autoComplete="off" maxLength={8} style={{ fontSize: 24, letterSpacing: 8, textAlign: 'center', maxWidth: 260 }} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))} />
        </label>
        {err && <div className="alert bad">{err}</div>}
        <div className="row between"><button type="button" className="ghost" onClick={() => { stopAll(); onSignOut() }}>Sign out</button>
          <button className="primary" disabled={busy || !browserOk || code.length < 6 || !agree || (needs && (!consent || !camOk || !scrOk))} onClick={start}>{resuming ? 'Continue test' : 'Start test'}</button></div>
      </div>
    </div>
  )
}

function useLockdown(active, report) {
  const [locked, setLocked] = useState(false)
  const last = useRef({})
  const log = useCallback((type, detail = '') => {
    const now = Date.now()
    if (media.acquiring && ['window_blur', 'tab_hidden', 'fullscreen_exit', 'fullscreen_enter'].includes(type)) return
    if (last.current[type] && now - last.current[type] < 1500) return
    last.current[type] = now
    report(type, detail)
  }, [report])

  useEffect(() => {
    if (!active) return
    setLocked(!inFullscreen())
    const onFs = () => {
      if (inFullscreen()) { setLocked(false); log('fullscreen_enter') } else { setLocked(true); log('fullscreen_exit') }
    }
    const onVis = () => { if (document.hidden) log('tab_hidden') }
    const onBlur = () => log('window_blur')
    const block = type => e => { e.preventDefault(); log(type) }
    const onCopy = block('copy_blocked'), onPaste = block('paste_blocked'), onCut = block('cut_blocked'), onCtx = block('context_menu_blocked')
    const onDrop = e => e.preventDefault()
    const onKey = e => {
      const k = (e.key || '').toLowerCase()
      const mod = e.ctrlKey || e.metaKey
      if (k === 'f12' || (mod && e.shiftKey && ['i', 'j', 'c'].includes(k)) || (mod && k === 'u')) { e.preventDefault(); log('devtools_key', e.key) }
      else if (mod && k === 'p') { e.preventDefault(); log('print_blocked') }
      else if (mod && ['c', 'v', 'x', 'a', 's', 'f', 'tab'].includes(k)) { e.preventDefault(); log('shortcut_blocked', `Ctrl+${e.key}`) }
      else if (e.altKey && k === 'tab') { log('shortcut_blocked', 'Alt+Tab') }
      else if (k === 'printscreen') { log('shortcut_blocked', 'PrintScreen') }
    }
    const onUnload = e => { e.preventDefault(); e.returnValue = '' }
    document.addEventListener('fullscreenchange', onFs)
    document.addEventListener('webkitfullscreenchange', onFs)
    document.addEventListener('visibilitychange', onVis)
    window.addEventListener('blur', onBlur)
    document.addEventListener('copy', onCopy)
    document.addEventListener('paste', onPaste)
    document.addEventListener('cut', onCut)
    document.addEventListener('contextmenu', onCtx)
    document.addEventListener('drop', onDrop)
    document.addEventListener('keydown', onKey, true)
    window.addEventListener('beforeunload', onUnload)
    return () => {
      document.removeEventListener('fullscreenchange', onFs)
      document.removeEventListener('webkitfullscreenchange', onFs)
      document.removeEventListener('visibilitychange', onVis)
      window.removeEventListener('blur', onBlur)
      document.removeEventListener('copy', onCopy)
      document.removeEventListener('paste', onPaste)
      document.removeEventListener('cut', onCut)
      document.removeEventListener('contextmenu', onCtx)
      document.removeEventListener('drop', onDrop)
      document.removeEventListener('keydown', onKey, true)
      window.removeEventListener('beforeunload', onUnload)
    }
  }, [active, log])
  return locked
}

function TestRunner({ onDone }) {
  const [t, setT] = useState(null)
  const [answers, setAnswers] = useState({})
  const [left, setLeft] = useState(null)
  const [saving, setSaving] = useState({})
  const [confirm, setConfirm] = useState(false)
  const [err, setErr] = useState('')
  const deadline = useRef(null)
  const timers = useRef({})
  const finished = useRef(false)

  const report = useCallback((type, detail) => { call('/events', { method: 'POST', body: { type, detail } }).catch(() => {}) }, [])
  const locked = useLockdown(!!t, report)
  const recorders = useRef({})
  const [recNeed, setRecNeed] = useState([])
  const [recErr, setRecErr] = useState('')
  const preview = useRef(null)

  const [secondScreen, setSecondScreen] = useState(false)
  const [warning, setWarning] = useState('')
  const warnTimer = useRef(null)
  useEffect(() => { if (t) setQuality(t.integrity?.quality) }, [t])

  // a second monitor plugged in during the test blocks it until it's removed
  useEffect(() => {
    if (!t?.record?.screen) return
    let was = false
    const check = () => {
      const now = hasSecondScreen()
      if (now && !was) report('second_screen', 'Second monitor connected')
      was = now
      setSecondScreen(now)
    }
    check()
    const iv = setInterval(check, 4000)
    window.screen?.addEventListener?.('change', check)
    return () => { clearInterval(iv); window.screen?.removeEventListener?.('change', check) }
  }, [t, report])

  // phone / distraction checks on the camera
  useEffect(() => {
    if (!t?.record?.camera || !t.integrity?.detect) return
    let det = null, cancelled = false
    const waitVideo = setInterval(async () => {
      const v = preview.current
      if (!v || !v.videoWidth) return
      clearInterval(waitVideo)
      det = await startDetector({
        video: v,
        settings: t.integrity,
        onUnavailable: why => report('detection_unavailable', why),
        onFlag: (type, detail, message, jpeg) => {
          if (cancelled || finished.current) return
          report(type, detail)
          if (jpeg) {
            fetch(`/api/portal/snapshot?kind=${type}&detail=${encodeURIComponent(detail)}`, {
              method: 'POST', headers: { Authorization: 'Bearer ' + store.get().token, 'Content-Type': 'image/jpeg' }, body: jpeg,
            }).catch(() => {})
          }
          if (t.integrity.warn) {
            setWarning(message)
            clearTimeout(warnTimer.current)
            warnTimer.current = setTimeout(() => setWarning(''), 7000)
          }
        },
      })
      if (cancelled) det.stop()
    }, 500)
    return () => { cancelled = true; clearInterval(waitVideo); det?.stop() }
  }, [t, report])

  const ensureRecording = useCallback(async () => {
    if (!t) return
    const token = store.get().token
    const missing = []
    for (const k of ['camera', 'screen'].filter(x => t.record?.[x])) {
      const stream = media[k]
      if (!isLive(stream)) { missing.push(k); continue }
      if (recorders.current[k]) continue
      try {
        recorders.current[k] = await startRecording({ kind: k, stream, token, onError: kk => report('recording_error', kk) })
        stream.getVideoTracks()[0].addEventListener('ended', () => {
          if (finished.current) return
          report(k === 'camera' ? 'camera_stopped' : 'screen_stopped')
          const r = recorders.current[k]; delete recorders.current[k]; r?.stop()
          setRecNeed(n => [...new Set([...n, k])])
        }, { once: true })
      } catch { missing.push(k) }
    }
    setRecNeed(missing)
    if (preview.current && isLive(media.camera)) preview.current.srcObject = media.camera
  }, [t, report])
  useEffect(() => { ensureRecording() }, [ensureRecording])

  const turnBackOn = async () => {
    setRecErr('')
    try {
      if (recNeed.includes('camera')) await getCamera(t.record.audio)
      if (recNeed.includes('screen')) await getScreen()
      report('recording_resumed')
      await ensureRecording()
    } catch (e) { setRecErr(e.message) }
  }

  const finish = useCallback(async () => {
    if (finished.current) return
    finished.current = true
    setWarning('')
    // let the last seconds of video upload before closing the test
    await Promise.race([Promise.all(Object.values(recorders.current).map(r => r.stop())), new Promise(ok => setTimeout(ok, 15000))])
    try { await call('/submit', { method: 'POST' }) } catch { /* the server auto-submits on expiry anyway */ }
    stopAll()
    if (inFullscreen()) document.exitFullscreen?.().catch(() => {})
    onDone()
  }, [onDone])

  useEffect(() => {
    if (performance.getEntriesByType?.('navigation')?.[0]?.type === 'reload') report('page_reload')
    call('/test').then(d => {
      setT(d)
      const a = {}; d.questions.forEach(q => { a[q.id] = q.kind === 'file' ? q.file_name : q.value }); setAnswers(a)
      deadline.current = Date.now() + d.remaining_seconds * 1000
      setLeft(d.remaining_seconds)
    }, e => { if (e.status === 410) onDone(); else setErr(e.message) })
  }, []) // eslint-disable-line

  useEffect(() => {
    if (!t) return
    const iv = setInterval(() => {
      const s = Math.max(0, Math.round((deadline.current - Date.now()) / 1000))
      setLeft(s)
      if (s <= 0) { clearInterval(iv); finish() }
    }, 1000)
    return () => clearInterval(iv)
  }, [t, finish])

  const saveNow = async (qid, value) => {
    setSaving(s => ({ ...s, [qid]: 'saving' }))
    try { await call(`/answers/${qid}`, { method: 'PUT', body: { value } }); setSaving(s => ({ ...s, [qid]: 'saved' })) }
    catch (e) { setSaving(s => ({ ...s, [qid]: 'error' })); if (e.status === 410) onDone(); if (e.status === 409) setErr(e.message) }
  }
  const setAnswer = (q, value, delay = 700) => {
    setAnswers(a => ({ ...a, [q.id]: value }))
    clearTimeout(timers.current[q.id])
    timers.current[q.id] = setTimeout(() => saveNow(q.id, value), delay)
  }
  const upload = async (q, file) => {
    const fd = new FormData(); fd.append('file', file)
    setSaving(s => ({ ...s, [q.id]: 'saving' }))
    try {
      const r = await api(`/api/portal/answers/${q.id}/file`, { method: 'POST', form: fd, token: store.get().token })
      setAnswers(a => ({ ...a, [q.id]: r.file_name })); setSaving(s => ({ ...s, [q.id]: 'saved' }))
    } catch (e) { setSaving(s => ({ ...s, [q.id]: 'error' })); alertBox(e.message) }
  }
  const [alertMsg, alertBox] = useState('')

  if (err) return <div className="portal-body"><div className="alert bad">{err}</div></div>
  if (!t) return <div className="empty">Loading your test…</div>
  const mm = String(Math.floor((left || 0) / 60)).padStart(2, '0'), ss = String((left || 0) % 60).padStart(2, '0')
  const answered = t.questions.filter(q => answers[q.id] !== '' && answers[q.id] != null).length

  return (
    <>
      <div className="portal-top" style={{ top: 0 }}>
        <b>{t.test_name}</b>
        <span className="small">{answered} of {t.questions.length} answered</span>
        <span className={'timer' + (left < 300 ? ' low' : '')}>{mm}:{ss}</span>
      </div>
      <div className="portal-body">
        {alertMsg && <div className="alert bad" onClick={() => alertBox('')}>{alertMsg}</div>}
        {warning && <div className="integrity-warn" role="alert">{warning}</div>}
        {t.questions.map((q, qi) => (
          <div key={q.id}>
          {q.section && q.section !== t.questions[qi - 1]?.section && <div className="q-section">{q.section}</div>}
          <div className="q">
            <div className="row between"><b>Question {q.number}</b><span className="small muted">{q.points} pt{q.points !== 1 ? 's' : ''} {saving[q.id] === 'saving' ? '· saving…' : saving[q.id] === 'saved' ? '· saved' : saving[q.id] === 'error' ? '· not saved, retrying when you type' : ''}</span></div>
            {q.prompt !== '(see picture)' && <div className="pre" style={{ margin: '8px 0' }}>{q.prompt}</div>}
            {q.image && <img className="q-img" src={q.image} alt="" draggable={false} />}
            {q.kind === 'mcq' && q.options.map((o, i) => (
              <div key={i} className={'opt' + (answers[q.id] === String(i) ? ' on' : '')} onClick={() => setAnswer(q, String(i), 0)}>
                <input type="radio" readOnly checked={answers[q.id] === String(i)} /><OptBody text={o} img={q.option_images?.[i]} />
              </div>
            ))}
            {q.kind === 'multi' && <>
              <div className="small muted">Select all that apply.</div>
              {q.options.map((o, i) => {
                const picked = (answers[q.id] || '').split(',').filter(Boolean)
                const on = picked.includes(String(i))
                const next = on ? picked.filter(x => x !== String(i)) : [...picked, String(i)]
                return (
                  <div key={i} className={'opt' + (on ? ' on' : '')} onClick={() => setAnswer(q, next.sort((a, b) => a - b).join(','), 0)}>
                    <input type="checkbox" readOnly checked={on} /><OptBody text={o} img={q.option_images?.[i]} />
                  </div>
                )
              })}
            </>}
            {q.kind === 'short' &&<input value={answers[q.id] || ''} onChange={e => setAnswer(q, e.target.value)} />}
            {q.kind === 'long' && <textarea style={{ minHeight: 180 }} spellCheck={false} value={answers[q.id] || ''} onChange={e => setAnswer(q, e.target.value)} />}
            {q.kind === 'file' && <div className="row"><input type="file" onChange={e => e.target.files[0] && upload(q, e.target.files[0])} style={{ maxWidth: 360 }} />{answers[q.id] && <span className="badge ok">Uploaded: {answers[q.id]}</span>}</div>}
          </div>
          </div>
        ))}
        <div className="row end"><button className="primary" onClick={() => setConfirm(true)}>Submit test</button></div>
      </div>
      {t.record?.camera && <div style={{ position: 'fixed', right: 14, bottom: 14, zIndex: 20, textAlign: 'right' }}>
        <video ref={preview} autoPlay muted playsInline style={{ width: 150, borderRadius: 8, background: '#000', display: 'block' }} />
        <span className="badge bad" style={{ marginTop: 4 }}>● Recording</span>
      </div>}
      {!t.record?.camera && t.record?.screen && <span className="badge bad" style={{ position: 'fixed', right: 14, bottom: 14, zIndex: 20 }}>● Screen is being recorded</span>}
      {recNeed.length > 0 && !confirm && (
        <div className="lock-overlay"><div className="box">
          <h1 style={{ color: '#fff' }}>Recording stopped</h1>
          <div>This test has to be recorded. Turn your {recNeed.map(k => k === 'camera' ? 'camera' : 'screen sharing (choose Entire screen)').join(' and ')} back on to continue. The timer is still running.</div>
          {recErr && <div className="alert bad">{recErr}</div>}
          <button className="primary" onClick={turnBackOn}>Turn recording back on</button>
        </div></div>
      )}
      {secondScreen && !confirm && recNeed.length === 0 && (
        <div className="lock-overlay"><div className="box">
          <h1 style={{ color: '#fff' }}>Second monitor connected</h1>
          <div>This test has to be taken on one screen. Unplug the extra monitor (or set your computer to show only one display). This has been recorded, and the timer is still running.</div>
        </div></div>
      )}
      {locked && !confirm && recNeed.length === 0 && !secondScreen && (
        <div className="lock-overlay"><div className="box">
          <h1 style={{ color: '#fff' }}>Return to full screen</h1>
          <div>The test must stay in full screen. Leaving it has been recorded. The timer is still running.</div>
          <button className="primary" onClick={goFullscreen}>Return to the test</button>
        </div></div>
      )}
      {confirm && (
        <div className="lock-overlay"><div className="box">
          <h1 style={{ color: '#fff' }}>Submit your test?</h1>
          <div>{answered} of {t.questions.length} questions answered. You can't change answers after submitting.</div>
          <div className="row"><button onClick={() => setConfirm(false)}>Keep working</button><button className="primary" onClick={finish}>Submit</button></div>
        </div></div>
      )}
    </>
  )
}

/* An answer option: text, picture, or both. Picture-only options from the Excel template are labelled "Option A". */
function OptBody({ text, img }) {
  const bare = img && /^Option [A-F]$/.test(text)
  return (
    <span className="opt-body">
      {!bare && <span>{text}</span>}
      {img && <img src={img} alt="" draggable={false} />}
    </span>
  )
}
