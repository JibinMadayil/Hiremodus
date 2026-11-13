import { useEffect, useRef, useState } from 'react'
import { get, post, fmtDate } from '../api'
import { useApp, Modal, Field } from '../ui'

const short = e => e.split('@')[0]
const toLocalInput = iso => (iso || '').slice(0, 16)
const addDays = (iso, n) => { const d = new Date(iso); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10) }

function useAvailability() {
  const [job, setJob] = useState(null)
  const [state, setState] = useState(null) // {status, slots, error, unresolved}
  const [waited, setWaited] = useState(0)
  const timer = useRef(null)
  const start = async (candidate_id, template_id, from_date) => {
    clearInterval(timer.current)
    setState({ status: 'queued' }); setWaited(0)
    const r = await post('/api/interviews/availability', { candidate_id, template_id, from_date })
    setJob(r.job_id)
    const poll = async () => {
      const s = await get(`/api/interviews/availability/${r.job_id}`)
      setState(s)
      if (s.status === 'done' || s.status === 'failed') clearInterval(timer.current)
    }
    await poll()
    timer.current = setInterval(() => { setWaited(w => w + 2); poll() }, 2000)
  }
  useEffect(() => () => clearInterval(timer.current), [])
  return { job, state, waited, start, reset: () => { clearInterval(timer.current); setJob(null); setState(null) } }
}

function SlotList({ state, waited, pick, picked }) {
  const { me } = useApp()
  if (!state) return null
  if (state.status === 'queued' || state.status === 'claimed') {
    return <div className="alert">Checking calendars through your Outlook… {waited > 12 && !me.connector_online && <><br />Your Outlook Connector looks offline. Start it, or enter a time manually below.</>}</div>
  }
  if (state.status === 'failed') return <div className="alert bad">Calendar check failed: {state.error}</div>
  if (!state.slots?.length) return <div className="alert warn">No free time found in the search window for the required people. Enter a time manually instead.</div>
  return (
    <div className="col" style={{ gap: 8 }}>
      {state.unresolved?.length > 0 && <div className="alert warn small">Outlook couldn't read the calendars of: {state.unresolved.join(', ')}. They're treated as free.</div>}
      {state.slots.map(s => (
        <div key={s.start} className={'slot' + (picked?.start === s.start ? ' on' : '')} onClick={() => pick(s)}>
          <div className="row between"><b>{fmtDate(s.start)}</b>{s.tier === 2 && <span className="badge warn">Fallback: fewer rotating interviewers</span>}</div>
          {(s.flex_free.length + s.flex_busy.length) > 0 && <div className="chips">
            {s.flex_free.map(e => <span key={e} className="chip free">{short(e)} free</span>)}
            {s.flex_busy.map(e => <span key={e} className="chip busy">{short(e)} busy → optional</span>)}
          </div>}
        </div>
      ))}
    </div>
  )
}

