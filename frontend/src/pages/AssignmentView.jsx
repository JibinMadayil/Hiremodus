import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { auth, get, post, put, fmtUtc } from '../api'
import { useApp, Field, Loading, TestBadge, Confirm } from '../ui'

const EVENT_LABEL = {
  signed_in: 'Signed in', started: 'Started the test', resumed: 'Reopened with a new start code', submitted: 'Submitted',
  time_expired: 'Time ran out, auto-submitted', fullscreen_exit: 'Left full screen', fullscreen_enter: 'Returned to full screen',
  tab_hidden: 'Switched tab or minimised', window_blur: 'Clicked outside the test window', copy_blocked: 'Tried to copy',
  paste_blocked: 'Tried to paste', cut_blocked: 'Tried to cut', context_menu_blocked: 'Right-clicked', shortcut_blocked: 'Blocked keyboard shortcut',
  print_blocked: 'Tried to print', camera_stopped: 'Camera turned off', screen_stopped: 'Stopped sharing the screen',
  recording_resumed: 'Turned recording back on', recording_error: 'Recording upload failed', devtools_key: 'Pressed a developer-tools key', wrong_code: 'Entered a wrong start code',
  file_uploaded: 'Uploaded a file', submitted_by_staff: 'Submitted by staff', page_reload: 'Reloaded the page',
  phone_detected: 'Phone in view', no_face: 'Nobody in front of the camera', multiple_faces: 'More than one person in view',
  looking_away: 'Looking away from the screen', second_screen: 'Second monitor connected',
  detection_unavailable: 'Phone and distraction checks could not run on this computer', unsupported_browser: 'Tried an unsupported browser',
}
const WARN = new Set(['camera_stopped', 'screen_stopped', 'recording_error', 'fullscreen_exit', 'tab_hidden', 'window_blur', 'copy_blocked', 'paste_blocked', 'cut_blocked', 'context_menu_blocked', 'shortcut_blocked', 'print_blocked', 'devtools_key', 'wrong_code', 'page_reload',
  'phone_detected', 'no_face', 'multiple_faces', 'looking_away', 'second_screen', 'detection_unavailable', 'unsupported_browser'])

