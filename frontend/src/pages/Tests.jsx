import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { get, post, api, auth, fmtUtc } from '../api'
import { useApp, Loading, TestBadge, DeptBadges, Modal } from '../ui'
import { StartCode } from './CandidateDetail'

export default function Tests() {
  const { can } = useApp()
  const [tab, setTab] = useState('live')
  const [tests, setTests] = useState(null)
  const [assign, setAssign] = useState(null)
  const [code, setCode] = useState(null)
  const [upload, setUpload] = useState(false)
  const load = () => {
    if (can('tests.papers')) get('/api/tests').then(setTests)
    get('/api/assignments').then(setAssign)
  }
  useEffect(load, [])
  useEffect(() => { const t = setInterval(() => get('/api/assignments').then(setAssign), 10000); return () => clearInterval(t) }, [])
  const filt = {
    live: a => ['assigned', 'in_progress'].includes(a.status),
    grade: a => a.status === 'submitted',
    done: a => ['graded', 'revoked'].includes(a.status),
  }
  return (
    <div className="col">
      <div className="page-head"><div><h1>Tests</h1><div className="muted">Candidates take these on the test portal after an interviewer gives them a start code.</div></div>
        {can('tests.papers') && <div className="row">
          <button onClick={downloadTemplate}>Download Excel template</button>
          <button onClick={() => setUpload(true)}>Upload test paper</button>
          <Link className="btn primary" to="/tests/new">New test</Link></div>}</div>
      <div className="tabs">
        <button className={tab === 'live' ? 'on' : ''} onClick={() => setTab('live')}>Waiting / in progress</button>
        <button className={tab === 'grade' ? 'on' : ''} onClick={() => setTab('grade')}>Needs grading {assign && `(${assign.filter(filt.grade).length})`}</button>
        <button className={tab === 'done' ? 'on' : ''} onClick={() => setTab('done')}>Finished</button>
        {can('tests.papers') && <button className={tab === 'tests' ? 'on' : ''} onClick={() => setTab('tests')}>Test papers</button>}
      </div>
      {tab === 'tests' ? (!tests ? <Loading /> :
        <div className="card tight"><table>
          <thead><tr><th>Test</th><th>Departments</th><th>Length</th><th>Questions</th><th>Points</th><th></th></tr></thead>
          <tbody>{tests.map(t => (
            <tr key={t.id}><td><b>{t.name}</b>{!t.active && <span className="badge" style={{ marginLeft: 6 }}>Off</span>}{t.allow_file_upload && <span className="badge info" style={{ marginLeft: 6 }}>File upload</span>}</td>
              <td><DeptBadges ids={t.department_ids} /></td><td>{t.duration_min} min</td><td>{t.questions.length}{t.pool_note && <div className="small muted">{t.pool_note}</div>}</td><td>{t.total_points}</td>
              <td><Link to={`/tests/${t.id}`}>Edit</Link></td></tr>
          ))}</tbody>
        </table></div>
      ) : (!assign ? <Loading /> :
        <div className="card tight"><table>
          <thead><tr><th>Candidate</th><th>Test</th><th>Status</th><th>Started</th><th>Score</th><th>Flags</th><th></th></tr></thead>
          <tbody>
            {assign.filter(filt[tab]).map(a => {
              const flags = (a.events || []).filter(e => !['signed_in', 'started', 'submitted', 'resumed', 'fullscreen_enter', 'file_uploaded'].includes(e.type)).length
              return (
                <tr key={a.id}>
                  <td><Link to={`/candidates/${a.candidate_id}`}>{a.candidate_name}</Link><div className="small muted mono">{a.username}</div></td>
                  <td>{a.test_name}</td><td><TestBadge status={a.status} /></td>
                  <td className="small">{a.started_at ? fmtUtc(a.started_at) : ''}</td>
                  <td>{a.auto_score != null ? `${(a.auto_score || 0) + (a.manual_score || 0)} / ${a.total_points}` : ''}</td>
                  <td>{flags > 0 && <span className="badge warn">{flags} warning{flags > 1 ? 's' : ''}</span>}</td>
                  <td className="row end">
                    {can('tests.start_code') && ['assigned', 'in_progress'].includes(a.status) && <button className="sm primary" onClick={() => setCode(a)}>Start code</button>}
                    {(can('tests.results') || can('tests.papers')) && a.status !== 'assigned' && a.status !== 'revoked' && <Link className="btn sm" to={`/results/${a.id}`}>{a.status === 'in_progress' ? 'Watch' : 'Open'}</Link>}
                  </td>
                </tr>
              )
            })}
            {!assign.filter(filt[tab]).length && <tr><td colSpan={7} className="empty">Nothing here.</td></tr>}
          </tbody>
        </table></div>
      )}
      {code && <StartCode a={code} onClose={() => { setCode(null); load() }} />}
      {upload && <UploadPaper tests={tests || []} onClose={() => setUpload(false)} onDone={() => { setUpload(false); load() }} />}
    </div>
  )
}

