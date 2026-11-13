import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get, put, fmtDate, fmtUtc } from '../api'
import { useApp, Modal, Loading, ErrorBox } from '../ui'
import Icon from '../icons'

const TILES = {
  active: { label: 'Active candidates', icon: 'users', tone: 'navy', to: '/candidates' },
  over30: { label: 'No contact 30+ days', icon: 'alert', tone: 'warn', to: '/candidates?aging=over' },
  due7: { label: 'Auto-reject in 7 days', icon: 'clock', tone: 'bad', to: '/candidates?aging=due' },
  autorej: { label: 'Auto-rejected this month', icon: 'x', tone: '', to: '/settings?tab=audit' },
  interviews7: { label: 'Interviews next 7 days', icon: 'calendar', tone: 'ok', to: '/interviews' },
  tograde: { label: 'Tests to grade', icon: 'clipboard', tone: '', to: '/tests' },
  live: { label: 'Tests in progress', icon: 'clock', tone: 'navy', to: '/tests' },
  outbox_wait: { label: 'Waiting on Outlook', icon: 'inbox', tone: 'navy', to: '/outbox' },
  outbox_failed: { label: 'Failed sends', icon: 'alert', tone: 'bad', to: '/outbox' },
  replies: { label: 'New candidate replies', icon: 'reply', tone: 'navy', to: '/candidates?unread=1&all=1' },
  hired: { label: 'Hired', icon: 'star', tone: 'ok', to: '/candidates' },
}
const DEFAULT_TILES = ['active', 'replies', 'over30', 'due7', 'interviews7', 'tograde', 'live', 'outbox_failed']
const BUCKET_COLORS = ['#22C55E', '#60A5FA', '#F59E0B', '#EF4444']

