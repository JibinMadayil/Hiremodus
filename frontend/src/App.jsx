import { useCallback, useEffect, useRef, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate, Link } from 'react-router-dom'
import { auth, get, post, setUnauthorizedHandler, fullName, fmtUtc } from './api'
import { AppCtx, Field, Modal, useToasts, StageBadge } from './ui'
import { Logo, applyBrand, usePublicBrand, DEFAULT_BRAND } from './brand'
import Icon from './icons'
import Portal from './pages/Portal'
import Dashboard from './pages/Dashboard'
import Candidates from './pages/Candidates'
import CandidateDetail from './pages/CandidateDetail'
import Interviews from './pages/Interviews'
import Tests from './pages/Tests'
import TestEditor from './pages/TestEditor'
import AssignmentView from './pages/AssignmentView'
import Outbox from './pages/Outbox'
import ImportPage from './pages/Import'
import Settings from './pages/Settings'
import MyOutlook from './pages/MyOutlook'

export default function App() {
  const loc = useLocation()
  if (loc.pathname.startsWith('/portal')) return <Portal />
  return <StaffApp />
}

function StaffApp() {
  const [meta, setMeta] = useState(null)
  const [needLogin, setNeedLogin] = useState(!auth.token)
  const [toast, toasts] = useToasts()

  const refreshMeta = useCallback(() => get('/api/meta').then(m => { setMeta(m); applyBrand({ ...DEFAULT_BRAND, ...m.settings }) }), [])
  useEffect(() => {
    setUnauthorizedHandler(() => { auth.set(null); setMeta(null); setNeedLogin(true) })
    if (auth.token) refreshMeta().catch(() => setNeedLogin(true))
  }, [refreshMeta])

  if (needLogin) return <Login onDone={() => { setNeedLogin(false); refreshMeta() }} />
  if (!meta) return <div className="empty">Loading…</div>
  const me = meta.me
  const can = p => me.permissions.includes(p)
  const brand = { ...DEFAULT_BRAND, ...meta.settings }
  const logout = () => { auth.set(null); setMeta(null); setNeedLogin(true) }
  return (
    <AppCtx.Provider value={{ meta, refreshMeta, toast, me, can, brand }}>
      <div className="shell">
        <Sidebar can={can} me={me} brand={brand} />
        <div style={{ minWidth: 0 }}>
          <Topbar me={me} can={can} onLogout={logout} />
          <main className="main">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/candidates" element={<Candidates />} />
              <Route path="/candidates/:id" element={<CandidateDetail />} />
              <Route path="/interviews" element={<Interviews />} />
              <Route path="/tests" element={<Tests />} />
              <Route path="/tests/new" element={<TestEditor />} />
              <Route path="/tests/:id" element={<TestEditor />} />
              <Route path="/results/:id" element={<AssignmentView />} />
              <Route path="/outbox" element={<Outbox />} />
              <Route path="/import" element={<ImportPage />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/outlook" element={<MyOutlook />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </main>
        </div>
      </div>
      {me.must_change_password && <ChangePassword onDone={refreshMeta} />}
      {toasts}
    </AppCtx.Provider>
  )
}

function Nav({ to, icon, children, end, count }) {
  return <NavLink to={to} end={end} className={({ isActive }) => 'nav' + (isActive ? ' active' : '')}><Icon name={icon} />{children}{count > 0 && <span className="count">{count}</span>}</NavLink>
}

function Sidebar({ can, me, brand }) {
  const settingsAccess = can('settings.manage') || can('users.manage') || can('audit.view')
  const testsAccess = can('tests.papers') || can('tests.results') || can('tests.start_code')
  return (
    <aside className="side">
      <div className="logo-wrap"><Link to="/"><Logo brand={brand} height={42} /></Link></div>
      <div className="nav-label">Hiring</div>
      <Nav to="/" end icon="home">Dashboard</Nav>
      <Nav to="/candidates" icon="users">Candidates</Nav>
      <Nav to="/interviews" icon="calendar">Interviews</Nav>
      {testsAccess && <Nav to="/tests" icon="clipboard">Tests</Nav>}
      {(can('emails.send') || can('import.run')) && <div className="nav-label">Tools</div>}
      {can('emails.send') && <Nav to="/outbox" icon="inbox">Outbox</Nav>}
      {can('import.run') && <Nav to="/import" icon="upload">Import from Excel</Nav>}
      {can('emails.send') && <Nav to="/outlook" icon="mail">My Outlook</Nav>}
      {settingsAccess && <Nav to="/settings" icon="settings">Settings</Nav>}
      <div className="spacer" />
      {can('emails.send') && !me.connector_online && (
        <div className="help"><b>Outlook connector offline</b>Emails and invites wait in your Outbox until it's running. <Link to="/outlook" style={{ color: '#fff', textDecoration: 'underline' }}>Set it up</Link></div>
      )}
    </aside>
  )
}

function useOutside(ref, close) {
  useEffect(() => {
    const h = e => { if (ref.current && !ref.current.contains(e.target)) close() }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [ref, close])
}

function Topbar({ me, can, onLogout }) {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const [openN, setOpenN] = useState(false)
  const [openMe, setOpenMe] = useState(false)
  const [notes, setNotes] = useState({ items: [], unread: 0 })
  const sRef = useRef(null), nRef = useRef(null), mRef = useRef(null)
  useOutside(sRef, useCallback(() => setHits([]), []))
  useOutside(nRef, useCallback(() => setOpenN(false), []))
  useOutside(mRef, useCallback(() => setOpenMe(false), []))
  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return }
    let stale = false
    const t = setTimeout(() => get('/api/candidates/search?q=' + encodeURIComponent(q.trim())).then(r => { if (!stale) setHits(r) }).catch(() => {}), 150)
    return () => { stale = true; clearTimeout(t) }
  }, [q])
  const loadNotes = useCallback(() => get('/api/notifications').then(setNotes).catch(() => {}), [])
  useEffect(() => { loadNotes(); const t = setInterval(loadNotes, 60000); return () => clearInterval(t) }, [loadNotes])
  const openBell = () => { setOpenN(o => !o); if (notes.unread) post('/api/notifications/read-all').then(loadNotes) }
  const initials = me.name.split(' ').map(x => x[0]).slice(0, 2).join('').toUpperCase()
  return (
    <div className="topbar">
      <div className="search" ref={sRef}>
        <span className="ic"><Icon name="search" /></span>
        <input placeholder="Search candidates by name, email or phone" value={q} onChange={e => setQ(e.target.value)} />
        {hits.length > 0 && <div className="results">{hits.map(c => (
          <a key={c.id} href={`/candidates/${c.id}`} onClick={e => { e.preventDefault(); setQ(''); setHits([]); nav(`/candidates/${c.id}`) }}>
            <span><b>{fullName(c)}</b> <span className="muted small">{c.access === 'summary' ? 'Other department, read-only' : c.email}</span></span>
            <StageBadge id={c.stage_id} />
          </a>))}</div>}
      </div>
      <div style={{ flex: 1 }} />
      <div ref={nRef} style={{ position: 'relative' }}>
        <button className="iconbtn" onClick={openBell} aria-label="Alerts"><Icon name="bell" />{notes.unread > 0 && <span className="dotn">{notes.unread}</span>}</button>
        {openN && <div className="menu notif">
          <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--line)' }}><b>Alerts</b></div>
          {!notes.items.length && <div className="empty">Nothing yet.</div>}
          {notes.items.map(n => (
            <a key={n.id} className={'n' + (n.read ? '' : ' unread')} href={n.link || '#'} onClick={e => { e.preventDefault(); setOpenN(false); if (n.link) nav(n.link) }}>
              <div style={{ fontWeight: 600 }}>{n.title}</div>
              {n.body && <div className="small muted pre" style={{ maxHeight: 60, overflow: 'hidden' }}>{n.body}</div>}
              <div className="small muted">{fmtUtc(n.at)}</div>
            </a>))}
        </div>}
      </div>
      <div ref={mRef} className="me-chip" onClick={() => setOpenMe(o => !o)}>
        <span className="avatar">{initials}</span>
        <div style={{ lineHeight: 1.2 }}><div style={{ fontWeight: 600, fontSize: 13 }}>{me.name}</div><div className="small muted">{me.roles.join(' + ')}</div></div>
        {openMe && <div className="menu" onClick={e => e.stopPropagation()}>
          <div className="item" style={{ cursor: 'default' }}><span className="small muted">{me.email}</span></div>
          {can('emails.send') && <Link className="item" to="/outlook" onClick={() => setOpenMe(false)}><Icon name="mail" />My Outlook</Link>}
          <div className="item" onClick={onLogout}><Icon name="logout" />Sign out</div>
        </div>}
      </div>
    </div>
  )
}

