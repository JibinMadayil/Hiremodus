import { useState } from 'react'
import { auth, post, put, fmtUtc } from '../api'
import { useApp } from '../ui'

export default function MyOutlook() {
  const { me, meta, refreshMeta, toast } = useApp()
  const [busy, setBusy] = useState(false)
  const sim = meta.settings.simulate_outlook === 'true'
  const download = async () => {
    setBusy(true)
    try {
      if (!me.has_connector_key) await post('/api/auth/connector-key')
      const r = await fetch('/api/connector/download', { headers: { Authorization: 'Bearer ' + auth.token } })
      if (!r.ok) throw new Error('Download failed')
      const blob = await r.blob(); const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'HireModusConnector.zip'; a.click(); URL.revokeObjectURL(url)
      refreshMeta()
    } catch (e) { toast(e.message, 'bad') } finally { setBusy(false) }
  }
  const graphOn = meta.settings.ms_graph_enabled === 'true'
  const [route, setRoute] = useState(me.mail_transport || 'default')
  const changeRoute = async v => {
    try { const r = await put('/api/me/mail-transport', { mail_transport: v }); setRoute(v); refreshMeta(); toast(r.uses === 'graph' ? 'Your mail now goes through Microsoft 365' : 'Your mail now goes through the Outlook connector') }
    catch (e) { toast(e.message, 'bad') }
  }
  const rotate = async () => { await post('/api/auth/connector-key'); refreshMeta(); toast('New key created. Download the connector again; the old copy stops working.') }
  return (
    <div className="col" style={{ maxWidth: 820 }}>
      <div className="page-head"><div><h1>My Outlook</h1><div className="muted">HireModus sends your emails and invites through the Outlook on your own PC, so they appear in your Sent Items and calendar.</div></div></div>
      {sim && <div className="alert warn">Outlook simulation is switched on for the whole app, so nothing is actually sent yet.</div>}
      {graphOn && <div className="card col" style={{ gap: 8 }}>
        <h2 style={{ margin: 0 }}>How your mail is sent</h2>
        <label className="check"><input type="radio" checked={route === 'default'} onChange={() => changeRoute('default')} /> Use the company default</label>
        <label className="check"><input type="radio" checked={route === 'graph'} onChange={() => changeRoute('graph')} /> <b>Microsoft 365</b><span className="muted">Works with the new Outlook. Nothing to install, and replies are picked up even when your PC is off.</span></label>
        <label className="check"><input type="radio" checked={route === 'connector'} onChange={() => changeRoute('connector')} /> <b>Outlook connector</b><span className="muted">Classic Outlook on your PC, set up below.</span></label>
        <div className="small muted">Either way, emails go out from your own mailbox and candidates' replies show on their page. Meetings booked one way have to be changed the same way.</div>
      </div>}
      <div className="card row between">
        <div><b>Connector status</b><div className="row" style={{ marginTop: 6 }}>
          {me.connector_online ? <span className="badge ok">Online</span> : <span className="badge">Offline</span>}
          {me.connector_last_seen && <span className="small muted">Last seen {fmtUtc(me.connector_last_seen)}{me.connector_info?.outlook_email ? ` as ${me.connector_info.outlook_email}` : ''}{me.connector_info?.machine ? ` on ${me.connector_info.machine}` : ''}</span>}
        </div></div>
        <div className="row"><button className="primary" disabled={busy} onClick={download}>Download connector</button>{me.has_connector_key && <button onClick={rotate}>New key</button>}</div>
      </div>
      <div className="card col">
        <h2>Set it up once (Windows)</h2>
        <ol style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
          <li>Download the connector above and unzip it somewhere permanent, for example <span className="mono">Documents\HireModusConnector</span>. The zip already contains your personal key.</li>
          <li>Install Python 3 for Windows from python.org if you don't have it (tick “Add python.exe to PATH”).</li>
          <li>Double-click <span className="mono">start_connector.bat</span>. The first run installs what it needs, then keeps a small window open.</li>
          <li>Keep Outlook open. Emails, invites and calendar checks you start in HireModus go out within a few seconds.</li>
          <li>Optional: put a shortcut to <span className="mono">start_connector.bat</span> in your Startup folder (Win+R, <span className="mono">shell:startup</span>) so it starts with Windows.</li>
        </ol>
        <div className="small muted">If your PC is off, nothing is lost: items wait in the Outbox and send when the connector is back. Keep the key private; anyone with it could send email as you through HireModus. “New key” cancels the old one.</div>
      </div>
    </div>
  )
}
