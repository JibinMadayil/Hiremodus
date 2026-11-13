import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get, post, fmtUtc } from '../api'
import { useApp, Modal, JobBadge, Loading, EmailList } from '../ui'

const KIND = { send_mail: 'Email', create_appointment: 'Calendar invite', update_appointment: 'Invite update', cancel_appointment: 'Invite cancellation' }

export default function Outbox() {
  const { me, toast, can } = useApp()
  const [status, setStatus] = useState('')
  const [all, setAll] = useState(false)
  const [list, setList] = useState(null)
  const [open, setOpen] = useState(null)
  const load = () => get(`/api/jobs?status=${status}&mine=${!all}`).then(setList)
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t) }, [status, all]) // eslint-disable-line
  const act = (j, what) => post(`/api/jobs/${j.id}/${what}`).then(() => { toast(what === 'retry' ? 'Queued again' : 'Cancelled'); load() }, e => toast(e.message, 'bad'))
  return (
    <div className="col">
      <div className="page-head"><div><h1>Outbox</h1><div className="muted">Every email and invite HireModus asked your Outlook to send, and what happened.</div></div>
        <div className="row">
          <select value={status} onChange={e => setStatus(e.target.value)}><option value="">All</option><option value="queued,claimed">Waiting</option><option value="failed">Failed</option><option value="done">Done</option></select>
          {can('outbox.view_all') && <label className="check"><input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} /> Everyone's</label>}
        </div></div>
      {!me.connector_online && <div className="alert warn">Your Outlook Connector is offline. Waiting items go out as soon as it starts. <Link to="/outlook">My Outlook</Link></div>}
      {!list ? <Loading /> : (
        <div className="card tight"><div className="table-wrap"><table>
          <thead><tr><th>When</th><th>Type</th><th>What</th>{all && <th>From</th>}<th>Status</th><th></th></tr></thead>
          <tbody>{list.map(j => (
            <tr key={j.id} className="click" onClick={() => get(`/api/jobs/${j.id}`).then(setOpen)}>
              <td className="small">{fmtUtc(j.created_at)}</td><td>{KIND[j.kind] || j.kind}</td>
              <td>{j.description}{j.error && <div className="small" style={{ color: 'var(--bad)' }}>{j.error}</div>}</td>
              {all && <td className="small">{j.owner_name}</td>}
              <td><JobBadge status={j.status} /></td>
              <td onClick={e => e.stopPropagation()} className="row end">
                {['failed', 'cancelled'].includes(j.status) && <button className="sm" onClick={() => act(j, 'retry')}>Retry</button>}
                {j.status === 'queued' && <button className="sm danger" onClick={() => act(j, 'cancel')}>Cancel</button>}
                {j.candidate_id && <Link className="btn sm" to={`/candidates/${j.candidate_id}`}>Candidate</Link>}
              </td>
            </tr>
          ))}{!list.length && <tr><td colSpan={6} className="empty">Nothing here.</td></tr>}</tbody>
        </table></div></div>
      )}
      {open && <Modal wide title={KIND[open.kind] || open.kind} onClose={() => setOpen(null)}>
        <div className="row"><JobBadge status={open.status} />{open.error && <span style={{ color: 'var(--bad)' }}>{open.error}</span>}</div>
        {open.kind === 'send_mail' && <div className="kv"><div>To</div><EmailList value={open.payload.to} /><div>CC</div><EmailList value={open.payload.cc} /><div>Subject</div><div>{open.payload.subject}</div></div>}
        {open.kind === 'create_appointment' && <div className="kv"><div>When</div><div>{open.payload.start} → {open.payload.end}</div><div>Required</div><EmailList value={open.payload.required} /><div>Optional</div><EmailList value={open.payload.optional} /><div>Location</div><div>{open.payload.location}</div><div>Subject</div><div>{open.payload.subject}</div></div>}
        {open.kind === 'update_appointment' && <div className="kv"><div>New time</div><div>{open.payload.start}</div></div>}
        {open.payload.body && <div className="card pre">{open.payload.body}</div>}
      </Modal>}
    </div>
  )
}
