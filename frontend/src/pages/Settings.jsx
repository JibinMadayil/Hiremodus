import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Logo } from '../brand'
import Icon from '../icons'
import { get, post, put, del, api, fmtUtc } from '../api'
import { useApp, Modal, Field, Loading, Confirm, EmailList, DeptPicker } from '../ui'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export default function Settings() {
  const { meta, can } = useApp()
  const [params, setParams] = useSearchParams()
  const all = [
    ['general', 'General', 'settings.manage'], ['aging', 'Aging rules', 'settings.manage'], ['users', 'Users', 'users.manage'],
    ['roles', 'Roles', 'users.manage'], ['departments', 'Departments', 'settings.manage'], ['stages', 'Pipeline stages', 'settings.manage'],
    ['email', 'Email templates', 'settings.manage'], ['interview', 'Interview types', 'settings.manage'], ['modules', 'Training modules', 'settings.manage'],
    ['holidays', 'Holidays', 'settings.manage'], ['fields', 'Custom fields', 'settings.manage'], ['notify', 'Notifications', 'settings.manage'],
    ['integrity', 'Test integrity', 'settings.manage'], ['feedback', 'Interview feedback', 'settings.manage'],
    ['microsoft', 'Email and Microsoft 365', 'settings.manage'], ['retention', 'Clearing old data', 'users.manage'],
    ['branding', 'Branding', 'settings.manage'], ['audit', 'Audit log', 'audit.view'],
  ]
  const tabs = all.filter(t => can(t[2]))
  const tab = tabs.find(t => t[0] === params.get('tab'))?.[0] || tabs[0]?.[0]
  const setTab = k => setParams({ tab: k })
  if (!tabs.length) return <div className="card empty">Your role has no settings to change.</div>
  return (
    <div className="col">
      <div className="page-head"><div><h1>Settings</h1><div className="muted">Departments, people, email wording, interview rules, aging rules, branding and access.</div></div></div>
      <div className="tabs">{tabs.map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
      {tab === 'general' && <General />}
      {tab === 'aging' && <AgingRules />}
      {tab === 'users' && <Users />}
      {tab === 'roles' && <Roles />}
      {tab === 'departments' && <ListEditor kind="departments" title="Department" fields={DEPT_FIELDS} columns={[['name', 'Name'], ['cc_emails', 'Recruiters / CC list (also gives access)', 'emails'], ['active', 'Active', 'bool']]} />}
      {tab === 'stages' && <Stages />}
      {tab === 'email' && <EmailTemplates />}
      {tab === 'interview' && <InterviewTemplates />}
      {tab === 'modules' && <ListEditor kind="modules" title="Module" fields={MODULE_FIELDS} columns={[['name', 'Module'], ['web_link', 'Oracle docs', 'link'], ['training_link', 'Training portal', 'link'], ['test_id', 'Test', 'fn'], ['active', 'Active', 'bool']]}
        extra={r => meta.tests.find(t => t.id === r.test_id)?.name || <span className="muted">None</span>} />}
      {tab === 'holidays' && <ListEditor kind="holidays" title="Holiday" fields={[{ k: 'day', label: 'Date', type: 'date' }, { k: 'name', label: 'Name' }]} columns={[['day', 'Date'], ['name', 'Name']]} hint="Automatic slot searches skip these days." />}
      {tab === 'fields' && <ListEditor kind="custom-fields" title="Custom field" fields={CUSTOM_FIELD_FIELDS} defaults={{ kind: 'text', options: [], sort: 0 }}
        columns={[['sort', '#'], ['label', 'Field'], ['kind', 'Type'], ['show_in_list', 'Offered as a list column', 'bool'], ['active', 'Active', 'bool']]}
        hint="Extra details you want to keep on every candidate. They appear on the candidate page and can be added as columns on the Candidates list." />}
      {tab === 'notify' && <Notifications />}
      {tab === 'integrity' && <Integrity />}
      {tab === 'feedback' && <FeedbackQuestions />}
      {tab === 'microsoft' && <Microsoft365 />}
      {tab === 'retention' && <Retention />}
      {tab === 'branding' && <Branding />}
      {tab === 'audit' && <Audit />}
    </div>
  )
}

const CUSTOM_FIELD_FIELDS = [
  { k: 'label', label: 'Label', span: 2 },
  { k: 'kind', label: 'Type', type: 'select', options: [['text', 'Short text'], ['long', 'Long text'], ['number', 'Number'], ['date', 'Date'], ['select', 'Dropdown'], ['checkbox', 'Yes / no']] },
  { k: 'sort', label: 'Order', type: 'number' },
  { k: 'options', label: 'Dropdown choices (comma separated)', type: 'csv', span: 2 },
  { k: 'show_in_list', label: 'Offer as a column on the Candidates list', type: 'bool' },
  { k: 'active', label: 'Active', type: 'bool' },
]

const DEPT_FIELDS = [
  { k: 'name', label: 'Name' }, { k: 'color', label: 'Colour', type: 'color' },
  { k: 'cc_emails', label: 'Department recruiters: CC on rejection, withdrawal and aging alerts', type: 'emails', span: 2, hint: "Recruiters on this list can also open this department's candidates, tests and results, even if it isn't ticked on their user." },
  { k: 'active', label: 'Active', type: 'bool' },
]
const MODULE_FIELDS = [
  { k: 'name', label: 'Module name', span: 2 },
  { k: 'web_link', label: 'Oracle documentation link ({{module_web_link}})', type: 'textarea', span: 2 },
  { k: 'training_link', label: 'Training portal link ({{module_training_link}})', type: 'textarea', span: 2 },
  { k: 'test_id', label: 'Test for this module', type: 'test', span: 2, hint: 'Used when an interview type that includes a test is booked with this module. Leave empty to use the interview type’s own test.' },
  { k: 'active', label: 'Active', type: 'bool' },
]

function General() {
  const { toast, refreshMeta } = useApp()
  const [s, setS] = useState(null)
  useEffect(() => { get('/api/settings').then(setS) }, [])
  if (!s) return <Loading />
  const set = (k, v) => setS(x => ({ ...x, [k]: v }))
  const save = () => put('/api/settings', s).then(r => { setS(r); refreshMeta(); toast('Settings saved') }, e => toast(e.message, 'bad'))
  return (
    <div className="card col" style={{ maxWidth: 900 }}>
      <div className="grid2">
        <Field label="Company name ({{company}})"><input value={s.company_name} onChange={e => set('company_name', e.target.value)} /></Field>
        <Field label="Test portal address" hint="The public link candidates use. Put in the real address once hosted."><input value={s.portal_base_url} onChange={e => set('portal_base_url', e.target.value)} /></Field>
        <Field label="Always CC (on templates that use it)" className="span2"><input value={s.global_cc} onChange={e => set('global_cc', e.target.value)} /></Field>
        <Field label="AI interview link ({{ai_interview_link}})"><input value={s.ai_interview_link} onChange={e => set('ai_interview_link', e.target.value)} /></Field>
        <Field label="AI result link starts with" hint="Pasting a link like this on an 'AI Interview Sent' candidate moves them on"><input value={s.ai_link_prefix} onChange={e => set('ai_link_prefix', e.target.value)} /></Field>
        <Field label="Oracle instance credentials link ({{instance_link}})" className="span2"><input value={s.instance_credentials_link} onChange={e => set('instance_credentials_link', e.target.value)} /></Field>
        <Field label="IT access requests go to"><input value={s.it_emails} onChange={e => set('it_emails', e.target.value)} /></Field>
        <Field label="IT access requests CC"><input value={s.it_cc} onChange={e => set('it_cc', e.target.value)} /></Field>
      </div>
      <label className="check"><input type="checkbox" checked={s.simulate_outlook === 'true'} onChange={e => set('simulate_outlook', e.target.checked ? 'true' : 'false')} />
        <span><b>Simulate Outlook</b>: record emails and invites in the Outbox without sending them, and invent calendar availability. Turn this off once people have the Outlook Connector running.</span></label>
      <div className="row end"><button className="primary" onClick={save}>Save settings</button></div>
    </div>
  )
}

/* ------------------------------------------------------------------ generic list editor */

export function FieldInput({ f, value, onChange }) {
  const { meta } = useApp()
  switch (f.type) {
    case 'bool': return <label className="check"><input type="checkbox" checked={!!value} onChange={e => onChange(e.target.checked)} /> {f.label}</label>
    case 'textarea': return <textarea style={{ minHeight: 60 }} value={value || ''} onChange={e => onChange(e.target.value)} />
    case 'tall': return <textarea className="tall" value={value || ''} onChange={e => onChange(e.target.value)} />
    case 'emails': return <textarea style={{ minHeight: 48 }} placeholder="name@novamodus.com; other@novamodus.com" value={value || ''} onChange={e => onChange(e.target.value)} />
    case 'number': return <input type="number" value={value ?? ''} onChange={e => onChange(e.target.value === '' ? null : +e.target.value)} />
    case 'date': return <input type="date" value={value || ''} onChange={e => onChange(e.target.value)} />
    case 'time': return <input type="time" value={value || ''} onChange={e => onChange(e.target.value)} />
    case 'color': return <input type="color" value={value || '#4f6bed'} onChange={e => onChange(e.target.value)} style={{ height: 36, padding: 2 }} />
    case 'dept': return <select value={value || ''} onChange={e => onChange(e.target.value ? +e.target.value : null)}><option value="">{f.none || 'None'}</option>{meta.departments.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
    case 'stage': return <select value={value || ''} onChange={e => onChange(e.target.value ? +e.target.value : null)}><option value="">{f.none || 'None'}</option>{meta.stages.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
    case 'test': return <select value={value || ''} onChange={e => onChange(e.target.value ? +e.target.value : null)}><option value="">None</option>{meta.tests.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
    case 'etpl': return <select value={value || ''} onChange={e => onChange(e.target.value ? +e.target.value : null)}><option value="">No email</option>{meta.email_templates.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
    case 'select': return <select value={value ?? ''} onChange={e => onChange(e.target.value)}>{f.options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
    case 'csv': return <input value={(value || []).join(', ')} onChange={e => onChange(e.target.value.split(',').map(x => x.trim()).filter(Boolean))} />
    case 'weekdays': return <div className="row">{DAYS.map((d, i) => <label key={d} className="check"><input type="checkbox" checked={(value || []).includes(i + 1)} onChange={e => onChange(e.target.checked ? [...(value || []), i + 1].sort() : (value || []).filter(x => x !== i + 1))} />{d}</label>)}</div>
    case 'depts': return <div className="row">{meta.departments.map(d => <label key={d.id} className="check"><input type="checkbox" checked={(value || []).includes(d.id)} onChange={e => onChange(e.target.checked ? [...(value || []), d.id] : (value || []).filter(x => x !== d.id))} />{d.name}</label>)}</div>
    default: return <input value={value ?? ''} onChange={e => onChange(e.target.value)} />
  }
}

export function RecordForm({ fields, value, onChange, cols = 2 }) {
  return (
    <div className={cols === 3 ? 'grid3' : 'grid2'}>
      {fields.map(f => f.section ? <h3 key={f.section} className={cols === 3 ? 'span3' : 'span2'} style={{ marginTop: 8, borderTop: '1px solid var(--line)', paddingTop: 12 }}>{f.section}</h3> :
        f.type === 'bool' ? <div key={f.k} className={f.span === 2 ? 'span2' : f.span === 3 ? 'span3' : ''}><FieldInput f={f} value={value[f.k]} onChange={v => onChange({ ...value, [f.k]: v })} />{f.hint && <div className="small muted" style={{ marginLeft: 24 }}>{f.hint}</div>}</div> :
          <Field key={f.k} label={f.label} hint={f.hint} className={f.span === 2 ? 'span2' : f.span === 3 ? 'span3' : ''}><FieldInput f={f} value={value[f.k]} onChange={v => onChange({ ...value, [f.k]: v })} /></Field>)}
    </div>
  )
}

function ListEditor({ kind, title, fields, columns, hint, defaults = {}, wide, cols, extra }) {
  const { toast, refreshMeta } = useApp()
  const [list, setList] = useState(null)
  const [edit, setEdit] = useState(null)
  const [delItem, setDelItem] = useState(null)
  const load = () => get(`/api/admin/${kind}`).then(setList)
  useEffect(() => { load() }, [kind]) // eslint-disable-line
  const save = async () => {
    try {
      if (edit.id) await put(`/api/admin/${kind}/${edit.id}`, edit); else await post(`/api/admin/${kind}`, edit)
      toast('Saved'); setEdit(null); load(); refreshMeta()
    } catch (e) { toast(e.message, 'bad') }
  }
  const remove = async () => {
    try { await del(`/api/admin/${kind}/${delItem.id}`); toast('Deleted'); setDelItem(null); load(); refreshMeta() } catch (e) { toast(e.message, 'bad'); setDelItem(null) }
  }
  if (!list) return <Loading />
  return (
    <div className="col">
      <div className="row between">{hint ? <div className="muted">{hint}</div> : <span />}<button className="primary" onClick={() => setEdit({ active: true, ...defaults })}>Add {title.toLowerCase()}</button></div>
      <div className="card tight"><table>
        <thead><tr>{columns.map(([k, l]) => <th key={k}>{l}</th>)}<th></th></tr></thead>
        <tbody>{list.map(r => (
          <tr key={r.id} className="click" onClick={() => setEdit({ ...r })}>
            {columns.map(([k, , t]) => <td key={k}>{t === 'bool' ? (r[k] ? 'Yes' : <span className="muted">No</span>) : t === 'emails' ? <EmailList value={r[k]} /> : t === 'link' ? (r[k] ? <span className="small muted">{r[k].slice(0, 40)}…</span> : <span className="badge warn">Missing</span>) : t === 'fn' ? extra(r, k) : String(r[k] ?? '')}</td>)}
            <td className="row end" onClick={e => e.stopPropagation()}><button className="sm danger" onClick={() => setDelItem(r)}>Delete</button></td>
          </tr>
        ))}</tbody>
      </table></div>
      {edit && <Modal wide={wide} title={`${edit.id ? 'Edit' : 'New'} ${title.toLowerCase()}`} onClose={() => setEdit(null)} footer={<><button onClick={() => setEdit(null)}>Cancel</button><button className="primary" onClick={save}>Save</button></>}>
        <RecordForm fields={fields} value={edit} onChange={setEdit} cols={cols} />
      </Modal>}
      {delItem && <Confirm title={`Delete ${title.toLowerCase()}`} danger confirmLabel="Delete" message={`Delete “${delItem.name || delItem.day}”? If it's still in use, turn it off instead.`} onClose={() => setDelItem(null)} onConfirm={remove} />}
    </div>
  )
}

function Stages() {
  const { meta } = useApp()
  return <ListEditor kind="stages" title="Stage" columns={[['sort', '#'], ['name', 'Stage'], ['kind', 'Type'], ['entry_template_id', 'Email when a candidate enters', 'fn'], ['aging_enabled', 'Aging rules', 'bool'], ['active', 'Active', 'bool']]}
    extra={(r) => meta.email_templates.find(t => t.id === r.entry_template_id)?.name || <span className="muted">None</span>}
    hint="Order is the order shown across the app. A stage's entry email is offered (with a confirmation) whenever candidates are moved into it."
    fields={[
      { k: 'name', label: 'Name' }, { k: 'sort', label: 'Order', type: 'number' },
      { k: 'kind', label: 'Type', type: 'select', options: [['open', 'Open (in progress)'], ['hired', 'Hired'], ['rejected', 'Rejected'], ['withdrawn', 'Withdrawn']] },
      { k: 'color', label: 'Colour', type: 'color' },
      { k: 'entry_template_id', label: 'Email to send when a candidate enters this stage', type: 'etpl', span: 2 },
      { k: 'advance_on_ai_link_to_id', label: 'When an AI interview link is pasted, move to', type: 'stage', none: 'Stay here', span: 2 },
      { k: 'requires_department', label: 'Candidates must have a department to enter', type: 'bool', span: 2 },
      { section: 'Aging rules for this stage' },
      { k: 'aging_enabled', label: 'Count days without contact in this stage (alert and automatic rejection)', type: 'bool', span: 2 },
      { k: 'alert_days', label: 'Alert after (days), empty = global setting', type: 'number' },
      { k: 'reject_days', label: 'Reject after (days), empty = global setting', type: 'number' },
      { k: 'active', label: 'Active', type: 'bool' },
    ]} />
}

function PlaceholderHelp() {
  const { meta } = useApp()
  return <details className="small"><summary className="muted">Placeholders you can use</summary>
    <div className="kv" style={{ marginTop: 6 }}>{Object.entries(meta.placeholders).flatMap(([k, v]) => [<div key={k} className="mono">{`{{${k}}}`}</div>, <div key={k + '_d'}>{v}</div>])}</div></details>
}

function EmailTemplates() {
  return <div className="col"><PlaceholderHelp />
    <ListEditor kind="email-templates" title="Email template" wide
      columns={[['name', 'Template'], ['subject', 'Subject'], ['show_as_action', 'Button on candidate page', 'bool'], ['active', 'Active', 'bool']]}
      defaults={{ include_global_cc: true, exclude_sender_from_cc: true, department_ids: [], body: 'Good Day {{first_name}},\n\n\n\nThank you' }}
      fields={[
        { k: 'name', label: 'Template name' }, { k: 'subject', label: 'Subject' },
        { k: 'body', label: 'Message', type: 'tall', span: 2 },
        { k: 'cc', label: 'CC', type: 'emails', span: 2 },
        { k: 'include_global_cc', label: 'Also CC the “Always CC” list from General', type: 'bool' },
        { k: 'include_department_cc', label: "Also CC the candidate's department list", type: 'bool' },
        { k: 'exclude_sender_from_cc', label: 'Leave the sender off the CC', type: 'bool' },
        { k: 'show_as_action', label: 'Show as a quick button on the candidate page', type: 'bool' },
        { k: 'department_ids', label: 'Only for these departments (none ticked = all)', type: 'depts', span: 2 },
        { k: 'moves_to_stage_id', label: 'After sending, move the candidate to', type: 'stage', none: "Don't move" },
        { k: 'due_days', label: 'Days until {{due_date}}', type: 'number' },
        { k: 'notify_it', label: 'Ask IT to grant access to SharePoint links', type: 'bool' },
        { k: 'it_links', label: 'Links for IT (placeholders allowed)', type: 'textarea', span: 2 },
        { k: 'active', label: 'Active', type: 'bool' },
      ]} /></div>
}

function InterviewTemplates() {
  const { meta } = useApp()
  return <div className="col"><PlaceholderHelp />
    <ListEditor kind="interview-templates" title="Interview type" wide cols={3}
      columns={[['name', 'Interview type'], ['department_id', 'Department', 'fn'], ['duration_min', 'Minutes'], ['weekdays', 'Days', 'fn'], ['day_start', 'Hours', 'fn'], ['includes_test', 'Test', 'bool'], ['active', 'Active', 'bool']]}
      extra={(r, k) => k === 'department_id' ? (meta.departments.find(d => d.id === r.department_id)?.name || 'Any')
        : k === 'weekdays' ? (r.weekdays || []).map(d => DAYS[d - 1]).join(', ') : `${r.day_start}–${r.day_end}`}
      defaults={{ duration_min: 30, weekdays: [1, 2, 3, 4, 5], day_start: '09:00', day_end: '18:00', search_offset_days: 0, search_window_days: 14, slot_options: 5, check_own_calendar: true, flex_min_free: 1, round_number: 1, round_label: 'First Round', send_confirmation_email: true, invite_subject: '{{round}} Interview - {{full_name}} - {{company}}', confirmation_subject: 'Interview Confirmation - {{company}}', invite_body: 'Good Day {{first_name}},\n\nDate and Time: {{interview_date}} at {{interview_time}}\nLocation: {{location}}\n\n{{test_block}}\n\nThank you' }}
      fields={[
        { k: 'name', label: 'Name', span: 2 }, { k: 'department_id', label: 'Department', type: 'dept', none: 'Any' },
        { k: 'round_label', label: 'Round label ({{round}})' }, { k: 'round_number', label: 'Round number', type: 'number' }, { k: 'duration_min', label: 'Length (minutes)', type: 'number' },
        { section: 'When' },
        { k: 'weekdays', label: 'Allowed days', type: 'weekdays', span: 3 },
        { k: 'day_start', label: 'Earliest start', type: 'time' }, { k: 'day_end', label: 'Must end by', type: 'time' }, { k: 'slot_options', label: 'Times to offer', type: 'number' },
        { k: 'search_offset_days', label: 'Start searching this many days out', type: 'number' }, { k: 'search_window_days', label: 'Search window (days)', type: 'number' },
        { k: 'check_own_calendar', label: "Check the organizer's own calendar too", type: 'bool' },
        { section: 'Who' },
        { k: 'required_emails', label: 'Always required', type: 'emails', span: 3 },
        { k: 'flex_emails', label: 'Rotating interviewers: required when free, optional when busy', type: 'emails', span: 3, hint: 'Like the ERP-EPM trio. Leave empty if not used.' },
        { k: 'flex_preferred_emails', label: 'Try first for times when these rotating people are all free', type: 'emails', span: 2 },
        { k: 'flex_min_free', label: 'At least this many rotating people free', type: 'number' },
        { k: 'optional_emails', label: 'Optional attendees', type: 'emails', span: 2 },
        { k: 'ask_extra_cc', label: 'Ask for an extra CC when booking', type: 'bool' },
        { section: 'Invite' },
        { k: 'location', label: 'Location ({{location}})', span: 3 },
        { k: 'invite_subject', label: 'Invite subject', span: 3 },
        { k: 'invite_body', label: 'Invite text', type: 'tall', span: 3 },
        { k: 'send_confirmation_email', label: 'Also send a separate confirmation email', type: 'bool' },
        { k: 'confirmation_subject', label: 'Confirmation email subject', span: 2 },
        { section: 'Module, test and IT' },
        { k: 'requires_module', label: 'Ask for a training module', type: 'bool' },
        { k: 'reuse_previous_module', label: 'Default to the module from the earlier round', type: 'bool' },
        { k: 'includes_test', label: 'Includes a test (creates a login in the invite)', type: 'bool' },
        { k: 'test_id', label: 'Test', type: 'test' },
        { k: 'notify_it', label: 'Ask IT to grant SharePoint access', type: 'bool' },
        { k: 'it_links', label: 'Links for IT', type: 'textarea', span: 3 },
        { k: 'active', label: 'Active', type: 'bool' },
      ]} /></div>
}

function Users() {
  const { meta, me, toast, refreshMeta } = useApp()
  const [list, setList] = useState(null)
  const [edit, setEdit] = useState(null)
  const load = () => get('/api/users').then(setList)
  useEffect(() => { load() }, [])
  const save = async () => {
    try {
      if (edit.id) await put(`/api/users/${edit.id}`, edit); else await post('/api/users', edit)
      toast('Saved'); setEdit(null); load(); refreshMeta()
    } catch (e) { toast(e.message, 'bad') }
  }
  if (!list) return <Loading />
  const roles = meta.roles
  return (
    <div className="col">
      <div className="row between"><div className="muted">A person can hold several roles. <b>Admin</b> sees every department but not question papers. <b>Admin + Recruiter</b> sees everything. <b>Recruiter</b> works only in their departments. <b>Associate</b> adds candidates and works the AI stages and Screening. Every change is written to the audit log.</div>
        <button className="primary" onClick={() => setEdit({ role_ids: [roles.find(r => r.key === 'recruiter')?.id].filter(Boolean), department_ids: [], active: true })}><Icon name="plus" size={16} />Add user</button></div>
      <div className="card tight"><table>
        <thead><tr><th>Name</th><th>Email</th><th>Roles</th><th>Departments</th><th>Outlook</th><th>Active</th></tr></thead>
        <tbody>{list.map(u => (
          <tr key={u.id} className="click" onClick={() => setEdit({ ...u, password: '' })}>
            <td><b>{u.name}</b></td><td>{u.email}</td>
            <td><div className="chips">{u.roles.map(r => <span key={r} className="badge brand">{r}</span>)}</div></td>
            <td className="small">{u.department_ids.map(id => meta.departments.find(d => d.id === id)?.name).join(', ')}</td>
            <td>{u.permissions.includes('emails.send') ? (u.connector_online ? <span className="badge ok">Online</span> : <span className="badge">Offline</span>) : ''}</td>
            <td>{u.active ? 'Yes' : <span className="muted">No</span>}</td>
          </tr>
        ))}</tbody>
      </table></div>
      {edit && <Modal title={edit.id ? 'Edit user' : 'Add user'} onClose={() => setEdit(null)} footer={<><button onClick={() => setEdit(null)}>Cancel</button><button className="primary" onClick={save}>Save</button></>}>
        <div className="grid2">
          <Field label="Name"><input value={edit.name || ''} onChange={e => setEdit({ ...edit, name: e.target.value })} /></Field>
          <Field label="Email (their Outlook address)"><input value={edit.email || ''} disabled={!!edit.id} onChange={e => setEdit({ ...edit, email: e.target.value })} /></Field>
          <Field label="Roles" className="span2"><div className="col" style={{ gap: 6 }}>{roles.map(r => (
            <label key={r.id} className="check"><input type="checkbox" checked={(edit.role_ids || []).includes(r.id)}
              onChange={e => setEdit({ ...edit, role_ids: e.target.checked ? [...(edit.role_ids || []), r.id] : (edit.role_ids || []).filter(x => x !== r.id) })} />
              <b>{r.name}</b> <span className="muted" style={{ fontWeight: 400 }}>{r.description}</span></label>))}</div></Field>
          <Field label={edit.id ? 'Reset password (optional)' : 'Temporary password'} hint="They'll be asked to change it"><input type="text" value={edit.password || ''} onChange={e => setEdit({ ...edit, password: e.target.value })} /></Field>
          {(() => {
            const keys = roles.filter(r => (edit.role_ids || []).includes(r.id))
            const unscoped = keys.some(r => !r.department_scoped)
            const assocOnly = keys.length > 0 && keys.every(r => r.key === 'associate')
            return <Field label="Departments they work in" className="span2"
              hint={unscoped ? 'Not needed: their role already sees every department.' : assocOnly ? "Associates don't need departments; they work on candidates before a department takes them."
                : "They'll only see these departments' candidates, tests and results in full (plus any department whose CC list has their email). Everyone else's candidates show as read-only."}>
              <DeptPicker value={edit.department_ids || []} onChange={v => setEdit({ ...edit, department_ids: v })} /></Field>
          })()}
          {edit.id && edit.id !== me.id && <label className="check"><input type="checkbox" checked={edit.active} onChange={e => setEdit({ ...edit, active: e.target.checked })} /> Active</label>}
        </div>
      </Modal>}
    </div>
  )
}

function Roles() {
  const { meta, toast, refreshMeta } = useApp()
  const [list, setList] = useState(null)
  const [edit, setEdit] = useState(null)
  const load = () => get('/api/roles').then(setList)
  useEffect(() => { load() }, [])
  const save = async () => {
    try {
      if (edit.id) await put(`/api/roles/${edit.id}`, edit); else await post('/api/roles', edit)
      toast('Role saved'); setEdit(null); load(); refreshMeta()
    } catch (e) { toast(e.message, 'bad') }
  }
  const remove = async r => { try { await del(`/api/roles/${r.id}`); toast('Deleted'); load(); refreshMeta() } catch (e) { toast(e.message, 'bad') } }
  if (!list) return <Loading />
  const perms = Object.entries(meta.permissions)
  return (
    <div className="col">
      <div className="row between"><div className="muted">Decide what each role can do. Changes apply immediately and are written to the audit log.</div>
        <button className="primary" onClick={() => setEdit({ name: '', permissions: ['candidates.view'], department_scoped: false, description: '' })}><Icon name="plus" size={16} />New role</button></div>
      <div className="card tight"><table>
        <thead><tr><th>Role</th><th>Can do</th><th>People</th><th></th></tr></thead>
        <tbody>{list.map(r => (
          <tr key={r.id} className="click" onClick={() => setEdit({ ...r })}>
            <td><b>{r.name}</b>{r.builtin && <span className="badge" style={{ marginLeft: 6 }}>Built-in</span>}{r.department_scoped && <span className="badge info" style={{ marginLeft: 6 }}>Own departments only</span>}<div className="small muted">{r.description}</div></td>
            <td className="small">{r.permissions.length} of {perms.length}{!r.permissions.includes('tests.papers') ? <div className="muted">No test papers</div> : <div style={{ color: 'var(--brand)' }}>Includes test papers</div>}</td>
            <td>{r.users}</td>
            <td onClick={e => e.stopPropagation()}>{!r.builtin && <button className="sm danger" onClick={() => remove(r)}>Delete</button>}</td>
          </tr>
        ))}</tbody>
      </table></div>
      {edit && <Modal wide title={edit.id ? `Role: ${edit.name}` : 'New role'} onClose={() => setEdit(null)} footer={<><button onClick={() => setEdit(null)}>Cancel</button><button className="primary" onClick={save}>Save</button></>}>
        <div className="grid2">
          <Field label="Name"><input value={edit.name} disabled={edit.builtin} onChange={e => setEdit({ ...edit, name: e.target.value })} /></Field>
          <Field label="Description"><input value={edit.description || ''} onChange={e => setEdit({ ...edit, description: e.target.value })} /></Field>
        </div>
        <label className="check"><input type="checkbox" checked={!!edit.department_scoped} onChange={e => setEdit({ ...edit, department_scoped: e.target.checked })} /> Only see candidates in the user's own departments</label>
        <div className="grid2">{perms.map(([k, label]) => (
          <label key={k} className="check" style={{ alignItems: 'flex-start' }}><input type="checkbox" checked={edit.permissions.includes(k)}
            onChange={e => setEdit({ ...edit, permissions: e.target.checked ? [...edit.permissions, k] : edit.permissions.filter(x => x !== k) })} />
            <span>{label}{k === 'tests.papers' && <span className="small muted"> (keep this to Recruiters)</span>}</span></label>))}</div>
      </Modal>}
    </div>
  )
}

function Audit() {
  const [q, setQ] = useState('')
  const [action, setAction] = useState('')
  const [list, setList] = useState(null)
  useEffect(() => { const t = setTimeout(() => get(`/api/audit?q=${encodeURIComponent(q)}&action=${action}`).then(setList), 250); return () => clearTimeout(t) }, [q, action])
  const ACTIONS = [['', 'Everything'], ['user_roles_changed,user_created,user_disabled,user_enabled,user_departments_changed,user_password_reset,role_changed,role_created,role_deleted', 'Users and roles'],
    ['auto_rejected', 'Automatic rejections'], ['moved', 'Stage moves'], ['candidate_updated', 'Candidate edits'], ['candidate_deleted', 'Deletions'], ['sign_in', 'Sign-ins']]
  return (
    <div className="col">
      <div className="row"><input style={{ maxWidth: 320 }} placeholder="Search who, what or details" value={q} onChange={e => setQ(e.target.value)} />
        <select style={{ maxWidth: 240 }} value={action} onChange={e => setAction(e.target.value)}>{ACTIONS.map(([v, l]) => <option key={l} value={v}>{l}</option>)}</select></div>
      {!list ? <Loading /> : <div className="card tight"><div className="table-wrap"><table>
        <thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th><th>Candidate</th></tr></thead>
        <tbody>{list.map(a => (
          <tr key={a.id}><td className="small" style={{ whiteSpace: 'nowrap' }}>{fmtUtc(a.at)}</td><td>{a.user_name}</td><td>{a.action.replaceAll('_', ' ')}</td>
            <td className="small">{a.detail}</td><td>{a.candidate_id ? <a href={`/candidates/${a.candidate_id}`}>{a.candidate_name || 'Open'}</a> : ''}</td></tr>
        ))}{!list.length && <tr><td colSpan={5} className="empty">Nothing found.</td></tr>}</tbody>
      </table></div></div>}
    </div>
  )
}

function useSettings() {
  const { toast, refreshMeta } = useApp()
  const [s, setS] = useState(null)
  useEffect(() => { get('/api/settings').then(setS) }, [])
  const set = (k, v) => setS(x => ({ ...x, [k]: v }))
  const save = keys => put('/api/settings', Object.fromEntries(keys.map(k => [k, s[k]]))).then(r => { setS(r); refreshMeta(); toast('Saved') }, e => toast(e.message, 'bad'))
  return [s, set, save]
}
const bool = (s, set, k, label, hint) => <label className="check" style={{ alignItems: 'flex-start' }}><input type="checkbox" checked={s[k] === 'true'} onChange={e => set(k, e.target.checked ? 'true' : 'false')} /><span>{label}{hint && <div className="small muted">{hint}</div>}</span></label>

function AgingRules() {
  const { meta, toast } = useApp()
  const [s, set, save] = useSettings()
  const [result, setResult] = useState(null)
  if (!s) return <Loading />
  const keys = ['aging_enabled', 'aging_alert_days', 'aging_reject_days', 'aging_auto_reject', 'aging_recipients', 'aging_sender_email', 'aging_run_time',
    'aging_cc_department', 'aging_cc_last_contact', 'aging_reset_on_stage_change', 'aging_import_grace_days', 'aging_alert_mode']
  const runNow = async () => { try { setResult(await post('/api/aging/run')) } catch (e) { toast(e.message, 'bad') } }
  const counted = meta.stages.filter(x => x.aging_enabled).map(x => x.name).join(', ') || 'none'
  return (
    <div className="card col" style={{ maxWidth: 920 }}>
      {bool(s, set, 'aging_enabled', 'Track days since last contact', `Stages that count: ${counted}. Change this per stage under Pipeline stages.`)}
      <div className="grid3">
        <Field label="Alert after (days without contact)"><input type="number" min={1} value={s.aging_alert_days} onChange={e => set('aging_alert_days', e.target.value)} /></Field>
        <Field label="Reject automatically after (days)"><input type="number" min={1} value={s.aging_reject_days} onChange={e => set('aging_reject_days', e.target.value)} /></Field>
        <Field label="Daily check runs at"><input type="time" value={s.aging_run_time} onChange={e => set('aging_run_time', e.target.value)} /></Field>
        <Field label="Alert emails go to" className="span2"><input value={s.aging_recipients} onChange={e => set('aging_recipients', e.target.value)} /></Field>
        <Field label="Sent from this person's Outlook">
          <select value={s.aging_sender_email} onChange={e => set('aging_sender_email', e.target.value)}><option value="">Nobody (in-app alerts only)</option>
            {meta.users.map(u => <option key={u.id} value={u.email}>{u.name}</option>)}</select></Field>
        <Field label="Alert emails">
          <select value={s.aging_alert_mode} onChange={e => set('aging_alert_mode', e.target.value)}>
            <option value="daily">Every day, listing everyone over the limit</option><option value="new">Only when someone newly crosses the limit</option></select></Field>
        <Field label="Grace for imported candidates already past the limit (days)"><input type="number" min={0} value={s.aging_import_grace_days} onChange={e => set('aging_import_grace_days', e.target.value)} /></Field>
      </div>
      {bool(s, set, 'aging_auto_reject', 'Reject automatically on the last day', 'Moves the candidate to Rejected and sends the rejection email from the sender above. Candidates with a booked interview or marked Keep are never rejected.')}
      {bool(s, set, 'aging_cc_department', "CC the department's recruiters", 'The emails listed on each department in Settings > Departments.')}
      {bool(s, set, 'aging_cc_last_contact', 'CC whoever last contacted the candidate')}
      {bool(s, set, 'aging_reset_on_stage_change', 'Also restart the clock when a candidate moves to another stage', 'Off: only emails and invites from HireModus, or Mark as contacted, restart it.')}
      <div className="row between"><button onClick={runNow}>Run the daily check now</button><button className="primary" onClick={() => save(keys)}>Save aging rules</button></div>
      {result && <div className="alert ok">Done: {result.rejected.length} rejected{result.rejected.length ? ` (${result.rejected.map(r => r.name).join(', ')})` : ''}, {result.alerted} candidates in {result.alert_emails} alert email(s).{result.warnings.map(w => ' ' + w)}</div>}
    </div>
  )
}

function Notifications() {
  const [s, set, save] = useSettings()
  if (!s) return <Loading />
  return (
    <div className="card col" style={{ maxWidth: 820 }}>
      <h2>When a candidate submits a test</h2>
      {bool(s, set, 'notify_test_submitted_inapp', 'Show an alert in HireModus to people who can see test results')}
      <Field label="Also email these people (optional)" hint="Sent from the same Outlook as the aging alerts"><input value={s.notify_test_submitted_emails} onChange={e => set('notify_test_submitted_emails', e.target.value)} placeholder="name@novamodus.com" /></Field>
      <h2 style={{ marginTop: 10 }}>When candidates are rejected automatically</h2>
      <div className="small muted">An in-app alert always appears.</div>
      <Field label="Also email these people (optional)"><input value={s.notify_auto_rejected_emails} onChange={e => set('notify_auto_rejected_emails', e.target.value)} /></Field>
      <div className="row end"><button className="primary" onClick={() => save(['notify_test_submitted_inapp', 'notify_test_submitted_emails', 'notify_auto_rejected_emails'])}>Save</button></div>
    </div>
  )
}

function Branding() {
  const { toast, refreshMeta } = useApp()
  const [s, set, save] = useSettings()
  if (!s) return <Loading />
  const upload = async f => {
    const fd = new FormData(); fd.append('file', f)
    try { const r = await api('/api/branding/logo', { method: 'POST', form: fd }); set('brand_logo', r.brand_logo); refreshMeta(); toast('Logo uploaded') } catch (e) { toast(e.message, 'bad') }
  }
  const removeLogo = async () => { await del('/api/branding/logo'); set('brand_logo', ''); refreshMeta() }
  return (
    <div className="grid2" style={{ alignItems: 'start' }}>
      <div className="card col">
        <Field label="App name"><input value={s.brand_name} onChange={e => set('brand_name', e.target.value)} /></Field>
        <Field label="Line under the logo"><input value={s.brand_tagline} onChange={e => set('brand_tagline', e.target.value)} /></Field>
        <div className="grid2">
          <Field label="Main colour"><input type="color" style={{ height: 40, padding: 3 }} value={s.brand_color} onChange={e => set('brand_color', e.target.value)} /></Field>
          <Field label="Dark colour"><input type="color" style={{ height: 40, padding: 3 }} value={s.brand_navy} onChange={e => set('brand_navy', e.target.value)} /></Field>
        </div>
        <Field label="Logo image (optional, replaces the drawn logo)"><input type="file" accept=".png,.jpg,.jpeg,.svg,.webp" onChange={e => e.target.files[0] && upload(e.target.files[0])} /></Field>
        {s.brand_logo && <button className="sm danger" style={{ alignSelf: 'flex-start' }} onClick={removeLogo}>Remove uploaded logo</button>}
        <div className="row end"><button onClick={() => { ['brand_name', 'brand_tagline'].forEach(k => set(k, k === 'brand_name' ? 'HireModus' : 'BY NOVAMODUS')); set('brand_color', '#E5484D'); set('brand_navy', '#1B2A4A') }}>Reset to Novamodus</button>
          <button className="primary" onClick={() => save(['brand_name', 'brand_tagline', 'brand_color', 'brand_navy'])}>Save branding</button></div>
      </div>
      <div className="card col">
        <h3>Preview</h3>
        <div style={{ padding: 18, border: '1px solid var(--line)', borderRadius: 12 }}><Logo brand={s} height={48} /></div>
        <div style={{ padding: 18, borderRadius: 12, background: s.brand_navy }}><Logo brand={s} height={48} light /></div>
        <div className="small muted">Used on the sign-in page, the sidebar and the candidate test portal.</div>
      </div>
    </div>
  )
}

function Integrity() {
  const { toast } = useApp()
  const [s, setS] = useState(null)
  useEffect(() => { get('/api/settings').then(setS) }, [])
  if (!s) return <Loading />
  const set = (k, v) => setS(x => ({ ...x, [k]: v }))
  const on = k => s[k] === 'true'
  const save = () => put('/api/settings', {
    recording_quality: s.recording_quality, detect_enabled: s.detect_enabled, detect_phone: s.detect_phone,
    detect_warn_candidate: s.detect_warn_candidate, detect_looking_away_seconds: s.detect_looking_away_seconds, detect_no_face_seconds: s.detect_no_face_seconds,
  }).then(r => { setS(r); toast('Saved') }, e => toast(e.message, 'bad'))
  const Q = { high: ['High', 'Full HD at 10 frames a second. Text is sharp. Up to about 1.1 GB an hour.'], standard: ['Standard', '720p at 8 frames a second. Up to about 550 MB an hour.'], low: ['Low', '720p at 5 frames a second. For slow internet. Up to about 180 MB an hour.'] }
  return (
    <div className="col" style={{ maxWidth: 900 }}>
      <div className="card col">
        <h2 style={{ margin: 0 }}>Screen recording quality</h2>
        {Object.entries(Q).map(([k, [label, help]]) => (
          <label key={k} className="check"><input type="radio" checked={s.recording_quality === k} onChange={() => set('recording_quality', k)} /><b>{label}</b><span className="muted">{help}</span></label>))}
        <div className="small muted">Candidates must use Chrome or Edge, share their entire screen (a tab or window is refused) and use one monitor. Recordings are still deleted at midnight on the day of the test.</div>
      </div>
      <div className="card col">
        <h2 style={{ margin: 0 }}>Phone and distraction checks</h2>
        <div className="small muted">Runs in the candidate's browser on the camera feed during tests that record the camera. Nothing is decided automatically: each check adds a flag and a camera snapshot to the integrity log for the panel to review.</div>
        <label className="check"><input type="checkbox" checked={on('detect_enabled')} onChange={e => set('detect_enabled', String(e.target.checked))} /> Check for: nobody at the screen, more than one person, looking away</label>
        <label className="check"><input type="checkbox" disabled={!on('detect_enabled')} checked={on('detect_phone')} onChange={e => set('detect_phone', String(e.target.checked))} /> Also look for a phone in view</label>
        <label className="check"><input type="checkbox" disabled={!on('detect_enabled')} checked={on('detect_warn_candidate')} onChange={e => set('detect_warn_candidate', String(e.target.checked))} /> Show the candidate a warning when something is flagged</label>
        <div className="row">
          <Field label="Flag looking away after (seconds)"><input type="number" min={2} max={60} style={{ width: 110 }} value={s.detect_looking_away_seconds} onChange={e => set('detect_looking_away_seconds', e.target.value)} /></Field>
          <Field label="Flag nobody at the screen after (seconds)"><input type="number" min={2} max={60} style={{ width: 110 }} value={s.detect_no_face_seconds} onChange={e => set('detect_no_face_seconds', e.target.value)} /></Field>
        </div>
        <div className="small muted">Phone detection catches a phone the camera can see. It can't see one held below the desk, which is why looking down for a long time is flagged too.</div>
      </div>
      <div className="row end"><button className="primary" onClick={save}>Save</button></div>
    </div>
  )
}

/* ---------------------------------------------------------------- interview feedback form */

function FeedbackQuestions() {
  const { toast, refreshMeta } = useApp()
  const [qs, setQs] = useState(null)
  const [s, setS] = useState(null)
  const [edit, setEdit] = useState(null)
  const load = () => { get('/api/feedback/questions?all=true').then(setQs); get('/api/settings').then(setS) }
  useEffect(load, [])
  if (!qs || !s) return <Loading />
  const save = async () => {
    const body = { ...edit, options: edit.kind === 'choice' ? String(edit.optionsText || '').split(',').map(x => x.trim()).filter(Boolean) : [] }
    try { edit.id ? await put(`/api/feedback/questions/${edit.id}`, body) : await post('/api/feedback/questions', body); setEdit(null); load(); toast('Saved') }
    catch (e) { toast(e.message, 'bad') }
  }
  const toggle = v => put('/api/settings', { feedback_enabled: String(v) }).then(r => { setS(r); refreshMeta() })
  return (
    <div className="col" style={{ maxWidth: 900 }}>
      <div className="card col">
        <label className="check"><input type="checkbox" checked={s.feedback_enabled !== 'false'} onChange={e => toggle(e.target.checked)} /> <b>Offer a feedback form on interviews</b></label>
        <div className="small muted">Interviewers in the candidate's department can fill it in after an interview. It's always optional: nobody has to fill it in before moving a candidate on.</div>
      </div>
      <div className="card tight">
        <div className="row between" style={{ padding: '12px 14px' }}><h2 style={{ margin: 0 }}>Questions</h2><button className="primary sm" onClick={() => setEdit({ label: '', kind: 'text', optionsText: '', required: false, active: true, sort: qs.length + 1 })}>Add question</button></div>
        <table><thead><tr><th>#</th><th>Question</th><th>Type</th><th>Required on the form</th><th>Active</th><th /></tr></thead>
          <tbody>{qs.map(q => (
            <tr key={q.id}><td>{q.sort}</td><td>{q.label}</td><td>{{ rating: 'Rating 1 to 5', choice: 'Choice: ' + q.options.join(', '), text: 'Text' }[q.kind]}</td>
              <td>{q.required ? 'Yes' : 'No'}</td><td>{q.active ? 'Yes' : 'No'}</td>
              <td className="row end"><button className="sm" onClick={() => setEdit({ ...q, optionsText: q.options.join(', ') })}>Edit</button>
                <button className="sm danger" onClick={() => del(`/api/feedback/questions/${q.id}`).then(r => { load(); toast(r.hidden_instead ? 'Hidden: it has answers already' : 'Removed') })}>Remove</button></td></tr>))}</tbody></table>
      </div>
      {edit && <Modal title={edit.id ? 'Edit question' : 'Add question'} onClose={() => setEdit(null)} footer={<><button onClick={() => setEdit(null)}>Cancel</button><button className="primary" onClick={save}>Save</button></>}>
        <Field label="Question"><input value={edit.label} onChange={e => setEdit({ ...edit, label: e.target.value })} /></Field>
        <Field label="Type"><select value={edit.kind} onChange={e => setEdit({ ...edit, kind: e.target.value })}><option value="rating">Rating 1 to 5</option><option value="choice">Choice</option><option value="text">Text</option></select></Field>
        {edit.kind === 'choice' && <Field label="Options, separated by commas"><input value={edit.optionsText} onChange={e => setEdit({ ...edit, optionsText: e.target.value })} placeholder="Hire, Maybe, No hire" /></Field>}
        <Field label="Order"><input type="number" style={{ width: 90 }} value={edit.sort} onChange={e => setEdit({ ...edit, sort: +e.target.value })} /></Field>
        <label className="check"><input type="checkbox" checked={edit.required} onChange={e => setEdit({ ...edit, required: e.target.checked })} /> Must be answered when someone fills in the form</label>
        <label className="check"><input type="checkbox" checked={edit.active} onChange={e => setEdit({ ...edit, active: e.target.checked })} /> Active</label>
      </Modal>}
    </div>
  )
}

/* ---------------------------------------------------------------- email, replies and Microsoft 365 */

function Microsoft365() {
  const { toast, refreshMeta, me } = useApp()
  const [m, setM] = useState(null)
  const [s, setS] = useState(null)
  const [secret, setSecret] = useState('')
  const [steps, setSteps] = useState(null)
  const [mailbox, setMailbox] = useState(me.email)
  const [busy, setBusy] = useState(false)
  const load = () => { get('/api/microsoft/settings').then(setM); get('/api/settings').then(setS) }
  useEffect(load, [])
  if (!m || !s) return <Loading />
  const set = (k, v) => setM(x => ({ ...x, [k]: v }))
  const save = async (extra = {}) => {
    try {
      const r = await put('/api/microsoft/settings', { ms_tenant_id: m.ms_tenant_id, ms_client_id: m.ms_client_id, ms_public_url: m.ms_public_url,
        ms_signin_enabled: m.ms_signin_enabled, ms_password_signin: m.ms_password_signin, ms_graph_enabled: m.ms_graph_enabled,
        ms_default_transport: m.ms_default_transport, ms_client_secret: secret, ...extra })
      setM(r); setSecret(''); refreshMeta(); toast('Saved')
    } catch (e) { toast(e.message, 'bad'); load() }
  }
  const test = async () => {
    setBusy(true); setSteps(null)
    try { setSteps((await post('/api/microsoft/test', { mailbox })).steps) } catch (e) { toast(e.message, 'bad') } finally { setBusy(false) }
  }
  const saveReplies = v => put('/api/settings', v).then(r => { setS(r); toast('Saved') }, e => toast(e.message, 'bad'))
  const route = (u, v) => put(`/api/users/${u.id}/mail-transport`, { mail_transport: v }).then(load, e => toast(e.message, 'bad'))
  return (
    <div className="col" style={{ maxWidth: 980 }}>
      <div className="card col">
        <h2 style={{ margin: 0 }}>Candidate replies</h2>
        <label className="check"><input type="checkbox" checked={s.replies_enabled !== 'false'} onChange={e => saveReplies({ replies_enabled: String(e.target.checked) })} /> Pick up candidates' replies from recruiters' and CC people's inboxes</label>
        <div className="row"><Field label="On the first check, look back (days)"><input type="number" min={1} max={90} style={{ width: 100 }} value={s.replies_lookback_days} onChange={e => setS({ ...s, replies_lookback_days: e.target.value })} onBlur={() => saveReplies({ replies_lookback_days: s.replies_lookback_days })} /></Field></div>
        <div className="small muted">Every 5 minutes, each person's Outlook connector or Microsoft 365 mailbox is checked for emails from candidates they work with. Only those emails are copied into HireModus, with attachments up to 15 MB. A reply alerts the department, shows as New, and restarts the aging clock.</div>
      </div>

      <div className="card col">
        <div className="row between"><h2 style={{ margin: 0 }}>Microsoft 365 (Entra ID)</h2>{m.configured ? <span className="badge ok">Details saved</span> : <span className="badge">Not set up</span>}</div>
        <div className="small muted">IT registers HireModus as an app in Microsoft Entra ID and gives you these three values. Until both switches below are on, nothing changes for anyone.</div>
        <div className="grid2">
          <Field label="Directory (tenant) ID"><input className="mono" value={m.ms_tenant_id} onChange={e => set('ms_tenant_id', e.target.value)} placeholder="00000000-0000-0000-0000-000000000000" /></Field>
          <Field label="Application (client) ID"><input className="mono" value={m.ms_client_id} onChange={e => set('ms_client_id', e.target.value)} /></Field>
          <Field label="Client secret" hint={m.secret_set ? 'A secret is saved. It is never shown again; type a new one only to replace it.' : 'Paste the secret value (not the secret ID).'}><input type="password" value={secret} onChange={e => setSecret(e.target.value)} placeholder={m.secret_set ? '•••••••• saved' : ''} autoComplete="new-password" /></Field>
          <Field label="HireModus web address (optional)" hint="The https:// address people use to open HireModus. Leave empty to use the address you're on now."><input value={m.ms_public_url} onChange={e => set('ms_public_url', e.target.value)} placeholder="https://hiremodus.novamodus.com" /></Field>
        </div>
        <Field label="Redirect URI to register in Entra (Authentication > Web)"><input readOnly className="mono" value={m.redirect_uri} onFocus={e => e.target.select()} /></Field>
        {!m.redirect_is_https && <div className="alert warn">Microsoft only accepts https:// redirect addresses (or http://localhost). Until HireModus has an https address, Microsoft sign-in only works on the PC running HireModus. Email through Microsoft 365 works either way.</div>}
        <div className="row"><button className="primary" onClick={() => save()}>Save details</button>
          {m.secret_set && <button className="ghost" onClick={() => save({ clear_secret: true })}>Remove secret</button>}</div>
      </div>

      <div className="card col">
        <h2 style={{ margin: 0 }}>Check the connection</h2>
        <div className="row" style={{ alignItems: 'flex-end' }}><Field label="Mailbox to test"><input style={{ width: 300 }} value={mailbox} onChange={e => setMailbox(e.target.value)} /></Field>
          <button disabled={!m.configured || busy} onClick={test}>{busy ? 'Checking…' : 'Test connection'}</button></div>
        {steps && <ul className="steps" style={{ margin: 0, paddingLeft: 18 }}>{steps.map((x, i) => <li key={i} className={x.ok ? 'ok' : 'bad'}>{x.ok ? '✓' : '✕'} {x.step}{x.error && <div className="small muted">{x.error}</div>}</li>)}</ul>}
        <div className="small muted">This checks the app details and reading the mailbox and calendar. Sending isn't tested, so no email goes out.</div>
      </div>

      <div className="card col">
        <h2 style={{ margin: 0 }}>Sign in with Microsoft</h2>
        <label className="check"><input type="checkbox" disabled={!m.configured} checked={m.ms_signin_enabled === 'true'} onChange={e => set('ms_signin_enabled', String(e.target.checked))} /> Show "Sign in with Microsoft" on the sign-in page</label>
        <div className="row">
          <label className="check"><input type="radio" checked={m.ms_password_signin === 'everyone'} onChange={() => set('ms_password_signin', 'everyone')} /> Everyone can still use their HireModus password</label>
          <label className="check"><input type="radio" checked={m.ms_password_signin === 'admins'} onChange={() => set('ms_password_signin', 'admins')} /> Only admins can use a password (as a backup)</label>
        </div>
        <div className="small muted">Only people already added in Settings > Users get in, matched by email. Their roles and departments still come from HireModus.</div>
        <div><button className="primary" onClick={() => save()}>Save</button></div>
      </div>

      <div className="card col">
        <h2 style={{ margin: 0 }}>Email and invites through Microsoft 365</h2>
        <label className="check"><input type="checkbox" disabled={!m.configured} checked={m.ms_graph_enabled === 'true'} onChange={e => set('ms_graph_enabled', String(e.target.checked))} /> Allow sending email, invites and checking replies through Microsoft 365</label>
        <div className="row">
          <span className="small">Default for everyone:</span>
          <label className="check"><input type="radio" checked={m.ms_default_transport === 'connector'} onChange={() => set('ms_default_transport', 'connector')} /> Outlook connector</label>
          <label className="check"><input type="radio" checked={m.ms_default_transport === 'graph'} onChange={() => set('ms_default_transport', 'graph')} /> Microsoft 365</label>
        </div>
        <div><button className="primary" onClick={() => save()}>Save</button></div>
        {m.ms_graph_enabled === 'true' && <table><thead><tr><th>Person</th><th>Setting</th><th>Uses now</th><th>Signed in with Microsoft</th></tr></thead>
          <tbody>{m.users.map(u => (
            <tr key={u.id}><td>{u.name}<div className="small muted">{u.email}</div></td>
              <td><select value={u.mail_transport} onChange={e => route(u, e.target.value)}><option value="default">Company default</option><option value="graph">Microsoft 365</option><option value="connector">Outlook connector</option></select></td>
              <td>{u.uses === 'graph' ? <span className="badge info">Microsoft 365</span> : <span className="badge">Connector</span>}</td>
              <td>{u.signed_in_with_microsoft ? 'Yes' : <span className="muted">Not yet</span>}</td></tr>))}</tbody></table>}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- clearing out old candidate data */

function Retention() {
  const { toast, refreshMeta, can } = useApp()
  const [r, setR] = useState(null)
  const [s, setS] = useState(null)
  const [confirm, setConfirm] = useState(false)
  const load = () => { get('/api/retention').then(setR); if (can('settings.manage')) get('/api/settings').then(setS) }
  useEffect(load, []) // eslint-disable-line
  if (!r) return <Loading />
  const save = v => put('/api/settings', v).then(x => { setS(x); refreshMeta(); load(); toast('Saved') }, e => toast(e.message, 'bad'))
  const keep = (id, k) => put(`/api/candidates/${id}/retention-keep`, { keep: k }).then(() => { load(); toast(k ? 'Will be kept' : 'Removed from the keep list') })
  return (
    <div className="col" style={{ maxWidth: 980 }}>
      <div className="card col">
        <h2 style={{ margin: 0 }}>Remove personal details of old candidates</h2>
        <div className="small muted">Rejected and Withdrawn candidates have their name, contact details, notes, custom fields, emails and replies, attachments, test answers, interview feedback and files removed a set time after they reached that stage. Department, stage, dates, position and source stay, so counts and reports keep working. The candidate shows as "Removed candidate #123". This can't be undone.</div>
        {s && <>
          <label className="check"><input type="checkbox" checked={s.retention_enabled === 'true'} onChange={e => e.target.checked ? setConfirm(true) : save({ retention_enabled: 'false' })} /> <b>Turn on automatic clear-out</b></label>
          <div className="row">
            <Field label="Remove details after (months)"><input type="number" min={1} max={120} style={{ width: 100 }} value={s.retention_months} onChange={e => setS({ ...s, retention_months: e.target.value })} onBlur={() => save({ retention_months: s.retention_months })} /></Field>
            <Field label="Warn admins first (days before)"><input type="number" min={1} max={90} style={{ width: 100 }} value={s.retention_warn_days} onChange={e => setS({ ...s, retention_warn_days: e.target.value })} onBlur={() => save({ retention_warn_days: s.retention_warn_days })} /></Field>
          </div>
        </>}
        <div className="small">{r.enabled ? <>On: details are removed <b>{r.months} months</b> after rejection or withdrawal, and admins are warned <b>{r.warn_days} days</b> before.</> : 'Off: nothing is removed.'} {r.cleared_total} candidate{r.cleared_total !== 1 ? 's have' : ' has'} been cleared so far.</div>
      </div>
      <div className="card tight">
        <div style={{ padding: '12px 14px' }}><h2 style={{ margin: 0 }}>Coming up in the next 60 days</h2><div className="small muted">Tick Keep for anyone whose details you need to hold on to, for example someone you may hire later.</div></div>
        {!r.upcoming.length ? <div className="muted" style={{ padding: '0 14px 14px' }}>Nobody.</div>
          : <table><thead><tr><th>Candidate</th><th>Stage</th><th>Department</th><th>Since</th><th>Details removed on</th><th>Keep</th></tr></thead>
            <tbody>{r.upcoming.map(c => (
              <tr key={c.id}><td><Link to={`/candidates/${c.id}`}>{c.name}</Link></td><td>{c.stage}</td><td>{c.department || <span className="muted">None</span>}</td>
                <td>{c.since ? fmtUtc(c.since).split(',')[0] : ''}</td><td>{c.clears_on}{!c.warned && <span className="small muted"> (after the warning)</span>}</td>
                <td><input type="checkbox" onChange={() => keep(c.id, true)} /></td></tr>))}</tbody></table>}
      </div>
      {r.kept.length > 0 && <div className="card tight">
        <div style={{ padding: '12px 14px' }}><h2 style={{ margin: 0 }}>Kept</h2></div>
        <table><tbody>{r.kept.map(c => <tr key={c.id}><td><Link to={`/candidates/${c.id}`}>{c.name}</Link></td><td>{c.stage}</td><td className="row end"><button className="sm" onClick={() => keep(c.id, false)}>Stop keeping</button></td></tr>)}</tbody></table>
      </div>}
      {confirm && <Confirm title="Turn on automatic clear-out?" danger confirmLabel="Turn on" onClose={() => setConfirm(false)}
        message={`Rejected and withdrawn candidates older than ${s.retention_months} months will lose their personal details for good. Admins get a warning ${s.retention_warn_days} days before each batch, and you can tick Keep on anyone in that time.`}
        onConfirm={() => { setConfirm(false); save({ retention_enabled: 'true' }) }} />}
    </div>
  )
}
