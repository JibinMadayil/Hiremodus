import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { get, post, put, patch, del, fmtDate, fmtUtc, fullName, auth } from '../api'
import { useApp, Modal, Field, StageBadge, DeptBadge, JobBadge, TestBadge, Confirm, Loading, ErrorBox, EmailList } from '../ui'
import { MoveModal, AgingCell, Locked } from './Candidates'
import Icon from '../icons'
import { ScheduleModal, RescheduleModal } from './Schedule'

const PROFILE = [
  ['first_name', 'First name'], ['last_name', 'Last name'], ['email', 'Email'], ['phone', 'Phone'],
  ['location', 'Location'], ['source', 'Source'], ['resume_link', 'Resume link', 'span2'],
  ['ai_interview_link', 'AI interview link (Ribbon)', 'span2'], ['ribbon_rating', 'Ribbon rating'], ['oracle_experience', 'Experienced in Oracle?'],
  ['screening_result', 'Resume screening result', 'span2', 'ta'], ['screening_comments', 'Screening comments / education', 'span2', 'ta'],
  ['area_fit', 'Area fit'], ['practice', 'Practice being considered'],
  ['round1_info', 'Round 1 (notes)'], ['round2_info', 'Round 2 (notes)'],
  ['test_score', 'Test score'], ['interviewer', 'Interviewer'],
  ['interviewer_comment', 'Interviewer comment', 'span2', 'ta'], ['final_decision', 'Final decision'], ['date_added', 'Date added', '', 'date'],
  ['notes', 'Notes', 'span2', 'ta'],
]