export default function AssignmentView() {
  const { id } = useParams()
  const { toast } = useApp()
  const [a, setA] = useState(null)
  const [grades, setGrades] = useState({})
  const [notes, setNotes] = useState('')
  const [force, setForce] = useState(false)
  const players = useRef({})
  const load = () => get(`/api/assignments/${id}`).then(d => {
    setA(d); setNotes(d.reviewer_notes || '')
    const g = {}; d.items.forEach(it => { g[it.question.id] = { score: it.answer?.score ?? '', comment: it.answer?.comment || '' } }); setGrades(g)
  })
  useEffect(() => { load() }, [id]) // eslint-disable-line
  useEffect(() => { if (a?.status === 'in_progress') { const t = setInterval(load, 8000); return () => clearInterval(t) } }, [a?.status]) // eslint-disable-line
  if (!a) return <Loading />
  const warnCount = a.events.filter(e => WARN.has(e.type)).length
  const counts = {}; a.events.forEach(e => { if (WARN.has(e.type)) counts[e.type] = (counts[e.type] || 0) + 1 })
  const manual = a.items.filter(i => i.question.kind !== 'mcq' && i.question.kind !== 'multi').reduce((s, i) => s + (+grades[i.question.id]?.score || 0), 0)
  const save = async final => {
    try {
      await put(`/api/assignments/${id}/grade`, { items: a.items.filter(i => i.question.kind !== 'mcq' && i.question.kind !== 'multi').map(i => ({ question_id: i.question.id, score: grades[i.question.id].score === '' ? null : +grades[i.question.id].score, comment: grades[i.question.id].comment })), reviewer_notes: notes, final })
      toast(final ? 'Grading finished' : 'Saved'); load()
    } catch (e) { toast(e.message, 'bad') }
  }
  const download = async (ans) => {
    const r = await fetch(`/api/assignments/${id}/file/${ans.id}`, { headers: { Authorization: 'Bearer ' + auth.token } })
    const blob = await r.blob(); const url = URL.createObjectURL(blob)
    const link = document.createElement('a'); link.href = url; link.download = ans.file_name; link.click(); URL.revokeObjectURL(url)
  }
  const gradable = ['submitted', 'graded'].includes(a.status)
  return (
    <div className="col" style={{ maxWidth: 1000 }}>
      <div className="page-head">
        <div><div className="small"><Link to={`/candidates/${a.candidate_id}`}>← {a.candidate_name}</Link></div><h1>{a.test.name}</h1>
          <div className="row"><TestBadge status={a.status} />{a.auto_submitted && <span className="badge warn">Auto-submitted when time ran out</span>}<span className="muted small">Login {a.username}</span></div></div>
        <div className="row">
          {a.status === 'in_progress' && <button className="danger" onClick={() => setForce(true)}>Submit now</button>}
          {gradable && a.can_see_papers && <><button onClick={() => save(false)}>Save</button><button className="primary" onClick={() => save(true)}>Finish grading</button></>}
        </div>
      </div>
      <div className="grid3">
        <div className="card stat"><span className="muted small">Multiple choice (automatic)</span><span className="n">{a.auto_score ?? '-'}</span></div>
        <div className="card stat"><span className="muted small">Written / files (manual)</span><span className="n">{gradable ? (a.can_see_papers ? manual : (a.manual_score ?? '-')) : '-'}</span></div>
        <div className="card stat"><span className="muted small">Total</span><span className="n">{a.auto_score != null ? `${(a.auto_score || 0) + (a.can_see_papers ? manual : (a.manual_score || 0))} / ${a.total_points}` : '-'}</span></div>
      </div>
      <Recordings recs={a.recordings || []} players={players} />
      <Snapshots snaps={a.snapshots || []} recs={a.recordings} players={players} />
      <div className="card">
        <div className="row between"><h2 style={{ margin: 0 }}>Integrity log</h2>{warnCount ? <span className="badge warn">{warnCount} warning{warnCount > 1 ? 's' : ''}</span> : <span className="badge ok">No warnings</span>}</div>
        {warnCount > 0 && <div className="chips" style={{ margin: '10px 0' }}>{Object.entries(counts).map(([k, n]) => <span key={k} className="chip busy">{EVENT_LABEL[k] || k}: {n}</span>)}</div>}
        <details><summary className="muted small">Full timeline ({a.events.length})</summary>
          <div className="timeline" style={{ marginTop: 8 }}>{a.events.map((e, i) => <div key={i} className="item small"><span style={{ color: WARN.has(e.type) ? 'var(--bad)' : undefined }}>{EVENT_LABEL[e.type] || e.type}</span> <span className="muted">· {fmtUtc(e.t)}{e.detail ? ` · ${e.detail}` : ''}</span>
                {canSeek(a.recordings, e.t) && <button className="sm ghost" onClick={() => seekAll(players, a.recordings, e.t)}>▶ Watch this moment</button>}</div>)}</div>
        </details>
      </div>
      {!a.can_see_papers && <div className="card muted">Questions and answers are only visible to Recruiters. You can see the score, integrity log and recording.</div>}
      {a.items.map((it, i) => {
        const q = it.question, ans = it.answer
        return (
          <div key={q.id} className="card col">
            <div className="row between"><b>Question {i + 1}</b><span className="muted small">{q.points} pt{q.points !== 1 ? 's' : ''}</span></div>
            {q.section && <div className="q-section" style={{ margin: 0 }}>{q.section}</div>}
            {q.prompt !== '(see picture)' && <div className="pre">{q.prompt}</div>}
            {q.image && <img className="q-img" src={q.image} alt="" />}
            {(q.kind === 'mcq' || q.kind === 'multi') ? (
              <div className="col" style={{ gap: 4 }}>
                {q.kind === 'multi' && ans?.value && <span className={'badge ' + (ans.score ? 'ok' : 'bad')} style={{ alignSelf: 'flex-start' }}>{ans.score ? 'All correct options picked' : 'Not an exact match, 0 points'}</span>}
                {q.options.map((o, k) => {
                const chosen = ans && (ans.value || '').split(',').includes(String(k))
                const right = q.kind === 'mcq' ? q.correct_index === k : (q.correct_indices || []).includes(k)
                return <div key={k} className="small" style={{ padding: '4px 8px', borderRadius: 6, background: right ? 'var(--ok-soft)' : chosen ? 'var(--bad-soft)' : undefined }}>{chosen ? '● ' : '○ '}{o}{right && ' (correct)'}{q.option_images?.[k] && <img src={q.option_images[k]} alt="" style={{ display: 'block', maxWidth: 160, maxHeight: 110, marginTop: 4, borderRadius: 6 }} />}</div>
              })}{!ans?.value && <span className="badge warn">Not answered</span>}</div>
            ) : q.kind === 'file' ? (
              ans?.file_name ? <div><button className="sm" onClick={() => download(ans)}>Download {ans.file_name}</button></div> : <span className="badge warn">No file</span>
            ) : (
              <div className="pre card" style={{ background: '#fafbfc' }}>{ans?.value || <span className="muted">No answer</span>}</div>
            )}
            {q.kind !== 'mcq' && q.kind !== 'multi' && gradable && <div className="row" style={{ alignItems: 'flex-end' }}>
              <Field label={`Score (0–${q.points})`}><input type="number" min={0} max={q.points} step="0.5" style={{ width: 100 }} value={grades[q.id]?.score} onChange={e => setGrades(g => ({ ...g, [q.id]: { ...g[q.id], score: e.target.value } }))} /></Field>
              <Field label="Comment" className="" ><input style={{ minWidth: 360 }} value={grades[q.id]?.comment} onChange={e => setGrades(g => ({ ...g, [q.id]: { ...g[q.id], comment: e.target.value } }))} /></Field>
            </div>}
          </div>
        )
      })}
      {gradable && a.can_see_papers && <div className="card"><Field label="Reviewer notes"><textarea value={notes} onChange={e => setNotes(e.target.value)} /></Field></div>}
      {force && <Confirm title="Submit this test now?" danger confirmLabel="Submit" message="The candidate's answers so far are saved and the test closes immediately." onClose={() => setForce(false)}
        onConfirm={() => post(`/api/assignments/${id}/force-submit`).then(() => { setForce(false); load() })} />}
    </div>
  )
}


