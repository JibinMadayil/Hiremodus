import { createContext, useCallback, useContext, useEffect, useState } from 'react'

export const AppCtx = createContext(null)
export const useApp = () => useContext(AppCtx)

export function Modal({ title, onClose, children, footer, wide }) {
  useEffect(() => {
    const k = e => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  return (
    <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose?.() }}>
      <div className={'modal' + (wide ? ' wide' : '')}>
        <div className="modal-head"><h2 style={{ margin: 0 }}>{title}</h2><button className="ghost" onClick={onClose} aria-label="Close">✕</button></div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

export function Field({ label, hint, children, className }) {
  return <label className={'f ' + (className || '')}>{label}{children}{hint && <span className="hint">{hint}</span>}</label>
}

export function useToasts() {
  const [items, setItems] = useState([])
  const push = useCallback((msg, kind = '') => {
    const id = Math.random()
    setItems(x => [...x, { id, msg, kind }])
    setTimeout(() => setItems(x => x.filter(i => i.id !== id)), kind === 'bad' ? 7000 : 4000)
  }, [])
  const view = <div className="toast-wrap">{items.map(t => <div key={t.id} className={'toast ' + t.kind}>{t.msg}</div>)}</div>
  return [push, view]
}

export function StageBadge({ id }) {
  const { meta } = useApp()
  const s = meta.stages.find(x => x.id === id)
  if (!s) return <span className="badge">No stage</span>
  return <span className="badge" style={{ background: s.color + '22', color: s.color }}><span className="dot" style={{ background: s.color }} />{s.name}</span>
}

export function DeptBadge({ id }) {
  const { meta } = useApp()
  const d = meta.departments.find(x => x.id === id)
  if (!d) return <span className="muted small">None</span>
  return <span className="badge" style={{ background: d.color + '1f', color: d.color }}>{d.name}</span>
}

const JOB_STATUS = { queued: ['Waiting for Outlook', 'warn'], claimed: ['Sending', 'info'], done: ['Done', 'ok'], failed: ['Failed', 'bad'], cancelled: ['Cancelled', ''] }
export function JobBadge({ status }) {
  const [t, k] = JOB_STATUS[status] || [status, '']
  return <span className={'badge ' + k}>{t}</span>
}

const TEST_STATUS = { assigned: ['Not started', ''], in_progress: ['In progress', 'warn'], submitted: ['Needs grading', 'info'], graded: ['Graded', 'ok'], revoked: ['Revoked', 'bad'] }
export function TestBadge({ status }) {
  const [t, k] = TEST_STATUS[status] || [status, '']
  return <span className={'badge ' + k}>{t}</span>
}

export function Confirm({ title, message, confirmLabel = 'Confirm', danger, onConfirm, onClose, busy }) {
  return (
    <Modal title={title} onClose={onClose} footer={<>
      <button onClick={onClose}>Cancel</button>
      <button className={danger ? 'danger solid' : 'primary'} disabled={busy} onClick={onConfirm}>{confirmLabel}</button>
    </>}>
      <div className="pre">{message}</div>
    </Modal>
  )
}

export function useAsync(fn, deps) {
  const [state, setState] = useState({ loading: true, data: null, error: null })
  const run = useCallback(() => {
    setState(s => ({ ...s, loading: true }))
    return fn().then(data => setState({ loading: false, data, error: null }), error => setState({ loading: false, data: null, error }))
  }, deps) // eslint-disable-line
  useEffect(() => { run() }, [run])
  return [state, run]
}

export function EmailList({ value }) {
  const list = (value || '').split(/[;,\s]+/).filter(Boolean)
  if (!list.length) return <span className="muted">None</span>
  return <div className="chips">{list.map(e => <span key={e} className="chip">{e}</span>)}</div>
}

export function Loading() { return <div className="empty">Loading…</div> }
export function ErrorBox({ error }) { return error ? <div className="alert bad">{error.message || String(error)}</div> : null }

/* Several departments as chips you can tick. `allowed` limits the choice (null = every department). */
export function DeptPicker({ value, onChange, allowed = null }) {
  const { meta } = useApp()
  const list = meta.departments.filter(d => d.active !== false && (allowed == null || allowed.includes(d.id) || value.includes(d.id)))
  const toggle = id => onChange(value.includes(id) ? value.filter(x => x !== id) : [...value, id].sort((a, b) => a - b))
  return (
    <div className="chips">
      {list.map(d => {
        const on = value.includes(d.id), locked = allowed != null && !allowed.includes(d.id)
        return <button type="button" key={d.id} disabled={locked} className={'chip pick' + (on ? ' on' : '')} title={locked ? "You don't work in this department" : ''}
          style={on ? { background: d.color + '22', borderColor: d.color, color: d.color } : undefined} onClick={() => toggle(d.id)}>{on ? '✓ ' : ''}{d.name}</button>
      })}
    </div>
  )
}

export function DeptBadges({ ids }) {
  if (!ids?.length) return <span className="muted small">None</span>
  return <span className="chips">{ids.map(id => <DeptBadge key={id} id={id} />)}</span>
}