async function downloadTemplate() {
  const r = await fetch('/api/test-paper/template.xlsx', { headers: { Authorization: 'Bearer ' + auth.token } })
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a'); a.href = url; a.download = 'HireModus test paper template.xlsx'; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

const KIND_LABEL = { mcq: 'Single choice', multi: 'Multiple choice', short: 'Short answer', long: 'Long answer', file: 'File upload' }
const LETTERS = 'ABCDEF'

function UploadPaper({ tests, onClose, onDone }) {
  const { meta, toast, refreshMeta } = useApp()
  const nav = useNavigate()
  const [pv, setPv] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [mode, setMode] = useState('new')
  const [target, setTarget] = useState('')
  const dname = id => meta.departments.find(d => d.id === id)?.name || ''

  const read = async file => {
    setErr(''); setBusy(true); setPv(null)
    const fd = new FormData(); fd.append('file', file)
    try { setPv(await api('/api/test-paper/preview', { method: 'POST', form: fd })) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const save = async () => {
    setErr(''); setBusy(true)
    try {
      const t = await post('/api/test-paper/commit', { mode, test_id: mode === 'new' ? null : +target, details: pv.details, questions: pv.questions })
      toast(mode === 'new' ? 'Test created' : mode === 'add' ? 'Questions added' : 'Questions replaced'); refreshMeta()
      onDone(); nav(`/tests/${t.id}`)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const blocked = !pv || pv.errors.length > 0 || !pv.questions.length || (mode !== 'new' && !target)
  return (
    <Modal wide title="Upload test paper" onClose={onClose} footer={<>
      <button onClick={onClose}>Cancel</button>
      <button className="primary" disabled={blocked || busy} onClick={save}>{mode === 'new' ? 'Create test' : mode === 'add' ? 'Add questions' : 'Replace questions'}</button>
    </>}>
      <div className="col">
        <div className="muted small">Fill in the HireModus Excel template (Download Excel template on the Tests page), then choose it here. Nothing is saved until you check the preview and confirm.</div>
        <input type="file" accept=".xlsx,.xlsm" onChange={e => e.target.files[0] && read(e.target.files[0])} />
        {busy && !pv && <div className="muted">Reading the file…</div>}
        {err && <div className="alert bad">{err}</div>}
        {pv && <>
          {pv.errors.length > 0 && <div className="alert bad"><b>Fix these in the file and choose it again:</b><ul style={{ margin: '6px 0 0 18px', padding: 0 }}>{pv.errors.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
          {pv.warnings.length > 0 && <div className="alert warn"><ul style={{ margin: 0, paddingLeft: 18 }}>{pv.warnings.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
          <div className="card col" style={{ gap: 8 }}>
            <div className="row">
              <label className="check"><input type="radio" checked={mode === 'new'} onChange={() => setMode('new')} /> Create a new test</label>
              <label className="check"><input type="radio" checked={mode === 'add'} onChange={() => setMode('add')} /> Add to an existing test</label>
              <label className="check"><input type="radio" checked={mode === 'replace'} onChange={() => setMode('replace')} /> Replace an existing test's questions</label>
            </div>
            {mode === 'new'
              ? <div className="small"><b>{pv.details.name || '(no name)'}</b> · {pv.details.department_ids.map(dname).join(', ') || 'no department'} · {pv.details.duration_min} min{pv.details.shuffle_options ? ' · options shuffled' : ''}{pv.details.shuffle_questions ? ' · questions shuffled' : ''}</div>
              : <select value={target} onChange={e => setTarget(e.target.value)}><option value="">Choose the test…</option>{tests.filter(t => t.active).map(t => <option key={t.id} value={t.id}>{t.name} ({t.questions.length} questions)</option>)}</select>}
            {mode === 'replace' && <div className="small muted">The test's current questions are removed. Results already taken stay as they are. Any question pool is reset to "every question".</div>}
            {mode !== 'new' && <div className="small muted">The test keeps its own name, departments and settings; only questions come from the file.</div>}
          </div>
          <div className="small muted">{pv.questions.length} question{pv.questions.length !== 1 ? 's' : ''} · {pv.pictures} picture{pv.pictures !== 1 ? 's' : ''} · {pv.questions.reduce((s, q) => s + (+q.points || 0), 0)} points</div>
          <div className="card tight" style={{ maxHeight: 380, overflow: 'auto' }}><table>
            <thead><tr><th>Row</th><th>Type</th><th>Question</th><th>Options</th><th>Correct</th><th>Pts</th></tr></thead>
            <tbody>{pv.questions.map(q => (
              <tr key={q.row}>
                <td className="small muted">{q.row}</td>
                <td className="small">{KIND_LABEL[q.kind]}{q.section && <div className="muted">{q.section}</div>}</td>
                <td className="small" style={{ maxWidth: 320 }}>{q.prompt !== '(see picture)' && q.prompt}{q.image && <div className="thumbs"><img src={q.image} alt="" style={{ width: 120 }} /></div>}</td>
                <td className="small">{q.options.length > 0 && <div className="col" style={{ gap: 2 }}>{q.options.map((o, k) => <div key={k}>{LETTERS[k]}. {/^Option [A-F]$/.test(o) && q.option_images[k] ? '' : o}{q.option_images[k] && <img src={q.option_images[k]} alt="" style={{ height: 32, verticalAlign: 'middle', marginLeft: 4, borderRadius: 4 }} />}</div>)}</div>}</td>
                <td className="small">{q.kind === 'mcq' ? LETTERS[q.correct_index] : q.kind === 'multi' ? q.correct_indices.map(k => LETTERS[k]).join(', ') : <span className="muted">Panel marks</span>}</td>
                <td className="small">{q.points}</td>
              </tr>))}</tbody>
          </table></div>
        </>}
      </div>
    </Modal>
  )
}
