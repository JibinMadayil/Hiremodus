import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, post } from '../api'
import { useApp, Field } from '../ui'

export default function ImportPage() {
  const { meta, toast, refreshMeta } = useApp()
  const [file, setFile] = useState(null)
  const [pv, setPv] = useState(null)
  const [choices, setChoices] = useState([])
  const [opts, setOpts] = useState({ skip_existing: true, replace_modules: true, create_interviews: true })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [result, setResult] = useState(null)

  const upload = async () => {
    setErr(''); setBusy(true); setResult(null)
    try {
      const fd = new FormData(); fd.append('file', file)
      const r = await api('/api/import/preview', { method: 'POST', form: fd })
      setPv(r); setChoices(r.sheets.map(s => ({ sheet: s.sheet, action: s.action, stage_id: s.stage_id ?? null, department_id: s.department_id ?? null })))
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const setC = (i, k, v) => setChoices(cs => cs.map((c, j) => j === i ? { ...c, [k]: v } : c))
  const commit = async () => {
    setBusy(true); setErr('')
    try {
      const r = await post('/api/import/commit', { token: pv.token, sheets: choices, ...opts })
      setResult(r); setPv(null); toast(`Imported ${r.candidates} candidates`); refreshMeta()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="col" style={{ maxWidth: 1100 }}>
      <div className="page-head"><div><h1>Import from Excel</h1><div className="muted">Bring in the Candidate Tracker workbook. Each sheet becomes a stage, department sheets keep their department, and Module Selection updates the module list.</div></div></div>
      <div className="card row">
        <input type="file" accept=".xlsx,.xlsm" style={{ maxWidth: 380 }} onChange={e => setFile(e.target.files[0])} />
        <button className="primary" disabled={!file || busy} onClick={upload}>Read workbook</button>
        <span className="small muted">Files with a Microsoft sensitivity label must be saved as an unprotected copy first.</span>
      </div>
      {err && <div className="alert bad">{err}</div>}
      {result && <div className="alert ok">Done: {result.candidates} candidates added{result.skipped_existing ? `, ${result.skipped_existing} skipped as already in HireModus` : ''}, {result.interviews} interviews linked to their Outlook invites, {result.modules} modules, {result.holidays} holidays. <Link to="/candidates">View candidates</Link></div>}
      {pv && <>
        <div className="card tight"><table>
          <thead><tr><th>Sheet</th><th>Rows</th><th>Import as</th><th>Stage</th><th>Department</th><th>Columns recognised</th></tr></thead>
          <tbody>{pv.sheets.map((s, i) => (
            <tr key={s.sheet}>
              <td><b>{s.sheet}</b></td>
              <td>{s.rows}{s.already_in_app > 0 && <div className="small muted">{s.already_in_app} already here</div>}</td>
              <td><select value={choices[i].action} onChange={e => setC(i, 'action', e.target.value)}>
                <option value="skip">Skip</option><option value="candidates">Candidates</option><option value="modules">Modules</option><option value="holidays">Holidays</option></select></td>
              <td>{choices[i].action === 'candidates' && <select value={choices[i].stage_id || ''} onChange={e => setC(i, 'stage_id', +e.target.value)}>{meta.stages.map(st => <option key={st.id} value={st.id}>{st.name}</option>)}</select>}</td>
              <td>{choices[i].action === 'candidates' && <select value={choices[i].department_id || ''} onChange={e => setC(i, 'department_id', e.target.value ? +e.target.value : null)}><option value="">None</option>{meta.departments.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select>}</td>
              <td className="small">{s.columns.length > 0 && <details><summary>{s.columns.filter(c => !c.field.startsWith('custom:')).length} of {s.columns.length}</summary>
                {s.columns.map(c => <div key={c.header}><span className="muted">{c.header}</span> → {c.label}</div>)}</details>}</td>
            </tr>
          ))}</tbody>
        </table></div>
        <div className="card col">
          <label className="check"><input type="checkbox" checked={opts.skip_existing} onChange={e => setOpts({ ...opts, skip_existing: e.target.checked })} /> Skip rows whose email is already in HireModus at the same stage (safe to re-run)</label>
          <label className="check"><input type="checkbox" checked={opts.replace_modules} onChange={e => setOpts({ ...opts, replace_modules: e.target.checked })} /> Make the Module Selection sheet the full module list</label>
          <label className="check"><input type="checkbox" checked={opts.create_interviews} onChange={e => setOpts({ ...opts, create_interviews: e.target.checked })} /> Create interview records from dated rounds (keeps the Outlook invite IDs so you can reschedule them)</label>
          <div className="row end"><button className="primary" disabled={busy} onClick={commit}>Import {pv.sheets.filter((s, i) => choices[i].action === 'candidates').reduce((n, s) => n + s.rows, 0)} rows</button></div>
        </div>
      </>}
    </div>
  )
}