/* Microsoft sign-in comes back to /#ms_token=... or /#ms_error=... */
let msError = ''
{
  const h = new URLSearchParams(window.location.hash.slice(1))
  if (h.get('ms_token')) auth.set(h.get('ms_token'))
  if (h.get('ms_error')) msError = h.get('ms_error')
  if (h.get('ms_token') || h.get('ms_error')) window.history.replaceState(null, '', window.location.pathname + window.location.search)
}

function Login({ onDone }) {
  const brand = usePublicBrand()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState(msError)
  const [opts, setOpts] = useState({ microsoft: false, password: 'everyone' })
  useEffect(() => { get('/api/auth/options', { token: null }).then(setOpts).catch(() => {}); msError = '' }, [])
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()
  const submit = async e => {
    e.preventDefault()
    setBusy(true); setErr('')
    try {
      const r = await post('/api/auth/login', { email, password }, { token: null })
      auth.set(r.token)
      onDone()
      nav('/')
    } catch (e2) { setErr(e2.message) } finally { setBusy(false) }
  }
  return (
    <div className="login-wrap">
      <div className="login-art">
        <Logo brand={brand} height={46} light />
        <div className="col" style={{ gap: 18 }}>
          <h2>Every candidate, interview and test in one place.</h2>
          <ul>
            <li>✓ Invites and emails go out from your own Outlook</li>
            <li>✓ Candidates without contact for 30 days are flagged automatically</li>
            <li>✓ Locked-down, recorded tests with start codes</li>
          </ul>
        </div>
        <div className="small" style={{ color: '#aeb8cf' }}>{brand.company_name || 'Novamodus Solutions Inc.'}</div>
      </div>
      <div className="login-side">
        <form className="login-card" onSubmit={submit}>
          <h1>Sign in</h1>
          {opts.microsoft && <>
            <a className="btn ms-btn" href="/api/auth/microsoft/start" style={{ height: 44 }}><MsLogo />Sign in with Microsoft</a>
            <div className="or"><span>{opts.password === 'admins' ? 'admins only' : 'or use your HireModus password'}</span></div>
          </>}
          {!opts.microsoft && <div className="muted">Use your Novamodus email and HireModus password.</div>}
          <Field label="Email"><input autoFocus={!opts.microsoft} value={email} onChange={e => setEmail(e.target.value)} /></Field>
          <Field label="Password"><input type="password" value={password} onChange={e => setPassword(e.target.value)} /></Field>
          {err && <div className="alert bad">{err}</div>}
          <button className={opts.microsoft ? '' : 'primary'} disabled={busy} style={{ justifyContent: 'center', height: 42 }}>Sign in with password</button>
          <div className="small muted">Taking a test? Go to the <a href="/portal">test portal</a>.</div>
        </form>
      </div>
    </div>
  )
}