export default function CandidateDetail() {
  const { id } = useParams()
  const { meta, me, toast, can } = useApp()
  const nav = useNavigate()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [form, setForm] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [modal, setModal] = useState(null)
  const isRec = can('candidates.edit')

  const load = () => get(`/api/candidates/${id}`).then(d => { setData(d); setForm(d.candidate); setDirty(false) }, setError)
  useEffect(() => { load() }, [id]) // eslint-disable-line
  useEffect(() => { // refresh while anything is still waiting on Outlook
    if (!data) return
    const waiting = data.jobs.some(j => j.status === 'queued' || j.status === 'claimed')
    if (!waiting) return
    const t = setTimeout(load, 4000)
    return () => clearTimeout(t)
  }, [data]) // eslint-disable-line

  if (error) return <ErrorBox error={error} />
  if (!data) return <Loading />
  if (data.access === 'summary') return <SummaryView c={data.candidate} />
  const c = data.candidate
  const set = (k, v) => { setForm(f => ({ ...f, [k]: v })); setDirty(true) }
  const save = async () => {
    try {
      const body = {}
      PROFILE.forEach(([k]) => { if (form[k] !== c[k]) body[k] = form[k] || (k === 'date_added' ? null : '') })
      if (isRec) body.module_id = form.module_id || null
      if (isRec && JSON.stringify(form.fields || {}) !== JSON.stringify(c.fields || {})) body.fields = form.fields || {}
      const r = await patch(`/api/candidates/${id}`, body)
      toast(r.messages?.length ? r.messages.join('. ') : 'Saved')
      load()
    } catch (e) { toast(e.message, 'bad') }
  }
  const stageOf = kind => meta.stages.find(s => s.kind === kind && s.active)
  const actions = meta.email_templates.filter(t => t.active && t.show_as_action && (!t.department_ids.length || t.department_ids.includes(c.department_id)))
  const done = msg => { setModal(null); if (msg) toast(msg); load() }

  return (
    <div className="col">
      <div className="page-head">
        <div>
          <div className="small"><Link to="/candidates">← Candidates</Link></div>
          <h1>{fullName(c)}</h1>
          <div className="row"><StageBadge id={c.stage_id} /><DeptBadge id={c.department_id} />{c.email && <span className="muted">{c.email}</span>}</div>
        </div>
        {isRec && <div className="row">
          {can('interviews.schedule') && <button className="primary" onClick={() => setModal({ kind: 'schedule' })} disabled={!c.email}><Icon name="calendar" size={16} />Schedule interview</button>}
          {can('emails.send') && <button onClick={() => setModal({ kind: 'email' })} disabled={!c.email}><Icon name="send" size={16} />Send email</button>}
          {can('tests.assign') && <button onClick={() => setModal({ kind: 'test' })}>Assign test</button>}
          <button onClick={() => setModal({ kind: 'move' })}>Move</button>
          {c.department_id && !me.associate && <button onClick={() => setModal({ kind: 'transfer' })}><Icon name="transfer" size={16} />Transfer</button>}
          {stageOf('hired') && can('candidates.hire') && <button onClick={() => setModal({ kind: 'move', stage: stageOf('hired').id })}>Hire</button>}
          {stageOf('withdrawn') && <button onClick={() => setModal({ kind: 'move', stage: stageOf('withdrawn').id })}>Withdrawn</button>}
          {stageOf('rejected') && <button className="danger" onClick={() => setModal({ kind: 'move', stage: stageOf('rejected').id })}>Reject</button>}
        </div>}
      </div>

      {c.anonymized_at && <div className="alert">This candidate's personal details were removed on {fmtUtc(c.anonymized_at)}, under the rule for old rejected and withdrawn candidates. Only stage, department and dates are kept.</div>}
      {!c.anonymized_at && can('users.manage') && ['rejected', 'withdrawn'].includes(meta.stages.find(s => s.id === c.stage_id)?.kind) && <KeepCard c={c} onDone={done} />}
      {c.transfer && <TransferBanner t={c.transfer} onDone={done} />}
      {data.same_email.length > 0 && <div className="alert bad">Duplicate: this email is also on {data.same_email.map((o, i) => <span key={o.id}>{i > 0 && ', '}<Link to={`/candidates/${o.id}`}>{o.name}</Link> (<StageBadge id={o.stage_id} />)</span>)}</div>}
      {c.aging && <AgingCard c={c} canEdit={isRec} onChange={done} />}
      {actions.length > 0 && isRec && can('emails.send') && <div className="row"><span className="muted small">Quick emails:</span>{actions.map(t => <button key={t.id} className="sm" disabled={!c.email} onClick={() => setModal({ kind: 'email', template: t.id })}>{t.name}</button>)}</div>}

      <div className="grid2" style={{ alignItems: 'start' }}>
        <div className="card col">
          <div className="row between"><h2 style={{ margin: 0 }}>Profile</h2><button className="primary sm" disabled={!dirty} onClick={save}>Save changes</button></div>
          <div className="grid2">
            {PROFILE.map(([k, label, cls, type]) => {
              const ro = (k === 'date_added' && !can('candidates.edit_date_added')) || (!isRec && !['notes', 'interviewer_comment', 'test_score', 'interviewer'].includes(k))
              return (
                <Field key={k} label={label} className={cls}>
                  {type === 'ta' ? <textarea style={{ minHeight: 60 }} readOnly={ro} value={form[k] || ''} onChange={e => set(k, e.target.value)} />
                    : <input type={type === 'date' ? 'date' : 'text'} readOnly={ro} value={form[k] || ''} onChange={e => set(k, e.target.value)} />}
                  {k === 'resume_link' && c.resume_link?.startsWith('http') && <a href={c.resume_link} target="_blank" rel="noreferrer" className="small">Open resume</a>}
                </Field>
              )
            })}
            <Field label="Training module" className="span2">
              <select disabled={!isRec} value={form.module_id || ''} onChange={e => set('module_id', e.target.value ? +e.target.value : null)}>
                <option value="">None</option>{meta.modules.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            </Field>
          </div>
          {Object.keys(c.custom || {}).length > 0 && <div><h3>Other columns from Excel</h3><div className="kv">{Object.entries(c.custom).flatMap(([k, v]) => [<div key={k}>{k}</div>, <div key={k + '_v'}>{String(v)}</div>])}</div></div>}
          {(meta.custom_fields || []).length > 0 && <div><h3>More details</h3><div className="grid2">
            {meta.custom_fields.map(f => <Field key={f.key} label={f.label}><CustomInput f={f} disabled={!isRec} value={(form.fields || {})[f.key]} onChange={v => set('fields', { ...(form.fields || {}), [f.key]: v })} /></Field>)}
          </div></div>}
          {can('candidates.delete') && <div><button className="danger sm" onClick={() => setModal({ kind: 'delete' })}>Delete candidate</button></div>}
        </div>

        <div className="col">
          <div className="card">
            <h2>Interviews</h2>
            {!data.interviews.length && <div className="muted">None yet.</div>}
            {data.interviews.map(iv => (
              <div key={iv.id} style={{ borderBottom: '1px solid var(--line)', padding: '10px 0' }}>
                <div className="row between"><b>{fmtDate(iv.start)}</b>
                  <span className={'badge ' + ({ scheduled: 'ok', sending: 'warn', failed: 'bad', cancelled: '' }[iv.status])}>{{ scheduled: 'In Outlook', sending: 'Waiting for Outlook', failed: 'Failed', cancelled: 'Cancelled' }[iv.status]}</span></div>
                <div className="small">{iv.title}</div>
                <div className="small muted">{iv.location}</div>
                <details className="small"><summary className="muted">Attendees and invite text</summary>
                  <div style={{ marginTop: 6 }}>Required: <EmailList value={iv.required} /></div>
                  <div style={{ marginTop: 6 }}>Optional: <EmailList value={iv.optional} /></div>
                  {iv.body && <div className="pre card" style={{ marginTop: 8 }}>{iv.body}</div>}
                </details>
                <InterviewFeedback iv={iv} items={(data.feedback || []).filter(f => f.interview_id === iv.id)} canEdit={isRec} onSaved={done} />
                {can('interviews.schedule') && iv.status !== 'cancelled' && new Date(iv.end) > new Date() && <div className="row" style={{ marginTop: 6 }}>
                  <button className="sm" onClick={() => setModal({ kind: 'reschedule', iv })}>Reschedule</button>
                  <button className="sm danger" onClick={() => setModal({ kind: 'cancel', iv })}>Cancel</button>
                </div>}
              </div>
            ))}
          </div>

          <div className="card">
            <h2>Tests</h2>
            {!data.assignments.length && <div className="muted">No tests assigned.</div>}
            {data.assignments.map(a => (
              <div key={a.id} style={{ borderBottom: '1px solid var(--line)', padding: '10px 0' }}>
                <div className="row between"><b>{a.test_name}</b><TestBadge status={a.status} /></div>
                <div className="small muted">Login: <span className="mono">{a.username}</span>{a.started_at && ` · started ${fmtUtc(a.started_at)}`}</div>
                {a.auto_score != null && <div className="small">Score: {(a.auto_score || 0) + (a.manual_score || 0)} / {a.total_points}</div>}
                <div className="row" style={{ marginTop: 6 }}>
                  {can('tests.start_code') && ['assigned', 'in_progress'].includes(a.status) && <button className="sm primary" onClick={() => setModal({ kind: 'code', a })}>Give start code</button>}
                  {(can('tests.results') || can('tests.papers')) && ['submitted', 'graded', 'in_progress'].includes(a.status) && <Link className="btn sm" to={`/results/${a.id}`}>{a.status === 'in_progress' ? 'Watch' : 'View / grade'}</Link>}
                  {can('tests.assign') && ['assigned', 'revoked'].includes(a.status) && <button className="sm" onClick={() => setModal({ kind: 'resetpw', a })}>Resend login</button>}
                  {can('tests.assign') && a.status === 'assigned' && <button className="sm danger" onClick={() => post(`/api/assignments/${a.id}/revoke`).then(() => done('Test login revoked'))}>Revoke</button>}
                </div>
              </div>
            ))}
          </div>

          <Conversation data={data} c={c} canReply={isRec && can('emails.send')} onChange={done} setModal={setModal} />

          {data.transfers?.length > 0 && <div className="card">
            <h2>Transfers</h2>
            <div className="timeline">{data.transfers.map(t => (
              <div key={t.id} className="item">
                <div className="row between"><span>{t.from || 'No department'} → <b>{t.to}</b></span>
                  <span className={'badge ' + ({ pending: 'warn', accepted: 'ok', declined: 'bad', cancelled: '' }[t.status])}>{{ pending: 'Waiting', accepted: 'Accepted', declined: 'Declined', cancelled: 'Cancelled' }[t.status]}</span></div>
                <div className="small">“{t.note}” <span className="muted">· {t.requested_by_name} · {fmtUtc(t.requested_at)}</span></div>
                {t.decided_at && t.status !== 'pending' && <div className="small muted">{t.status === 'cancelled' ? 'Cancelled' : t.status === 'accepted' ? 'Accepted' : 'Declined'} by {t.decided_by_name} · {fmtUtc(t.decided_at)}{t.decision_note ? `: “${t.decision_note}”` : ''}</div>}
              </div>))}</div>
          </div>}

          <div className="card">
            <h2>Activity</h2>
            <div className="timeline">{data.log.map(l => (
              <div key={l.id} className="item"><div>{l.action.replaceAll('_', ' ')}{l.detail && <span className="muted">: {l.detail}</span>}</div><div className="small muted">{l.user_name} · {fmtUtc(l.at)}</div></div>
            ))}</div>
          </div>
        </div>
      </div>

      {modal?.kind === 'move' && <MoveModal ids={[c.id]} initialStage={modal.stage} currentDept={c.department_id || null} onClose={() => setModal(null)} onDone={done} />}
      {modal?.kind === 'transfer' && <TransferModal c={c} onClose={() => setModal(null)} onDone={done} />}
      {modal?.kind === 'schedule' && <ScheduleModal candidate={c} onClose={() => setModal(null)} onDone={() => done()} />}
      {modal?.kind === 'reschedule' && <RescheduleModal interview={modal.iv} candidate={c} onClose={() => setModal(null)} onDone={() => done()} />}
      {modal?.kind === 'cancel' && <Confirm title="Cancel interview" danger confirmLabel="Cancel interview" message={`This cancels the Outlook meeting for all attendees and revokes any unused test login.\n\n${modal.iv.title}`}
        onClose={() => setModal(null)} onConfirm={() => post(`/api/interviews/${modal.iv.id}/cancel`).then(() => done('Cancellation sent to Outlook'), e => toast(e.message, 'bad'))} />}
      {modal?.kind === 'email' && <EmailModal candidate={c} initial={modal.template} onClose={() => setModal(null)} onDone={done} />}
      {modal?.kind === 'viewreply' && <ViewReply eid={modal.eid} c={c} canReply={isRec && can('emails.send')} onClose={() => done()} onReply={eid => setModal({ kind: 'reply', eid })} />}
      {modal?.kind === 'reply' && <ReplyModal eid={modal.eid} c={c} onClose={() => setModal(null)} onDone={done} />}
      {modal?.kind === 'test' && <AssignTest candidate={c} onClose={() => setModal(null)} onDone={done} />}
      {modal?.kind === 'code' && <StartCode a={modal.a} onClose={() => { setModal(null); load() }} />}
      {modal?.kind === 'resetpw' && <Confirm title="Send a new test login" message="This creates a new password for the candidate's test login and emails it to them. The old password stops working." confirmLabel="Send new login"
        onClose={() => setModal(null)} onConfirm={() => post(`/api/assignments/${modal.a.id}/reset-password`).then(() => done('New login emailed'), e => toast(e.message, 'bad'))} />}
      {modal?.kind === 'delete' && <Confirm title="Delete candidate" danger confirmLabel="Delete" message="This permanently removes the candidate, their interviews and test results from HireModus. Outlook meetings are not touched."
        onClose={() => setModal(null)} onConfirm={() => del(`/api/candidates/${c.id}`).then(() => { toast('Deleted'); nav('/candidates') })} />}
    </div>
  )
}

function EmailModal({ candidate, initial, onClose, onDone }) {
  const { meta } = useApp()
  const tpls = meta.email_templates.filter(t => t.active && !['test_access', 'reschedule'].includes(t.key))
  const [tid, setTid] = useState(initial || tpls.find(t => t.show_as_action)?.id || tpls[0]?.id)
  const [mail, setMail] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    setMail(null)
    post(`/api/candidates/${candidate.id}/email/preview`, { template_id: +tid }).then(setMail, e => setErr(e.message))
  }, [tid, candidate.id])
  const send = async () => {
    try {
      await post(`/api/candidates/${candidate.id}/email/send`, { template_id: +tid, subject: mail.subject, body: mail.body, cc: mail.cc })
      onDone('Email queued in your Outlook')
    } catch (e) { setErr(e.message) }
  }
  return (
    <Modal wide title="Send email" onClose={onClose} footer={<><button onClick={onClose}>Cancel</button><button className="primary" disabled={!mail} onClick={send}>Send</button></>}>
      <Field label="Template"><select value={tid} onChange={e => setTid(e.target.value)}>{tpls.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
      {mail && <>
        <div className="grid2"><Field label="To"><input readOnly value={mail.to} /></Field><Field label="CC"><input value={mail.cc} onChange={e => setMail({ ...mail, cc: e.target.value })} /></Field></div>
        <Field label="Subject"><input value={mail.subject} onChange={e => setMail({ ...mail, subject: e.target.value })} /></Field>
        <Field label="Message"><textarea className="tall" value={mail.body} onChange={e => setMail({ ...mail, body: e.target.value })} /></Field>
        {mail.moves_to && <div className="alert">Sending moves the candidate to <b>{mail.moves_to}</b>.</div>}
        {mail.notify_it && <div className="alert">IT also gets an access request for the SharePoint links in this email.</div>}
      </>}
      {err && <div className="alert bad">{err}</div>}
    </Modal>
  )
}

function AssignTest({ candidate, onClose, onDone }) {
  const { meta } = useApp()
  const tests = meta.tests.filter(t => t.active)
  const [tid, setTid] = useState(tests.find(t => t.department_id === candidate.department_id)?.id || tests[0]?.id)
  const [send, setSend] = useState(true)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const go = async () => {
    try { setRes(await post(`/api/candidates/${candidate.id}/assign-test`, { test_id: +tid, send_email: send })) } catch (e) { setErr(e.message) }
  }
  if (res) return (
    <Modal title="Test assigned" onClose={() => onDone()} footer={<button className="primary" onClick={() => onDone()}>Done</button>}>
      <div>{send ? 'The login was emailed to the candidate.' : 'Give these details to the candidate:'}</div>
      <div className="kv"><div>Username</div><div className="mono">{res.assignment.username}</div><div>Password</div><div className="mono">{res.password}</div></div>
      <div className="small muted">The password is shown only once. Use “Resend login” later if it's lost.</div>
    </Modal>
  )
  return (
    <Modal title="Assign a test" onClose={onClose} footer={<><button onClick={onClose}>Cancel</button><button className="primary" onClick={go}>Assign</button></>}>
      <div className="muted small">Tests attached to an interview template are assigned automatically when the invite goes out. Use this for a standalone test.</div>
      <Field label="Test"><select value={tid} onChange={e => setTid(e.target.value)}>{tests.map(t => <option key={t.id} value={t.id}>{t.name} ({t.duration_min} min)</option>)}</select></Field>
      <label className="check"><input type="checkbox" checked={send} onChange={e => setSend(e.target.checked)} /> Email the login to the candidate</label>
      {err && <div className="alert bad">{err}</div>}
    </Modal>
  )
}

export function StartCode({ a, onClose }) {
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => { post(`/api/assignments/${a.id}/start-code`).then(setRes, e => setErr(e.message)) }, [a.id])
  return (
    <Modal title="Start code" onClose={onClose} footer={<button className="primary" onClick={onClose}>Close</button>}>
      {err && <div className="alert bad">{err}</div>}
      {res && <>
        <div className="muted">Read this to the candidate once they've signed in to the test portal. It works once and expires in {res.valid_minutes} minutes.</div>
        <div className="code-big">{res.code}</div>
        {a.status === 'in_progress' && <div className="alert warn">This test is already running. The code reopens it (for example after a browser crash) and the timer keeps counting.</div>}
      </>}
    </Modal>
  )
}


