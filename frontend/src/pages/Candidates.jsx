import { useDeferredValue, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { get, post, put, fmtDate, fullName } from '../api'
import Icon from '../icons'
import { useApp, Modal, Field, StageBadge, DeptBadge, Loading, ErrorBox } from '../ui'

const BASE_COLS = {
  email: { label: 'Email', cell: c => c.access === 'summary' ? <Locked /> : c.email || <span className="badge warn">No email</span> },
  phone: { label: 'Phone', cell: c => c.phone },
  stage: { label: 'Stage', cell: c => <StageBadge id={c.stage_id} /> },
  department: { label: 'Department', cell: c => <DeptBadge id={c.department_id} /> },
  days: { label: 'Days since contact', cell: c => <AgingCell a={c.aging} /> },
  ribbon: { label: 'Ribbon', cell: c => c.ribbon_rating },
  next_interview: { label: 'Next interview', cell: c => c.next_interview ? <span className="small">{fmtDate(c.next_interview)}</span> : '' },
  date_added: { label: 'Date added', cell: c => c.date_added ? <span className="small muted">{fmtDate(c.date_added + 'T12:00', false)}</span> : '' },
  location: { label: 'Location', cell: c => c.location },
  source: { label: 'Source', cell: c => c.source },
  area_fit: { label: 'Area fit', cell: c => c.area_fit },
  practice: { label: 'Practice', cell: c => c.practice },
  final_decision: { label: 'Final decision', cell: c => c.final_decision },
  test_score: { label: 'Test score', cell: c => c.test_score },
}
const DEFAULT_COLS = ['email', 'stage', 'department', 'days', 'ribbon', 'next_interview', 'date_added']

export function Locked({ text = 'Other department' }) {
  return <span className="lockpill" title="Read-only: this candidate belongs to a department you don't work in"><Icon name="lock" size={12} />{text}</span>
}

export function AgingCell({ a }) {
  if (!a) return <span className="muted small">n/a</span>
  if (a.status === 'paused') return <span className="badge info" title={a.next_interview ? 'Interview ' + fmtDate(a.next_interview) : ''}>Interview booked</span>
  if (a.status === 'exempt') return <span className="badge">Keep · {a.days}d</span>
  const cls = a.status === 'alert' ? 'warn' : (a.status === 'due' || a.status === 'grace') ? 'bad' : ''
  const tip = a.reject_on ? `Auto-reject on ${fmtDate(a.reject_on + 'T12:00', false)}` : ''
  return <span className={'badge ' + cls} title={tip}>{a.days} day{a.days === 1 ? '' : 's'}</span>
}

export default function Candidates() {
  const { meta, can, toast, me } = useApp()
  const [params, setParams] = useSearchParams()
  const scoped = me.scope_ids != null
  const [mine, setMine] = useState(params.get('all') !== '1')
  const stage = params.get('stage') || ''
  const dept = params.get('dept') || ''
  const agingF = params.get('aging') || ''
  const [layout, setLayout] = useState(params.get('layout') || 'list')
  const [q, setQ] = useState('')
  const [dups, setDups] = useState(false)
  const [unreadOnly, setUnreadOnly] = useState(params.get('unread') === '1')
  const [list, setList] = useState(null)
  const [error, setError] = useState(null)
  const [sel, setSel] = useState(new Set())
  const [adding, setAdding] = useState(params.get('new') === '1')
  const [moving, setMoving] = useState(null)
  const [emailing, setEmailing] = useState(false)
  const [prefs, setPrefs] = useState(null)
  const [colPicker, setColPicker] = useState(false)
  const nav = useNavigate()
  const isRec = can('candidates.edit')

  const customCols = Object.fromEntries((meta.custom_fields || []).filter(f => f.show_in_list).map(f => [`f:${f.key}`, {
    label: f.label, cell: c => { const v = (c.fields || {})[f.key]; return f.kind === 'checkbox' ? (v ? 'Yes' : '') : v == null ? '' : String(v) } }]))
  const ALLCOLS = { ...BASE_COLS, ...customCols }
  const cols = (prefs?.candidate_columns || DEFAULT_COLS).filter(k => ALLCOLS[k])
  const views = prefs?.candidate_views || []

  useEffect(() => { get('/api/me/prefs').then(setPrefs) }, [])
  const load = () => {
    const p = new URLSearchParams()
    if (dept) p.set('department_id', dept)
    if (dups) p.set('duplicates_only', 'true')
    if (agingF) p.set('aging', agingF)
    if (scoped && mine) p.set('mine', 'true')
    if (unreadOnly) p.set('unread_only', 'true')
    get('/api/candidates?' + p).then(d => { setList(d); setError(null) }, setError)
  }
  useEffect(load, [dept, dups, agingF, mine, unreadOnly]) // eslint-disable-line
  useEffect(() => setSel(new Set()), [stage, dept, agingF])

  const dq = useDeferredValue(q)  // typing stays instant; the list catches up a moment later
  const searched = useMemo(() => {
    if (!list) return []
    const t = dq.trim().toLowerCase()
    return t ? list.filter(c => [c.first_name, c.last_name, c.email, c.phone, c.location, c.area_fit, c.practice].join(' ').toLowerCase().includes(t)) : list
  }, [list, dq])
  const filtered = stage ? searched.filter(c => String(c.stage_id) === stage) : searched
  const counts = {}
  searched.forEach(c => { counts[c.stage_id] = (counts[c.stage_id] || 0) + 1 })

  const setFilter = (k, v) => { const p = new URLSearchParams(params); v ? p.set(k, v) : p.delete(k); p.delete('new'); setParams(p) }
  const toggle = id => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const selectable = filtered.filter(c => c.access !== 'summary')
  const allOn = selectable.length > 0 && selectable.every(c => sel.has(c.id))
  const savePrefs = async patch => { const p = await put('/api/me/prefs', patch); setPrefs(p) }
  const saveView = async () => {
    const name = window.prompt('Name this view (for example "HCM over 30 days")')
    if (!name) return
    const v = { name, stage, dept, aging: agingF, q, layout, columns: cols }
    await savePrefs({ candidate_views: [...views.filter(x => x.name !== name), v] })
    toast('View saved')
  }
  const applyView = v => {
    const p = new URLSearchParams()
    if (v.stage) p.set('stage', v.stage); if (v.dept) p.set('dept', v.dept); if (v.aging) p.set('aging', v.aging)
    setParams(p); setQ(v.q || ''); setLayout(v.layout || 'list')
    if (v.columns) savePrefs({ candidate_columns: v.columns })
  }

  return (
    <div className="col">
      <div className="page-head">
        <div><h1>Candidates</h1><div className="muted">{list ? `${filtered.length} shown` : ''}{scoped && !mine ? ' · candidates in other departments are read-only' : ''}</div></div>
        <div className="row">
          {scoped && <div className="seg">
            <button className={mine ? 'on' : ''} onClick={() => { setMine(true); setFilter('all', '') }}>{me.associate ? 'Mine' : 'My departments'}</button>
            <button className={!mine ? 'on' : ''} onClick={() => { setMine(false); setFilter('all', '1') }}>Everyone</button></div>}
          {views.length > 0 && <select style={{ width: 200 }} value="" onChange={e => { const v = views.find(x => x.name === e.target.value); if (v) applyView(v) }}>
            <option value="">Saved views…</option>{views.map(v => <option key={v.name}>{v.name}</option>)}</select>}
          <button onClick={saveView}><Icon name="star" size={16} />Save view</button>
          <div className="seg"><button className={layout === 'list' ? 'on' : ''} onClick={() => setLayout('list')}><Icon name="list" size={16} /></button>
            <button className={layout === 'board' ? 'on' : ''} onClick={() => setLayout('board')}><Icon name="board" size={16} /></button></div>
          {isRec && <button className="primary" onClick={() => setAdding(true)}><Icon name="plus" size={16} />Add candidate</button>}
        </div>
      </div>

      {layout === 'list' && <div className="chipbar">
        <button className={!stage ? 'on' : ''} onClick={() => setFilter('stage', '')}>All<span className="c">{searched.length}</span></button>
        {meta.stages.filter(s => s.active).map(s => <button key={s.id} className={String(s.id) === stage ? 'on' : ''} onClick={() => setFilter('stage', s.id)}>{s.name}<span className="c">{counts[s.id] || 0}</span></button>)}
      </div>}

      <div className="row">
        <input style={{ maxWidth: 300 }} placeholder="Filter by name, email, location…" value={q} onChange={e => setQ(e.target.value)} />
        <select style={{ maxWidth: 190 }} value={dept} onChange={e => setFilter('dept', e.target.value)}>
          <option value="">All departments</option>{meta.departments.filter(d => !scoped || !mine || me.scope_ids.includes(d.id)).map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <select style={{ maxWidth: 230 }} value={agingF} onChange={e => setFilter('aging', e.target.value)}>
          <option value="">Any contact age</option>
          <option value="over">No contact {meta.settings.aging_alert_days}+ days</option>
          <option value="due">Due for automatic rejection</option>
        </select>
        <label className="check"><input type="checkbox" checked={dups} onChange={e => setDups(e.target.checked)} /> Duplicates only</label>
        <label className="check"><input type="checkbox" checked={unreadOnly} onChange={e => setUnreadOnly(e.target.checked)} /> New replies only</label>
        <div style={{ flex: 1 }} />
        {layout === 'list' && <button className="sm" onClick={() => setColPicker(true)}><Icon name="columns" size={15} />Columns</button>}
        {isRec && sel.size > 0 && <>
          <span className="muted">{sel.size} selected</span>
          <button onClick={() => setMoving({})}>Move / assign department</button>
          {can('emails.send') && <button onClick={() => setEmailing(true)}>Send email</button>}
        </>}
      </div>

      <ErrorBox error={error} />
      {!list ? <Loading /> : layout === 'board' ? <Board list={searched} onMove={(id, st) => setMoving({ ids: [id], stage: st })} canMove={isRec} /> : (
        <div className="card tight"><div className="table-wrap">
          <table>
            <thead><tr>
              {isRec && <th style={{ width: 30 }}><input type="checkbox" checked={allOn} onChange={() => setSel(allOn ? new Set() : new Set(selectable.map(c => c.id)))} /></th>}
              <th>Name</th>{cols.map(k => <th key={k}>{ALLCOLS[k].label}</th>)}
            </tr></thead>
            <tbody>
              {filtered.map(c => {
                const st = c.aging?.status
                const rowCls = st === 'alert' ? ' aging-alert' : (st === 'due' || st === 'grace') ? ' aging-due' : ''
                return (
                  <tr key={c.id} className={'click' + (sel.has(c.id) ? ' sel' : rowCls)} onClick={() => nav(`/candidates/${c.id}`)}>
                    {isRec && <td onClick={e => e.stopPropagation()}>{c.access !== 'summary' && <input type="checkbox" checked={sel.has(c.id)} onChange={() => toggle(c.id)} />}</td>}
                    <td><b>{fullName(c)}</b>{c.duplicate && <span className="badge bad" style={{ marginLeft: 6 }}>Duplicate</span>}
                      {c.transfer && <span className="badge info" style={{ marginLeft: 6 }} title={c.transfer.note}>Transfer to {c.transfer.to} pending</span>}
                      {c.unread_replies > 0 && <span className="badge brand" style={{ marginLeft: 6 }} title="Replies you haven't opened"><Icon name="reply" size={11} /> {c.unread_replies} new</span>}
                      <div className="small muted">{c.access === 'summary' ? <Locked text="Read-only" /> : c.location}</div></td>
                    {cols.map(k => <td key={k}>{ALLCOLS[k].cell(c)}</td>)}
                  </tr>
                )
              })}
              {!filtered.length && <tr><td colSpan={cols.length + 2} className="empty">No candidates here.</td></tr>}
            </tbody>
          </table>
        </div></div>
      )}

      {adding && <AddCandidate onClose={() => { setAdding(false); setFilter('new', '') }} onSaved={(id, dup) => {
        setAdding(false); toast(dup ? 'Saved. Heads up: this email already exists on another record.' : 'Candidate added', dup ? 'bad' : ''); nav(`/candidates/${id}`)
      }} />}
      {moving && <MoveModal ids={moving.ids || [...sel]} initialStage={moving.stage}
        currentDept={(moving.ids || [...sel]).every(id => !list?.find(c => c.id === id)?.department_id) ? null : undefined} onClose={() => setMoving(null)} onDone={msg => { setMoving(null); setSel(new Set()); toast(msg); load() }} />}
      {emailing && <BulkEmail ids={[...sel]} onClose={() => setEmailing(false)} onDone={msg => { setEmailing(false); setSel(new Set()); toast(msg); load() }} />}
      {colPicker && <ColumnPicker all={ALLCOLS} value={cols} onClose={() => setColPicker(false)} onSave={v => { savePrefs({ candidate_columns: v }); setColPicker(false) }} />}
    </div>
  )
}

function ColumnPicker({ all, value, onClose, onSave }) {
  const [list, setList] = useState(value)
  const move = (k, d) => setList(l => { const i = l.indexOf(k); const n = [...l]; n.splice(i, 1); n.splice(Math.max(0, Math.min(n.length, i + d)), 0, k); return n })
  return (
    <Modal title="Choose columns" onClose={onClose} footer={<><button onClick={() => setList(DEFAULT_COLS)}>Reset</button><button onClick={onClose}>Cancel</button><button className="primary" onClick={() => onSave(list)}>Save</button></>}>
      <div className="small muted">Only changes your own list. Custom fields an admin adds in Settings show up here too.</div>
      {[...list, ...Object.keys(all).filter(k => !list.includes(k))].map(k => (
        <div key={k} className="row between" style={{ borderBottom: '1px solid var(--line)', paddingBottom: 6 }}>
          <label className="check"><input type="checkbox" checked={list.includes(k)} onChange={e => setList(l => e.target.checked ? [...l, k] : l.filter(x => x !== k))} />{all[k].label}</label>
          {list.includes(k) && <div className="row"><button className="sm" onClick={() => move(k, -1)}>↑</button><button className="sm" onClick={() => move(k, 1)}>↓</button></div>}
        </div>
      ))}
    </Modal>
  )
}

function Board({ list, onMove, canMove }) {
  const { meta } = useApp()
  const nav = useNavigate()
  const [over, setOver] = useState(null)
  const stages = meta.stages.filter(s => s.active)
  return (
    <div className="board">
      {stages.map(s => {
        const items = list.filter(c => c.stage_id === s.id)
        return (
          <div key={s.id} className={'lane' + (over === s.id ? ' over' : '')}
            onDragOver={e => { if (canMove) { e.preventDefault(); setOver(s.id) } }} onDragLeave={() => setOver(null)}
            onDrop={e => { e.preventDefault(); setOver(null); const id = +e.dataTransfer.getData('text/plain'); const c = list.find(x => x.id === id); if (c && c.stage_id !== s.id) onMove(id, s.id) }}>
            <div className="lane-head"><span><span className="dot" style={{ background: s.color, marginRight: 8 }} />{s.name}</span><span className="badge">{items.length}</span></div>
            {items.slice(0, 150).map(c => {
              const st = c.aging?.status
              return (
                <div key={c.id} className={'kcard' + (st === 'alert' ? ' k-alert' : (st === 'due' || st === 'grace') ? ' k-due' : '') + (c.access === 'summary' ? ' k-ro' : '')} draggable={canMove && c.access !== 'summary'}
                  onDragStart={e => e.dataTransfer.setData('text/plain', String(c.id))} onClick={() => nav(`/candidates/${c.id}`)}>
                  <div className="row between"><b>{fullName(c)}</b>{c.aging && <AgingCell a={c.aging} />}</div>
                  <div className="small muted" style={{ marginTop: 4 }}>{c.access === 'summary' ? <Locked /> : c.email}{c.unread_replies > 0 && <span className="unread-dot" title="New reply" />}</div>
                  <div className="row" style={{ marginTop: 6 }}>{c.department_id && <DeptBadge id={c.department_id} />}{c.next_interview && <span className="small muted">{fmtDate(c.next_interview)}</span>}</div>
                </div>
              )
            })}
            {items.length > 150 && <div className="small muted">+{items.length - 150} more. Use the list view to see them all.</div>}
          </div>
        )
      })}
    </div>
  )
}

function AddCandidate({ onClose, onSaved }) {
  const { meta, me } = useApp()
  const stageOk = s => s.active && (!me.associate || !(s.kind === 'open' && s.requires_department))
  const [f, setF] = useState({ first_name: '', last_name: '', email: '', phone: '', resume_link: '', location: '', source: '',
    stage_id: meta.stages[0]?.id, department_id: null })
  const [err, setErr] = useState('')
  const set = (k, v) => setF(x => ({ ...x, [k]: v }))
  const save = async () => {
    try {
      const r = await post('/api/candidates', { ...f, department_id: f.department_id || null })
      onSaved(r.candidate.id, r.duplicate_of > 0)
    } catch (e) { setErr(e.message) }
  }
  return (
    <Modal title="Add candidate" onClose={onClose} footer={<><button onClick={onClose}>Cancel</button><button className="primary" onClick={save}>Save</button></>}>
      <div className="grid2">
        <Field label="First name"><input autoFocus value={f.first_name} onChange={e => set('first_name', e.target.value)} /></Field>
        <Field label="Last name"><input value={f.last_name} onChange={e => set('last_name', e.target.value)} /></Field>
        <Field label="Email"><input value={f.email} onChange={e => set('email', e.target.value)} /></Field>
        <Field label="Phone"><input value={f.phone} onChange={e => set('phone', e.target.value)} /></Field>
        <Field label="Resume link" className="span2"><input value={f.resume_link} onChange={e => set('resume_link', e.target.value)} /></Field>
        <Field label="Location"><input value={f.location} onChange={e => set('location', e.target.value)} /></Field>
        <Field label="Source"><input value={f.source} placeholder="Website, Referral…" onChange={e => set('source', e.target.value)} /></Field>
        <Field label="Stage"><select value={f.stage_id || ''} onChange={e => set('stage_id', +e.target.value)}>{meta.stages.filter(stageOk).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
        <Field label="Department"><select value={f.department_id || ''} onChange={e => set('department_id', e.target.value ? +e.target.value : null)}><option value="">None yet</option>{meta.departments.filter(d => d.active).map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></Field>
      </div>
      {me.associate && <div className="small muted">Picking a department hands the candidate over to that department's recruiters, and they're told about it.</div>}
      {err && <div className="alert bad">{err}</div>}
    </Modal>
  )
}

export function MoveModal({ ids, onClose, onDone, initialStage, currentDept }) {
  const { meta, me, can } = useApp()
  const [note, setNote] = useState('')
  const [stageId, setStageId] = useState(initialStage || '')
  const [deptId, setDeptId] = useState('')
  const [sendEmail, setSendEmail] = useState(true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const stage = meta.stages.find(s => String(s.id) === String(stageId))
  const tpl = stage?.entry_template_id ? meta.email_templates.find(t => t.id === stage.entry_template_id) : null
  const stageOk = s => s.active && (s.kind !== 'hired' || can('candidates.hire')) && (!me.associate || !(s.kind === 'open' && s.requires_department))
  const dept = meta.departments.find(d => String(d.id) === String(deptId))
  const outside = !!dept && me.scope_ids != null && !me.scope_ids.includes(dept.id) && !me.associate && currentDept !== null
  const go = async () => {
    setBusy(true); setErr('')
    try {
      const r = await post('/api/candidates/bulk/move', { ids, stage_id: stageId ? +stageId : null, department_id: deptId === '' ? null : +deptId, send_email: sendEmail, note })
      const errs = r.results.filter(x => x.error)
      const mailed = r.results.filter(x => x.emailed).length
      const sent = r.results.filter(x => x.transferred).length
      const moved = r.results.length - errs.length - sent
      onDone([moved && `${moved} updated`, mailed && `${mailed} email(s) queued`, sent && `${sent} transfer request(s) sent to ${dept?.name}`].filter(Boolean).join(', ')
        + (errs.length ? `. Skipped: ${errs.map(e => `${e.name} (${e.error})`).join('; ')}` : ''))
    } catch (e) { setErr(e.message); setBusy(false) }
  }
  return (
    <Modal title={`Move ${ids.length} candidate${ids.length > 1 ? 's' : ''}`} onClose={onClose} footer={<>
      <button onClick={onClose}>Cancel</button>
      <button className={stage && stage.kind === 'rejected' ? 'danger solid' : 'primary'} disabled={busy || (!stageId && deptId === '') || (outside && !note.trim())} onClick={go}>
        {outside ? 'Send transfer request' : tpl && sendEmail ? `Move and send ${ids.length} email${ids.length > 1 ? 's' : ''}` : 'Move'}
      </button></>}>
      <div className="grid2">
        <Field label="Stage"><select value={stageId} onChange={e => setStageId(e.target.value)}><option value="">Keep current stage</option>{meta.stages.filter(stageOk).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
        <Field label="Department"><select value={deptId} onChange={e => setDeptId(e.target.value)}><option value="">Keep current department</option>{meta.departments.filter(d => d.active).map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></Field>
      </div>
      {outside && <div className="col" style={{ gap: 6 }}>
        <div className="alert">You don't work in {dept.name}, so this sends them a transfer request instead of moving the candidate. {dept.name}'s recruiters are notified and can accept it, or decline it, which rejects the candidate. Candidates without a department yet are simply handed over.</div>
        <Field label={`Note for ${dept.name} (required)`}><textarea placeholder="Why this candidate fits their team" value={note} onChange={e => setNote(e.target.value)} /></Field>
      </div>}
      {me.associate && <div className="small muted">Associates work the AI stages and Screening. To move someone further, pick their department; that department's recruiters take it from there.</div>}
      {stage?.requires_department && <div className="alert">Candidates need a department for this stage. Pick one above if they don't have it yet.</div>}
      {tpl && <label className="check"><input type="checkbox" checked={sendEmail} onChange={e => setSendEmail(e.target.checked)} /> Send the “{tpl.name}” email to each candidate</label>}
      {err && <div className="alert bad">{err}</div>}
    </Modal>
  )
}

function BulkEmail({ ids, onClose, onDone }) {
  const { meta } = useApp()
  const tpls = meta.email_templates.filter(t => t.active && t.show_as_action)
  const [tid, setTid] = useState(tpls[0]?.id || '')
  const [busy, setBusy] = useState(false)
  const t = tpls.find(x => x.id === +tid)
  const mv = t?.moves_to_stage_id ? meta.stages.find(s => s.id === t.moves_to_stage_id) : null
  const go = async () => {
    setBusy(true)
    const r = await post('/api/candidates/bulk/email', { ids, template_id: +tid })
    const bad = r.results.filter(x => !x.ok)
    onDone(`${r.results.length - bad.length} email(s) queued${bad.length ? `. Skipped: ${bad.map(b => b.name).join(', ')} (no email)` : ''}`)
  }
  return (
    <Modal title={`Email ${ids.length} candidate${ids.length > 1 ? 's' : ''}`} onClose={onClose} footer={<><button onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !tid} onClick={go}>Send {ids.length}</button></>}>
      <Field label="Template"><select value={tid} onChange={e => setTid(e.target.value)}>{tpls.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
      {mv && <div className="alert">Sending this moves each candidate to <b>{mv.name}</b>.</div>}
      <div className="small muted">Each email is personalised and sent from your own Outlook. Open a single candidate if you want to edit the text first.</div>
    </Modal>
  )
}