function ChangePassword({ onDone }) {
  const [cur, setCur] = useState('')
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [err, setErr] = useState('')
  const save = async () => {
    if (pw !== pw2) return setErr('The new passwords don’t match')
    try { await post('/api/auth/change-password', { current_password: cur, new_password: pw }); onDone() } catch (e) { setErr(e.message) }
  }
  return (
    <Modal title="Set a new password" onClose={() => {}} footer={<button className="primary" onClick={save}>Save password</button>}>
      <div className="muted">You're using a temporary password. Choose your own before continuing.</div>
      <Field label="Current password"><input type="password" value={cur} onChange={e => setCur(e.target.value)} /></Field>
      <Field label="New password" hint="At least 8 characters"><input type="password" value={pw} onChange={e => setPw(e.target.value)} /></Field>
      <Field label="Repeat new password"><input type="password" value={pw2} onChange={e => setPw2(e.target.value)} /></Field>
      {err && <div className="alert bad">{err}</div>}
    </Modal>
  )
}

function MsLogo() {
  return <svg width="18" height="18" viewBox="0 0 21 21" aria-hidden="true"><path fill="#f25022" d="M0 0h10v10H0z" /><path fill="#7fba00" d="M11 0h10v10H11z" /><path fill="#00a4ef" d="M0 11h10v10H0z" /><path fill="#ffb900" d="M11 11h10v10H11z" /></svg>
}