const ms = iso => new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime()

function sessionFor(recs, kind, t) {
  const at = ms(t)
  return (recs || []).find(r => r.kind === kind && r.url && ms(r.started_at) - 2000 <= at && at <= ms(r.last_chunk_at || r.started_at) + 15000)
}
function canSeek(recs, t) { return !!(sessionFor(recs, 'camera', t) || sessionFor(recs, 'screen', t)) }
function seekAll(players, recs, t) {
  ;['camera', 'screen'].forEach(kind => {
    const r = sessionFor(recs, kind, t)
    const v = r && players.current[r.id]
    if (v) { v.currentTime = Math.max(0, (ms(t) - ms(r.started_at)) / 1000 - 3); v.play().catch(() => {}); v.scrollIntoView({ block: 'center', behavior: 'smooth' }) }
  })
}

function RecVideo({ rec, players }) {
  // browser-made WebM files don't store their length; jumping to the end once makes the seek bar work
  const fix = e => {
    const v = e.currentTarget
    if (v.duration === Infinity) {
      v.currentTime = 1e101
      v.ontimeupdate = () => { v.ontimeupdate = null; v.currentTime = 0 }
    }
  }
  return <video ref={el => { if (el) players.current[rec.id] = el }} src={rec.url} controls preload="metadata" onLoadedMetadata={fix}
    style={{ width: '100%', background: '#000', borderRadius: 8, maxHeight: 420 }} />
}

function Recordings({ recs, players }) {
  if (!recs.length) return null
  const deleted = recs.every(r => r.deleted)
  const mb = recs.reduce((s, r) => s + r.bytes, 0) / 1048576
  return (
    <div className="card col">
      <div className="row between"><h2 style={{ margin: 0 }}>Recording</h2>
        <span className="small muted">{deleted ? 'Deleted at midnight on the day of the test' : `${mb.toFixed(0)} MB · deleted automatically ${fmtUtc(recs[0].delete_at)}`}</span></div>
      {!deleted && <div className="grid2">
        {['screen', 'camera'].map(kind => {
          const list = recs.filter(r => r.kind === kind)
          if (!list.length) return null
          return <div key={kind} className="col" style={{ gap: 8 }}>
            <b>{kind === 'screen' ? 'Screen' : 'Camera'}</b>
            {list.map((r, i) => r.url
              ? <div key={r.id}>{list.length > 1 && <div className="small muted">Part {i + 1}, from {fmtUtc(r.started_at)}</div>}<RecVideo rec={r} players={players} /></div>
              : <div key={r.id} className="small muted">{r.deleted ? 'Deleted' : 'No video received'}</div>)}
          </div>
        })}
      </div>}
      {!deleted && <div className="small muted">Use “Watch this moment” in the integrity log to jump to a warning. A new part starts whenever the candidate had to turn recording back on.</div>}
    </div>
  )
}

function Snapshots({ snaps, recs, players }) {
  if (!snaps.length) return null
  const live = snaps.filter(x => x.url)
  return (
    <div className="card col">
      <div className="row between"><h2 style={{ margin: 0 }}>Camera snapshots</h2>
        <span className="small muted">Taken when a check flagged something · deleted at midnight with the recording</span></div>
      {live.length ? <div className="snap-strip">{live.map(x => (
        <figure key={x.id}>
          <a href={x.url} target="_blank" rel="noreferrer"><img src={x.url} alt={EVENT_LABEL[x.kind] || x.kind} /></a>
          <figcaption><b>{EVENT_LABEL[x.kind] || x.kind}</b><br /><span className="muted">{fmtUtc(x.at)}{x.detail ? ` · ${x.detail}` : ''}</span>
            {canSeek(recs, x.at) && <><br /><button className="sm ghost" onClick={() => seekAll(players, recs, x.at)}>▶ Watch this moment</button></>}</figcaption>
        </figure>))}</div>
        : <div className="small muted">{snaps.length} snapshot{snaps.length > 1 ? 's were' : ' was'} taken and deleted at midnight.</div>}
      <div className="small muted">These checks flag things for you to look at. A flag isn't proof: check the recording before deciding.</div>
    </div>
  )
}