export function ScheduleModal({ candidate, onClose, onDone }) {
  const { meta, toast } = useApp()
  const deptTpls = meta.interview_templates.filter(t => t.active && t.department_id === candidate.department_id)
  const [showAll, setShowAll] = useState(deptTpls.length === 0)
  const tpls = showAll ? meta.interview_templates.filter(t => t.active) : deptTpls
  const [tid, setTid] = useState(tpls[0]?.id || '')
  const tpl = meta.interview_templates.find(t => t.id === +tid)
  const [moduleId, setModuleId] = useState(candidate.module_id || '')
  const [extraCc, setExtraCc] = useState('')
  const [step, setStep] = useState(1)
  const [mode, setMode] = useState('find')
  const [manual, setManual] = useState('')
  const [picked, setPicked] = useState(null)
  const [req, setReq] = useState('')
  const [opt, setOpt] = useState('')
  const [preview, setPreview] = useState(null)
  const [includeTest, setIncludeTest] = useState(true)
  const [confirmMail, setConfirmMail] = useState(true)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const av = useAvailability()

  useEffect(() => { av.reset(); setPicked(null) }, [tid]) // eslint-disable-line
  useEffect(() => { if (tpl?.reuse_previous_module && candidate.module_id) setModuleId(candidate.module_id) }, [tid]) // eslint-disable-line

  const choose = s => { setPicked(s); setReq(s.required.join('; ')); setOpt(s.optional.join('; ')) }
  const checkManual = async () => {
    setErr('')
    if (!manual) return setErr('Pick a date and time')
    const r = await post('/api/interviews/evaluate', { template_id: +tid, start: manual, job_id: mode === 'manual' && av.state?.status === 'done' ? av.job : null })
    choose(r)
  }
  const toPreview = async () => {
    setErr('')
    if (tpl.requires_module && !moduleId) return setErr('Pick a training module')
    try {
      const p = await post('/api/interviews/preview', { candidate_id: candidate.id, template_id: +tid, start: picked.start, module_id: moduleId ? +moduleId : null })
      setPreview(p); setStep(3)
    } catch (e) { setErr(e.message) }
  }
  const book = async () => {
    setBusy(true); setErr('')
    try {
      await post('/api/interviews', {
        candidate_id: candidate.id, template_id: +tid, start: picked.start, required: req.split(/[;,\s]+/).filter(Boolean),
        optional: opt.split(/[;,\s]+/).filter(Boolean), module_id: moduleId ? +moduleId : null, extra_cc: extraCc,
        subject: preview.subject, body: preview.body, include_test: includeTest, send_confirmation: confirmMail,
      })
      toast('Interview booked. The invite goes out from your Outlook.')
      onDone()
    } catch (e) { setErr(e.message); setBusy(false) }
  }

  const footer = step === 1
    ? <><button onClick={onClose}>Cancel</button><button className="primary" disabled={!tid} onClick={() => setStep(2)}>Next: pick a time</button></>
    : step === 2
      ? <><button onClick={() => setStep(1)}>Back</button><button className="primary" disabled={!picked} onClick={toPreview}>Next: review invite</button></>
      : <><button onClick={() => setStep(2)}>Back</button><button className="primary" disabled={busy} onClick={book}>Send invite</button></>

  return (
    <Modal wide title={`Schedule interview: ${candidate.first_name} ${candidate.last_name}`} onClose={onClose} footer={footer}>
      {step === 1 && <>
        <Field label="Interview type">
          <select value={tid} onChange={e => setTid(e.target.value)}>
            {tpls.map(t => <option key={t.id} value={t.id}>{t.name} ({t.duration_min} min{t.includes_test ? ', with test' : ''})</option>)}
          </select>
        </Field>
        {deptTpls.length > 0 && <label className="check"><input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)} /> Show interview types from other departments</label>}
        {tpl?.requires_module && (
          <Field label="Training module" hint={tpl.reuse_previous_module ? 'Defaults to the module from round 1' : 'Remembered for round 2'}>
            <select value={moduleId} onChange={e => setModuleId(e.target.value)}><option value="">Choose…</option>{meta.modules.filter(m => m.active).map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
          </Field>
        )}
        {tpl?.ask_extra_cc && <Field label="Extra CC (optional)"><input value={extraCc} onChange={e => setExtraCc(e.target.value)} placeholder="name@novamodus.com" /></Field>}
        {tpl?.includes_test && <div className="alert">This interview includes a test. HireModus creates a login for the candidate and puts it in the invite. If the training module has its own test (for example the General Ledger questionnaire), that test is used.</div>}
      </>}

      {step === 2 && <>
        <div className="tabs">
          <button className={mode === 'find' ? 'on' : ''} onClick={() => setMode('find')}>Find free times</button>
          <button className={mode === 'manual' ? 'on' : ''} onClick={() => setMode('manual')}>Enter a time</button>
        </div>
        {mode === 'find' && <>
          <div className="row"><button className="primary" onClick={() => av.start(candidate.id, +tid)}>{av.state ? 'Search again' : 'Check calendars'}</button>
            <span className="muted small">{tpl.search_offset_days ? `Starts ${tpl.search_offset_days} days out. ` : ''}Uses the template's days, hours and interviewers.</span></div>
          <SlotList state={av.state} waited={av.waited} pick={choose} picked={picked} />
        </>}
        {mode === 'manual' && <>
          <div className="row">
            <input type="datetime-local" style={{ maxWidth: 240 }} value={manual} onChange={e => setManual(e.target.value)} />
            <button onClick={checkManual}>Use this time</button>
            {!av.state && <button className="ghost" onClick={() => av.start(candidate.id, +tid)}>Load calendars to check conflicts</button>}
            {av.state?.status === 'done' && <span className="badge ok">Calendars loaded</span>}
          </div>
        </>}
        {picked && <div className="card">
          <h3>{fmtDate(picked.start)}</h3>
          {picked.warnings?.map(w => <div key={w} className="alert warn small" style={{ marginBottom: 6 }}>{w}</div>)}
          <div className="grid2">
            <Field label="Required attendees" hint="The candidate is added automatically"><textarea style={{ minHeight: 60 }} value={req} onChange={e => setReq(e.target.value)} /></Field>
            <Field label="Optional attendees"><textarea style={{ minHeight: 60 }} value={opt} onChange={e => setOpt(e.target.value)} /></Field>
          </div>
        </div>}
      </>}

      {step === 3 && preview && <>
        <Field label="Subject"><input value={preview.subject} onChange={e => setPreview({ ...preview, subject: e.target.value })} /></Field>
        <Field label="Invite text" hint="{{test_block}} is replaced with the candidate's test login when you send"><textarea className="tall" value={preview.body} onChange={e => setPreview({ ...preview, body: e.target.value })} /></Field>
        <div className="row">
          {preview.includes_test && <label className="check"><input type="checkbox" checked={includeTest} onChange={e => setIncludeTest(e.target.checked)} /> Create a login for <b>{preview.test_name}</b> and include it</label>}
          <label className="check"><input type="checkbox" checked={confirmMail} onChange={e => setConfirmMail(e.target.checked)} /> Also send a separate confirmation email</label>
        </div>
      </>}
      {err && <div className="alert bad">{err}</div>}
    </Modal>
  )
}

