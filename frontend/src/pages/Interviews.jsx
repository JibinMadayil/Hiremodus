import { useState } from 'react'
import { Link } from 'react-router-dom'
import { get, fmtDate } from '../api'
import { useApp, useAsync, Loading, ErrorBox, DeptBadge } from '../ui'

export default function Interviews() {
  const { meta } = useApp()
  const [ahead, setAhead] = useState(30)
  const [back, setBack] = useState(1)
  const [dept, setDept] = useState('')
  const [{ data, loading, error }] = useAsync(() => get(`/api/interviews?days_ahead=${ahead}&days_back=${back}`), [ahead, back])
  const list = (data || []).filter(i => !dept || String(i.candidate_department_id) === dept)
  const byDay = {}
  list.forEach(i => { const k = i.start.slice(0, 10); (byDay[k] = byDay[k] || []).push(i) })
  return (
    <div className="col">
      <div className="page-head"><div><h1>Interviews</h1><div className="muted">Everything booked through HireModus or imported from Excel.</div></div>
        <div className="row">
          <select value={back} onChange={e => setBack(+e.target.value)}><option value={1}>From today</option><option value={14}>Include last 2 weeks</option><option value={90}>Include last 3 months</option></select>
          <select value={ahead} onChange={e => setAhead(+e.target.value)}><option value={7}>Next 7 days</option><option value={30}>Next 30 days</option><option value={90}>Next 90 days</option></select>
          <select value={dept} onChange={e => setDept(e.target.value)}><option value="">All departments</option>{meta.departments.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
        </div>
      </div>
      {loading ? <Loading /> : <ErrorBox error={error} />}
      {!loading && !list.length && <div className="card empty">No interviews in this range.</div>}
      {Object.entries(byDay).map(([day, items]) => (
        <div key={day} className="card">
          <h2>{fmtDate(day + 'T12:00', false)}</h2>
          <table><tbody>{items.map(i => (
            <tr key={i.id}>
              <td style={{ width: 110 }}><b>{new Date(i.start).toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit' })}</b></td>
              <td><Link to={`/candidates/${i.candidate_id}`}>{i.candidate_name}</Link><div className="small muted">{i.title}</div></td>
              <td><DeptBadge id={i.candidate_department_id} /></td>
              <td className="small muted">{i.location}</td>
              <td>{i.status === 'cancelled' ? <span className="badge bad">Cancelled</span> : i.status === 'scheduled' ? <span className="badge ok">In Outlook</span> : <span className="badge warn">{i.status}</span>}</td>
            </tr>
          ))}</tbody></table>
        </div>
      ))}
    </div>
  )
}