function AgingCard({ c, canEdit, onChange }) {
  const { toast, meta } = useApp()
  const a = c.aging
  const contacted = () => post(`/api/candidates/${c.id}/contacted`).then(() => onChange('Marked as contacted. The clock restarted at day 1.'), e => toast(e.message, 'bad'))
  const keep = v => post(`/api/candidates/${c.id}/aging-exempt`, { exempt: v }).then(() => onChange(v ? 'This candidate won\u2019t be auto-rejected' : 'Aging rules apply again'), e => toast(e.message, 'bad'))
  const tone = a.status === 'alert' ? 'warn' : (a.status === 'due' || a.status === 'grace') ? 'bad' : a.status === 'paused' ? 'info' : 'ok'
  const msg = {
    ok: `Day ${a.days} since last contact. Flagged at day ${a.alert_days}, rejected automatically at day ${a.reject_days}.`,
    alert: `${a.days} days without contact, so recruiters are being alerted. Automatic rejection on ${fmtDate(a.reject_on + 'T12:00', false)} unless someone contacts them.`,
    grace: `${a.days} days without contact (imported already past the limit). Automatic rejection on ${a.reject_on ? fmtDate(a.reject_on + 'T12:00', false) : ''}.`,
    due: `${a.days} days without contact. Will be rejected automatically at the next daily check.`,
    paused: `Interview booked${a.next_interview ? ' for ' + fmtDate(a.next_interview) : ''}. The clock is paused and restarts from the interview day.`,
    exempt: `Marked Keep: won't be rejected automatically (${a.days} days since last contact).`,
  }[a.status]
  return (
    <div className={'alert ' + (tone === 'ok' ? '' : tone)} style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap', background: tone === 'ok' ? 'var(--soft)' : undefined, color: tone === 'ok' ? 'var(--ink)' : undefined }}>
      <Icon name={a.status === 'paused' ? 'calendar' : a.status === 'ok' || a.status === 'exempt' ? 'clock' : 'alert'} />
      <div style={{ flex: 1, minWidth: 260 }}>{msg}<div className="small" style={{ opacity: .8 }}>Last contact {fmtDate(a.since + 'T12:00', false)}{c.last_contact_name ? ` by ${c.last_contact_name}` : ''}</div></div>
      {canEdit && <><button className="sm" onClick={contacted}><Icon name="check" size={14} />Mark as contacted</button>
        {a.status === 'exempt' ? <button className="sm" onClick={() => keep(false)}>Remove Keep</button> : <button className="sm" onClick={() => keep(true)}>Keep (don't auto-reject)</button>}</>}
    </div>
  )
}

function CustomInput({ f, value, onChange, disabled }) {
  if (f.kind === 'checkbox') return <label className="check"><input type="checkbox" disabled={disabled} checked={!!value} onChange={e => onChange(e.target.checked)} /> Yes</label>
  if (f.kind === 'select') return <select disabled={disabled} value={value || ''} onChange={e => onChange(e.target.value)}><option value="">Choose…</option>{(f.options || []).map(o => <option key={o}>{o}</option>)}</select>
  if (f.kind === 'long') return <textarea style={{ minHeight: 60 }} readOnly={disabled} value={value || ''} onChange={e => onChange(e.target.value)} />
  return <input type={f.kind === 'number' ? 'number' : f.kind === 'date' ? 'date' : 'text'} readOnly={disabled} value={value ?? ''} onChange={e => onChange(e.target.value)} />
}

/* Read-only view of a candidate in a department the user doesn't work in */
function SummaryView({ c }) {
  const { meta } = useApp()
  const dept = meta.departments.find(d => d.id === c.department_id)
  return (
    <div className="col" style={{ maxWidth: 760 }}>
      <div className="page-head"><div>
        <div className="small"><Link to="/candidates">← Candidates</Link></div>
        <h1>{fullName(c)}</h1>
        <div className="row"><StageBadge id={c.stage_id} /><DeptBadge id={c.department_id} /><Locked text="Read-only" /></div>
      </div></div>
      <div className="card col">
        <div>{fullName(c)} is with <b>{dept?.name || 'another team'}</b>. You can see where they are in the process; their details, emails and tests are only open to {dept?.name || 'that department'}.</div>
        <div className="kv">
          <div>Stage</div><div><StageBadge id={c.stage_id} /></div>
          <div>Department</div><div><DeptBadge id={c.department_id} /></div>
          <div>Days since contact</div><div><AgingCell a={c.aging} /></div>
          {c.next_interview && <><div>Next interview</div><div>{fmtDate(c.next_interview)}</div></>}
          {c.date_added && <><div>Date added</div><div>{fmtDate(c.date_added + 'T12:00', false)}</div></>}
        </div>
        {c.transfer && <div className="alert">Transfer to <b>{c.transfer.to}</b> requested by {c.transfer.requested_by_name}: “{c.transfer.note}”</div>}
      </div>
    </div>
  )
}

function TransferBanner({ t, onDone }) {
  const { me, can } = useApp()
  const [declining, setDeclining] = useState(false)
  const [busy, setBusy] = useState(false)
  const decider = can('candidates.edit') && (me.scope_ids == null || me.scope_ids.includes(t.to_department_id))
  const mine = t.requested_by === me.id
  const act = async (path, msg, body) => {
    setBusy(true)
    try { await post(`/api/candidates/transfers/${t.id}/${path}`, body); onDone(msg) } catch (e) { onDone(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="transfer-banner">
      <Icon name="transfer" size={22} />
      <div style={{ flex: 1, minWidth: 260 }}>
        <b>Transfer to {t.to} waiting{decider ? ' for you' : ''}</b>
        <div className="small">From {t.from || 'no department'} · {t.requested_by_name} · {fmtUtc(t.requested_at)}</div>
        <div style={{ marginTop: 4 }}>“{t.note}”</div>
      </div>
      {decider && <div className="row">
        <button className="danger" disabled={busy} onClick={() => setDeclining(true)}>Decline</button>
        <button className="primary" disabled={busy} onClick={() => act('accept', `Accepted into ${t.to}`)}>Accept into {t.to}</button>
      </div>}
      {!decider && (mine || can('users.manage')) && <button disabled={busy} onClick={() => act('cancel', 'Transfer cancelled')}>Cancel request</button>}
      {declining && <DeclineModal t={t} onClose={() => setDeclining(false)} onConfirm={(note, send) => act('decline', 'Declined. The candidate was moved to Rejected' + (send ? ' and the rejection email queued' : ''), { note, send_email: send })} />}
    </div>
  )
}

function DeclineModal({ t, onClose, onConfirm }) {
  const { meta } = useApp()
  const [note, setNote] = useState('')
  const [send, setSend] = useState(true)
  const rej = meta.stages.find(s => s.kind === 'rejected' && s.active)
  const tpl = rej?.entry_template_id ? meta.email_templates.find(x => x.id === rej.entry_template_id) : null
  return (
    <Modal title="Decline this transfer?" onClose={onClose} footer={<>
      <button onClick={onClose}>Keep it waiting</button>
      <button className="danger solid" onClick={() => onConfirm(note, send && !!tpl)}>Decline and reject</button></>}>
      <div>Declining moves the candidate to <b>{rej?.name || 'Rejected'}</b>. {t.requested_by_name || 'The person who asked'} is told.</div>
      <Field label="Reason (optional, shared with them)"><textarea value={note} onChange={e => setNote(e.target.value)} /></Field>
      {tpl ? <label className="check"><input type="checkbox" checked={send} onChange={e => setSend(e.target.checked)} /> Send the “{tpl.name}” email to the candidate</label>
        : <div className="small muted">No rejection email is set up for this stage, so nothing is sent to the candidate.</div>}
    </Modal>
  )
}

function TransferModal({ c, onClose, onDone }) {
  const { meta } = useApp()
  const [to, setTo] = useState('')
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const target = meta.departments.find(d => String(d.id) === to)
  const go = async () => {
    setBusy(true); setErr('')
    try { await post(`/api/candidates/${c.id}/transfer`, { to_department_id: +to, note }); onDone(`Transfer request sent to ${target.name}`) }
    catch (e) { setErr(e.message); setBusy(false) }
  }
  return (
    <Modal title={`Transfer ${fullName(c)}`} onClose={onClose} footer={<>
      <button onClick={onClose}>Cancel</button>
      <button className="primary" disabled={busy || !to || !note.trim()} onClick={go}>Send request</button></>}>
      <Field label="To department"><select value={to} onChange={e => setTo(e.target.value)}><option value="">Choose…</option>
        {meta.departments.filter(d => d.active && d.id !== c.department_id).map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></Field>
      <Field label="Why? (required, they'll see this)"><textarea value={note} placeholder="e.g. Strong SCM background, better fit for the open SCM role" onChange={e => setNote(e.target.value)} /></Field>
      <div className="small muted">The candidate stays where they are until {target?.name || 'the other department'} accepts. If they decline, the candidate is rejected.</div>
      {err && <div className="alert bad">{err}</div>}
    </Modal>
  )
}

/* ---------------------------------------------------------------- emails, invites and candidate replies */

function Conversation({ data, c, canReply, onChange, setModal }) {
  const out = data.jobs.filter(j => j.kind !== 'free_busy').map(j => ({ t: j.created_at, kind: 'out', j }))
  const inc = (data.emails || []).map(e => ({ t: e.received_at, kind: 'in', e }))
  const items = [...out, ...inc].sort((a, b) => (a.t < b.t ? 1 : -1))
  const unread = inc.filter(x => x.e.unread).length
  return (
    <div className="card">
      <div className="row between"><h2 style={{ margin: 0 }}>Emails and invites</h2>
        {unread > 0 && <button className="sm ghost" onClick={() => post(`/api/candidates/${c.id}/emails/read-all`).then(() => onChange())}>Mark {unread} as read</button>}</div>
      {!items.length && <div className="muted" style={{ marginTop: 8 }}>Nothing sent yet.</div>}
      <div className="timeline" style={{ marginTop: 8 }}>{items.map(x => x.kind === 'in' ? (
        <div key={'in' + x.e.id} className={'item reply' + (x.e.unread ? ' unread' : '')}>
          <div className="row between"><span><Icon name="reply" size={14} /> <b>{x.e.from_name || x.e.from}</b> replied{x.e.unread && <span className="badge info" style={{ marginLeft: 6 }}>New</span>}</span>
            <span className="small muted">{fmtUtc(x.e.received_at)}</span></div>
          <div className="small"><b>{x.e.subject || '(no subject)'}</b></div>
          <div className="small muted reply-preview">{x.e.preview || '(no text)'}</div>
          <div className="row" style={{ marginTop: 6 }}>
            <button className="sm" onClick={() => setModal({ kind: 'viewreply', eid: x.e.id })}>View reply</button>
            {canReply && <button className="sm primary" onClick={() => setModal({ kind: 'reply', eid: x.e.id })}>Reply</button>}
            {x.e.attachments.length > 0 && <span className="small muted">{x.e.attachments.length} attachment{x.e.attachments.length > 1 ? 's' : ''}</span>}
          </div>
        </div>
      ) : (
        <div key={'out' + x.j.id} className={'item' + (x.j.reply_to ? ' answer' : '')}>
          <div className="row between"><span>{x.j.description}</span><JobBadge status={x.j.status} /></div>
          <div className="small muted">{fmtUtc(x.j.created_at)}{x.j.kind === 'reply_mail' && x.j.status === 'done' && (x.j.threaded ? ' · in the same thread' : ' · sent as a new email')}{x.j.error && <span style={{ color: 'var(--bad)' }}> · {x.j.error}</span>}</div>
        </div>
      ))}</div>
    </div>
  )
}

async function download(url, name) {
  const r = await fetch(url, { headers: { Authorization: 'Bearer ' + auth.token } })
  if (!r.ok) return alert('The file could not be downloaded')
  const href = URL.createObjectURL(await r.blob())
  const a = document.createElement('a'); a.href = href; a.download = name; a.click()
  setTimeout(() => URL.revokeObjectURL(href), 2000)
}

const kb = n => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'

function ViewReply({ eid, c, canReply, onClose, onReply }) {
  const [e, setE] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => { get(`/api/candidate-emails/${eid}`).then(setE, x => setErr(x.message)) }, [eid])
  return (
    <Modal wide title={e ? (e.subject || '(no subject)') : 'Reply'} onClose={onClose} footer={<>
      <button onClick={onClose}>Close</button>
      {canReply && e && <button className="primary" onClick={() => onReply(eid)}>Reply</button>}</>}>
      {err && <div className="alert bad">{err}</div>}
      {!e && !err && <Loading />}
      {e && <div className="col" style={{ gap: 10 }}>
        <div className="kv small">
          <div>From</div><div>{e.from_name ? `${e.from_name} <${e.from}>` : e.from}</div>
          <div>To</div><div>{e.to || ''}</div>
          {e.cc && <><div>CC</div><div>{e.cc}</div></>}
          <div>Received</div><div>{fmtUtc(e.received_at)}</div>
        </div>
        {e.attachments.length > 0 && <div className="row">{e.attachments.map(a => a.available
          ? <button key={a.index} className="sm" onClick={() => download(`/api/candidate-emails/${eid}/attachments/${a.index}`, a.name)}>⬇ {a.name} <span className="muted">({kb(a.size)})</span></button>
          : <span key={a.index} className="badge" title="Over 15 MB, so it wasn't copied. Open it in Outlook.">{a.name} (too large)</span>)}</div>}
        <div className="pre card mail-body">{e.body || '(no text)'}</div>
      </div>}
    </Modal>
  )
}

function ReplyModal({ eid, c, onClose, onDone }) {
  const { meta } = useApp()
  const [d, setD] = useState(null)
  const [body, setBody] = useState('')
  const [subject, setSubject] = useState('')
  const [ccDept, setCcDept] = useState(true)
  const [extraCc, setExtraCc] = useState('')
  const [tpl, setTpl] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const tpls = meta.email_templates.filter(t => t.active && !['test_access', 'reschedule'].includes(t.key))
  useEffect(() => { get(`/api/candidate-emails/${eid}/reply-draft`).then(r => { setD(r); setSubject(r.subject) }, x => setErr(x.message)) }, [eid])
  const pickTemplate = async id => {
    setTpl(id)
    if (!id) return
    try { const m = await post(`/api/candidates/${c.id}/email/preview`, { template_id: +id }); setBody(m.body) } catch (x) { setErr(x.message) }
  }
  const send = async () => {
    setBusy(true); setErr('')
    const cc = [ccDept ? d.dept_cc : '', extraCc].filter(Boolean).join('; ')
    try {
      const r = await post(`/api/candidate-emails/${eid}/reply`, { body, cc, subject })
      onDone(r.threaded ? 'Reply queued; it goes out in the same thread' : 'Reply queued; it goes out as a new email with the earlier message quoted')
    } catch (x) { setErr(x.message); setBusy(false) }
  }
  return (
    <Modal wide title={`Reply to ${fullName(c)}`} onClose={onClose} footer={<>
      <button onClick={onClose}>Cancel</button>
      <button className="primary" disabled={!d || !body.trim() || busy} onClick={send}>Send reply</button></>}>
      {!d && !err && <Loading />}
      {d && <div className="col" style={{ gap: 10 }}>
        <div className="grid2"><Field label="To"><input readOnly value={d.to} /></Field>
          <Field label="Start from a template (optional)"><select value={tpl} onChange={e => pickTemplate(e.target.value)}><option value="">None</option>{tpls.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field></div>
        <Field label="Subject"><input value={subject} onChange={e => setSubject(e.target.value)} /></Field>
        {d.dept_cc && <label className="check"><input type="checkbox" checked={ccDept} onChange={e => setCcDept(e.target.checked)} /> CC the department ({d.dept_cc})</label>}
        <Field label="Other CC (optional)"><input value={extraCc} placeholder="name@novamodus.com" onChange={e => setExtraCc(e.target.value)} /></Field>
        <Field label="Message"><textarea className="tall" value={body} onChange={e => setBody(e.target.value)} placeholder="Your answer. Their message is quoted underneath automatically." /></Field>
        <div className="small muted">{d.threaded ? "Their email is in your inbox, so this goes out as a reply in the same thread" : "Their email isn't in your inbox, so this goes out as a new email with \"RE:\" and their message quoted"}, from your {d.via === 'graph' ? 'Microsoft 365 mailbox' : 'Outlook'}.</div>
      </div>}
      {err && <div className="alert bad">{err}</div>}
    </Modal>
  )
}

/* ---------------------------------------------------------------- interview feedback */

let questionCache = null
function useFeedbackQuestions() {
  const [qs, setQs] = useState(questionCache)
  useEffect(() => { if (!questionCache) get('/api/feedback/questions').then(r => { questionCache = r; setQs(r) }) }, [])
  return qs
}

function InterviewFeedback({ iv, items, canEdit, onSaved }) {
  const { me, can, meta } = useApp()
  const [open, setOpen] = useState(false)
  const qs = useFeedbackQuestions()
  if (meta.settings?.feedback_enabled === 'false') return null
  const mine = items.find(f => f.user_id === me.id)
  const started = new Date(iv.start) <= new Date()
  const qname = id => qs?.find(q => String(q.id) === String(id))?.label || 'Removed question'
  return (
    <div style={{ marginTop: 6 }}>
      {items.length > 0 && <details className="small"><summary><b>Feedback ({items.length})</b></summary>
        {items.map(f => (
          <div key={f.id} className="card" style={{ marginTop: 6, padding: 10 }}>
            <div className="row between"><b>{f.user_name}</b><span className="muted">{fmtUtc(f.updated_at || f.created_at)}</span></div>
            <div className="kv" style={{ marginTop: 4 }}>{Object.entries(f.answers || {}).flatMap(([k, v]) => [<div key={k}>{qname(k)}</div>, <div key={k + 'v'} className="pre">{v}</div>])}</div>
            {(f.user_id === me.id || can('users.manage')) && <button className="sm ghost" onClick={() => del(`/api/feedback/${f.id}`).then(() => onSaved('Feedback removed'))}>Remove</button>}
          </div>))}
      </details>}
      {canEdit && iv.status !== 'cancelled' && started && <button className="sm" style={{ marginTop: 6 }} onClick={() => setOpen(true)}>{mine ? 'Edit my feedback' : 'Add feedback'}</button>}
      {open && qs && <FeedbackModal iv={iv} qs={qs} mine={mine} onClose={() => setOpen(false)} onDone={() => { setOpen(false); onSaved('Feedback saved') }} />}
    </div>
  )
}

function FeedbackModal({ iv, qs, mine, onClose, onDone }) {
  const [ans, setAns] = useState(mine?.answers || {})
  const [err, setErr] = useState('')
  const set = (id, v) => setAns(a => ({ ...a, [id]: v }))
  const save = () => post(`/api/interviews/${iv.id}/feedback`, { answers: ans }).then(onDone, e => setErr(e.message))
  return (
    <Modal title={`Feedback: ${iv.title || 'Interview'}`} onClose={onClose} footer={<><button onClick={onClose}>Cancel</button><button className="primary" onClick={save}>Save feedback</button></>}>
      <div className="small muted">Optional. Only people who work in this candidate's department can read it.</div>
      {qs.map(q => (
        <Field key={q.id} label={q.label + (q.required ? ' *' : '')}>
          {q.kind === 'rating' && <div className="row">{q.options.map(o => <button key={o} type="button" className={'sm' + (ans[q.id] === o ? ' primary' : '')} onClick={() => set(q.id, o)}>{o}</button>)}</div>}
          {q.kind === 'choice' && <div className="row">{q.options.map(o => <label key={o} className="check"><input type="radio" checked={ans[q.id] === o} onChange={() => set(q.id, o)} /> {o}</label>)}</div>}
          {q.kind === 'text' && <textarea style={{ minHeight: 70 }} value={ans[q.id] || ''} onChange={e => set(q.id, e.target.value)} />}
        </Field>))}
      {err && <div className="alert bad">{err}</div>}
    </Modal>
  )
}

/* ---------------------------------------------------------------- keeping details past the clear-out date */

function KeepCard({ c, onDone }) {
  const { meta } = useApp()
  if (meta.settings?.retention_enabled !== 'true') return null
  const months = meta.settings?.retention_months || 12
  return (
    <div className="card row between" style={{ padding: '10px 14px' }}>
      <span className="small">{c.retention_keep ? <><b>Kept:</b> this candidate's details won't be removed automatically.</>
        : <>This candidate's personal details will be removed {months} months after they were {meta.stages.find(s => s.id === c.stage_id)?.name.toLowerCase()}. Admins get a warning first.</>}</span>
      <label className="check"><input type="checkbox" checked={!!c.retention_keep}
        onChange={e => put(`/api/candidates/${c.id}/retention-keep`, { keep: e.target.checked }).then(() => onDone(e.target.checked ? 'Details will be kept' : 'Details will be removed on schedule'))} /> Keep details</label>
    </div>
  )
}