export function RescheduleModal({ interview, candidate, onClose, onDone }) {
  const { toast } = useApp()
  const [mode, setMode] = useState('find')
  const [manual, setManual] = useState(toLocalInput(interview.start))
  const [picked, setPicked] = useState(null)
  const [notify, setNotify] = useState(true)
  const [err, setErr] = useState('')
  const av = useAvailability()
  const fromDate = addDays(interview.start, 7)
  const go = async () => {
    setErr('')
    const start = mode === 'find' ? picked?.start : manual
    if (!start) return setErr('Pick a time')
    try {
      await post(`/api/interviews/${interview.id}/reschedule`, { start, notify_candidate: notify })
      toast('Reschedule sent to Outlook'); onDone()
    } catch (e) { setErr(e.message) }
  }
  return (
    <Modal wide title="Reschedule interview" onClose={onClose} footer={<><button onClick={onClose}>Cancel</button><button className="primary" onClick={go}>Reschedule</button></>}>
      <div className="muted">Currently {fmtDate(interview.start)}. The existing Outlook invite is updated for everyone.</div>
      <div className="tabs">
        <button className={mode === 'find' ? 'on' : ''} onClick={() => setMode('find')}>Find free times</button>
        <button className={mode === 'manual' ? 'on' : ''} onClick={() => setMode('manual')}>Enter a time</button>
      </div>
      {mode === 'find' && (interview.template_id ? <>
        <div className="row"><button className="primary" onClick={() => av.start(candidate.id, interview.template_id, fromDate)}>Check calendars</button><span className="muted small">Searches from the week after the current date.</span></div>
        <SlotList state={av.state} waited={av.waited} pick={setPicked} picked={picked} />
      </> : <div className="alert warn">This interview has no template (imported), so enter a time manually.</div>)}
      {mode === 'manual' && <input type="datetime-local" style={{ maxWidth: 240 }} value={manual} onChange={e => setManual(e.target.value)} />}
      <label className="check"><input type="checkbox" checked={notify} onChange={e => setNotify(e.target.checked)} /> Email the candidate that it moved</label>
      {err && <div className="alert bad">{err}</div>}
    </Modal>
  )
}