export default function Dashboard() {
  const { meta, me, can, toast } = useApp()
  const [d, setD] = useState(null)
  const [aging, setAging] = useState(null)
  const [tiles, setTiles] = useState(null)
  const [edit, setEdit] = useState(false)
  const [error, setError] = useState(null)
  const myDepts = meta.departments.filter(x => x.active !== false && (me.scope_ids == null || me.scope_ids.includes(x.id)))
  const [dept, setDept] = useState(() => { try { return localStorage.getItem('hm_dash_dept') || '' } catch { return '' } })
  const pickDept = v => { setDept(v); try { localStorage.setItem('hm_dash_dept', v) } catch { /* private window */ } }
  useEffect(() => {
    const q = dept && myDepts.some(x => String(x.id) === dept) ? `?department_id=${dept}` : ''
    setD(null); setAging(null)
    Promise.all([get('/api/dashboard' + q), get('/api/aging' + q), get('/api/me/prefs')])
      .then(([a, b, p]) => { setD(a); setAging(b); setTiles(p.dashboard_tiles || DEFAULT_TILES) }, setError)
  }, [dept]) // eslint-disable-line
  if (error) return <ErrorBox error={error} />
  if (!d || !aging) return <Loading />
  const open = meta.stages.filter(s => s.kind === 'open').map(s => s.id)
  const hiredIds = meta.stages.filter(s => s.kind === 'hired').map(s => s.id)
  const values = {
    active: open.reduce((n, id) => n + (d.by_stage[id] || 0), 0),
    over30: aging.over_total, due7: aging.due_soon_total, autorej: aging.auto_rejected_month,
    interviews7: d.upcoming.filter(i => i.status !== 'cancelled').length,
    tograde: d.tests_to_grade, live: d.tests_live, outbox_wait: d.outbox_waiting, outbox_failed: d.outbox_failed,
    hired: hiredIds.reduce((n, id) => n + (d.by_stage[id] || 0), 0),
    replies: d.unread_replies || 0,
  }
  const deptName = myDepts.find(x => String(x.id) === dept)?.name
  const saveTiles = async list => { setTiles(list); await put('/api/me/prefs', { dashboard_tiles: list }); toast('Dashboard saved') }
  const sim = meta.settings.simulate_outlook === 'true'
  const maxStage = Math.max(1, ...meta.stages.map(s => d.by_stage[s.id] || 0))
  const hour = new Date().getHours()
  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="card hero">
        <div>
          <h1>Good {hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening'}, {me.name.split(' ')[0]}</h1>
          <div className="muted">{values.over30 ? `${values.over30} candidate${values.over30 > 1 ? 's have' : ' has'} had no contact for ${aging.alert_days}+ days.` : 'Every candidate has been contacted recently.'}
            {values.due7 ? ` ${values.due7} will be rejected automatically within a week.` : ''}</div>
        </div>
        <div className="row">
          {can('candidates.edit') && <Link className="btn primary" to="/candidates?new=1"><Icon name="plus" />Add candidate</Link>}
          <button className="sm" style={{ background: 'rgba(255,255,255,.12)', color: '#fff', borderColor: 'rgba(255,255,255,.25)' }} onClick={() => setEdit(true)}><Icon name="sliders" size={15} />Customize</button>
        </div>
      </div>

      {myDepts.length > 0 && !me.associate && <div className="seg dept-seg">
        <button className={!dept ? 'on' : ''} onClick={() => pickDept('')}>{me.scope_ids == null ? 'All departments' : 'All my departments'}</button>
        {myDepts.map(x => <button key={x.id} className={dept === String(x.id) ? 'on' : ''} onClick={() => pickDept(String(x.id))}>{x.name}</button>)}
      </div>}

      {sim && <div className="alert warn">Outlook simulation is on: emails and invites are recorded in the Outbox but not sent. An admin can turn this off in Settings once Outlook connectors are running.</div>}

      {d.replies?.length > 0 && <div className="card col" style={{ gap: 8 }}>
        <div className="card-title"><h2>New replies from candidates{deptName ? ` · ${deptName}` : ''}</h2><span className="badge brand">{d.unread_replies}</span></div>
        {d.replies.map(r => (
          <Link key={r.id} to={`/candidates/${r.candidate_id}`} className="row between" style={{ padding: '8px 0', borderTop: '1px solid var(--line)', color: 'inherit', flexWrap: 'nowrap' }}>
            <span style={{ minWidth: 0 }}><b>{r.candidate_name}</b> <span className="muted">{r.subject}</span><div className="small muted reply-preview" style={{ WebkitLineClamp: 1 }}>{r.preview}</div></span>
            <span className="small muted" style={{ whiteSpace: 'nowrap' }}>{fmtUtc(r.received_at)}</span>
          </Link>))}
        {d.unread_replies > d.replies.length && <Link className="small" to="/candidates?unread=1&all=1">See all {d.unread_replies}</Link>}
      </div>}

      {d.transfers?.length > 0 && <div className="card col" style={{ gap: 8 }}>
        <div className="card-title"><h2>Transfers waiting for {me.scope_ids == null ? 'a decision' : 'you'}</h2><span className="badge warn">{d.transfers.length}</span></div>
        {d.transfers.map(t => (
          <Link key={t.id} to={`/candidates/${t.candidate_id}`} className="row between" style={{ padding: '8px 0', borderTop: '1px solid var(--line)', color: 'inherit' }}>
            <span><b>{t.candidate_name}</b> <span className="muted">{t.from} → {t.to}</span><div className="small muted">“{t.note}”</div></span>
            <span className="small muted">{fmtUtc(t.requested_at)}</span>
          </Link>))}
      </div>}

      <div className="grid4">
        {tiles.filter(k => TILES[k]).map(k => (
          <Link key={k} to={TILES[k].to} className="card tile">
            <span className={'ico ' + TILES[k].tone}><Icon name={TILES[k].icon} size={20} /></span>
            <div><div className="n">{values[k]}</div><div className="l">{TILES[k].label}</div></div>
          </Link>
        ))}
      </div>

      <div className="grid2" style={{ alignItems: 'start' }}>
        <div className="card">
          <div className="card-title"><h2>Days since last contact, by area</h2>{!aging.enabled && <span className="badge">Aging rules off</span>}</div>
          {!aging.areas.length && <div className="muted">No candidates in stages that count.</div>}
          <div className="bars">
            {aging.areas.map(a => {
              const total = a.buckets.reduce((x, y) => x + y, 0) || 1
              return (
                <div key={a.area} className="bar-row">
                  <span>{a.area}</span>
                  <div className="track">{a.buckets.map((n, i) => n ? <span key={i} title={`${n}`} style={{ width: `${(n / total) * 100}%`, background: BUCKET_COLORS[i] }} /> : null)}</div>
                  <span className="small" style={{ textAlign: 'right' }}>{a.over ? <b style={{ color: 'var(--warn)' }}>{a.over}</b> : <span className="muted">0</span>}</span>
                </div>
              )
            })}
          </div>
          <div className="legend">
            <span><i style={{ background: BUCKET_COLORS[0] }} />0–15 days</span>
            <span><i style={{ background: BUCKET_COLORS[1] }} />16–{aging.alert_days - 1}</span>
            <span><i style={{ background: BUCKET_COLORS[2] }} />{aging.alert_days}–{aging.reject_days - 1}</span>
            <span><i style={{ background: BUCKET_COLORS[3] }} />{aging.reject_days}+ (grace)</span>
            <span style={{ marginLeft: 'auto' }}>Number on the right: over {aging.alert_days} days</span>
          </div>
        </div>

        <div className="card">
          <div className="card-title"><h2>Pipeline</h2><Link to="/candidates?layout=board" className="small">Open board</Link></div>
          <div className="bars">
            {meta.stages.filter(s => s.active).map(s => (
              <Link key={s.id} to={`/candidates?stage=${s.id}`} className="bar-row" style={{ color: 'inherit', textDecoration: 'none' }}>
                <span>{s.name}</span>
                <div className="track"><span style={{ width: `${((d.by_stage[s.id] || 0) / maxStage) * 100}%`, background: s.color }} /></div>
                <span style={{ textAlign: 'right', fontWeight: 650 }}>{d.by_stage[s.id] || 0}</span>
              </Link>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title"><h2>Interviews in the next 7 days</h2><Link to="/interviews" className="small">All interviews</Link></div>
        {!d.upcoming.length && <div className="muted">Nothing booked.</div>}
        <table><tbody>
          {d.upcoming.map(i => (
            <tr key={i.id}>
              <td style={{ width: 230 }}><b>{fmtDate(i.start)}</b></td>
              <td><Link to={`/candidates/${i.candidate_id}`}>{i.candidate_name}</Link></td>
              <td className="muted">{i.title.split(' - ')[0]}</td>
              <td style={{ textAlign: 'right' }}>{i.status === 'cancelled' ? <span className="badge bad">Cancelled</span> : i.status === 'scheduled' ? <span className="badge ok">In Outlook</span> : <span className="badge warn">Sending</span>}</td>
            </tr>
          ))}
        </tbody></table>
      </div>

      {edit && <TilePicker value={tiles} onClose={() => setEdit(false)} onSave={l => { saveTiles(l); setEdit(false) }} />}
    </div>
  )
}

function TilePicker({ value, onClose, onSave }) {
  const [list, setList] = useState(value)
  const toggle = k => setList(l => l.includes(k) ? l.filter(x => x !== k) : [...l, k])
  const move = (k, dlt) => setList(l => { const i = l.indexOf(k); const n = [...l]; n.splice(i, 1); n.splice(Math.max(0, Math.min(n.length, i + dlt)), 0, k); return n })
  return (
    <Modal title="Customize your dashboard" onClose={onClose} footer={<><button onClick={() => setList(DEFAULT_TILES)}>Reset</button><button onClick={onClose}>Cancel</button><button className="primary" onClick={() => onSave(list)}>Save</button></>}>
      <div className="muted small">Tick the numbers you want to see and put them in order. This only changes your own dashboard.</div>
      {[...list, ...Object.keys(TILES).filter(k => !list.includes(k))].map(k => (
        <div key={k} className="row between" style={{ borderBottom: '1px solid var(--line)', paddingBottom: 8 }}>
          <label className="check"><input type="checkbox" checked={list.includes(k)} onChange={() => toggle(k)} /><Icon name={TILES[k].icon} size={16} />{TILES[k].label}</label>
          {list.includes(k) && <div className="row"><button className="sm" onClick={() => move(k, -1)}>↑</button><button className="sm" onClick={() => move(k, 1)}>↓</button></div>}
        </div>
      ))}
    </Modal>
  )
}
