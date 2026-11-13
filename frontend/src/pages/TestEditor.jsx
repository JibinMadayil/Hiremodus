import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { get, post, put, del, api } from '../api'
import { useApp, Field, Loading, Confirm, DeptPicker } from '../ui'

const blank = { name: '', department_id: null, department_ids: [], duration_min: 30, instructions: '', allow_file_upload: false, shuffle_questions: false, code_valid_minutes: 30, shuffle_options: false, pool_choice: null, pool_written: null, record_camera: true, record_audio: true, record_screen: true, active: true, questions: [] }
const KINDS = { mcq: 'Multiple choice, one answer (auto-graded)', multi: 'Multiple choice, select all that apply (auto-graded)', short:'Short written answer', long: 'Long written answer', file: 'File upload' }

export default function TestEditor() {
  const { id } = useParams()
  const { meta, toast, refreshMeta, me } = useApp()
  const nav = useNavigate()
  const [t, setT] = useState(id ? null : { ...blank, department_ids: me.scope_ids?.length === 1 ? [...me.scope_ids] : [] })
  const [err, setErr] = useState('')
  const [confirmDel, setConfirmDel] = useState(false)
  useEffect(() => { if (id) get(`/api/tests/${id}`).then(setT) }, [id])
  if (!t) return <Loading />
  const set = (k, v) => setT(x => ({ ...x, [k]: v }))
  const setQ = (i, k, v) => setT(x => ({ ...x, questions: x.questions.map((q, j) => j === i ? { ...q, [k]: v } : q) }))
  const choice = k => k === 'mcq' || k === 'multi'
  const addQ = kind => setT(x => {
    const lastSection = x.questions[x.questions.length - 1]?.section || ''
    return { ...x, questions: [...x.questions, { kind, section: lastSection, prompt: '', image: '', options: choice(kind) ? ['', '', '', ''] : [], option_images: choice(kind) ? ['', '', '', ''] : [], correct_index: kind === 'mcq' ? 0 : null, correct_indices: [], points: choice(kind) ? 1 : 5 }] }
  })
  const uploadPic = async (file, done) => {
    const fd = new FormData(); fd.append('file', file)
    try { const r = await api('/api/test-images', { method: 'POST', form: fd }); done(r.url) } catch (e) { toast(e.message, 'bad') }
  }
  const removeOpt = (i, k) => setT(x => ({ ...x, questions: x.questions.map((q, j) => j !== i ? q : {
    ...q, options: q.options.filter((_, m) => m !== k), option_images: (q.option_images || []).filter((_, m) => m !== k),
    correct_index: q.correct_index > k ? q.correct_index - 1 : q.correct_index === k ? 0 : q.correct_index,
    correct_indices: (q.correct_indices || []).filter(c => c !== k).map(c => c > k ? c - 1 : c),
  }) }))
  const move = (i, d) => setT(x => { const q = [...x.questions]; const [m] = q.splice(i, 1); q.splice(i + d, 0, m); return { ...x, questions: q } })
  const total = t.questions.reduce((s, q) => s + (+q.points || 0), 0)
  const save = async () => {
    setErr('')
    try {
      const body = { ...t, questions: t.questions.map(q => ({ ...q, points: +q.points || 0 })) }
      const r = id ? await put(`/api/tests/${id}`, body) : await post('/api/tests', body)
      toast('Test saved'); refreshMeta()
      if (!id) nav(`/tests/${r.id}`, { replace: true }); else setT(r)
    } catch (e) { setErr(e.message) }
  }
  return (
    <div className="col" style={{ maxWidth: 900 }}>
      <div className="page-head"><div><h1>{id ? 'Edit test' : 'New test'}</h1><div className="muted">{t.questions.length} questions, {total} points</div></div>
        <div className="row">{id && <button className="danger" onClick={() => setConfirmDel(true)}>Delete</button>}<button onClick={() => nav('/tests')}>Back</button><button className="primary" onClick={save}>Save test</button></div></div>
      {err && <div className="alert bad">{err}</div>}
      <div className="card grid3">
        <Field label="Test name" className="span2"><input value={t.name} onChange={e => set('name', e.target.value)} /></Field>
        <Field label="Departments" className="span3" hint="People who work in these departments, or are on their CC lists, can see this test, its questions and results. Pick at least one."><DeptPicker value={t.department_ids || []} allowed={me.scope_ids} onChange={v => set('department_ids', v)} /></Field>
        <Field label="Time limit (minutes)"><input type="number" min={1} value={t.duration_min} onChange={e => set('duration_min', +e.target.value)} /></Field>
        <Field label="Start code valid for (minutes)"><input type="number" min={1} value={t.code_valid_minutes} onChange={e => set('code_valid_minutes', +e.target.value)} /></Field>
        <div className="col" style={{ gap: 6, justifyContent: 'flex-end' }}>
          <label className="check"><input type="checkbox" checked={t.allow_file_upload} onChange={e => set('allow_file_upload', e.target.checked)} /> Allow file uploads (Dev tests)</label>
          <label className="check"><input type="checkbox" checked={t.shuffle_questions} onChange={e => set('shuffle_questions', e.target.checked)} /> Shuffle question order</label>
          <label className="check"><input type="checkbox" checked={!!t.shuffle_options} onChange={e => set('shuffle_options', e.target.checked)} /> Shuffle answer options</label>
          <label className="check"><input type="checkbox" checked={t.active} onChange={e => set('active', e.target.checked)} /> Active</label>
        </div>
        <div className="span3 row" style={{ borderTop: '1px solid var(--line)', paddingTop: 10, alignItems: 'flex-end' }}>
          <b style={{ alignSelf: 'center' }}>Question pool:</b>
          <Field label={`Choice questions per candidate (of ${t.questions.filter(q => q.kind === 'mcq' || q.kind === 'multi').length})`}><input type="number" min={1} style={{ width: 120 }} placeholder="All" value={t.pool_choice ?? ''} onChange={e => set('pool_choice', e.target.value === '' ? null : +e.target.value)} /></Field>
          <Field label={`Written questions per candidate (of ${t.questions.filter(q => q.kind !== 'mcq' && q.kind !== 'multi').length})`}><input type="number" min={1} style={{ width: 120 }} placeholder="All" value={t.pool_written ?? ''} onChange={e => set('pool_written', e.target.value === '' ? null : +e.target.value)} /></Field>
          <span className="small muted" style={{ alignSelf: 'center' }}>Leave empty to give everyone every question. With a pool, each candidate gets a different random set.</span>
        </div>
        <div className="span3 row" style={{ borderTop: '1px solid var(--line)', paddingTop: 10 }}>
          <b>Record the candidate:</b>
          <label className="check"><input type="checkbox" checked={t.record_screen} onChange={e => set('record_screen', e.target.checked)} /> Entire screen</label>
          <label className="check"><input type="checkbox" checked={t.record_camera} onChange={e => set('record_camera', e.target.checked)} /> Camera</label>
          <label className="check"><input type="checkbox" disabled={!t.record_camera} checked={t.record_camera && t.record_audio} onChange={e => set('record_audio', e.target.checked)} /> Microphone</label>
          <span className="small muted">Recordings are deleted automatically at midnight on the day of the test.</span>
        </div>
        <Field label="Instructions shown before the test starts" className="span3"><textarea value={t.instructions} onChange={e => set('instructions', e.target.value)} /></Field>
      </div>

      {t.questions.map((q, i) => (
        <div key={i} className="card col">
          <div className="row between"><b>Question {i + 1} · {KINDS[q.kind]}</b>
            <div className="row"><Field label="Points"><input type="number" min={0} step="0.5" style={{ width: 80 }} value={q.points} onChange={e => setQ(i, 'points', e.target.value)} /></Field>
              <button className="sm" disabled={i === 0} onClick={() => move(i, -1)}>↑</button><button className="sm" disabled={i === t.questions.length - 1} onClick={() => move(i, 1)}>↓</button>
              <button className="sm danger" onClick={() => setT(x => ({ ...x, questions: x.questions.filter((_, j) => j !== i) }))}>Remove</button></div></div>
          <div className="row" style={{ alignItems: 'flex-end' }}>
            <Field label="Section (optional)"><input style={{ width: 200 }} placeholder="e.g. Aptitude" list="sections" value={q.section || ''} onChange={e => setQ(i, 'section', e.target.value)} /></Field>
          </div>
          <textarea style={{ minHeight: 60 }} placeholder="Question text" value={q.prompt} onChange={e => setQ(i, 'prompt', e.target.value)} />
          <PicSlot url={q.image} label="Add a picture to the question" onFile={f => uploadPic(f, url => setQ(i, 'image', url))} onClear={() => setQ(i, 'image', '')} big />
          {choice(q.kind) && <div className="col" style={{ gap: 6 }}>
            {q.options.map((o, k) => (
              <div key={k} className="row" style={{ flexWrap: 'nowrap' }}>
                {q.kind === 'mcq'
                  ? <input type="radio" name={`c${i}`} checked={q.correct_index === k} onChange={() => setQ(i, 'correct_index', k)} title="Correct answer" />
                  : <input type="checkbox" checked={(q.correct_indices || []).includes(k)} title="Correct answer"
                      onChange={e => setQ(i, 'correct_indices', e.target.checked ? [...(q.correct_indices || []), k].sort((a, b) => a - b) : (q.correct_indices || []).filter(c => c !== k))} />}
                <input value={o} placeholder={`Option ${k + 1}`} onChange={e => setQ(i, 'options', q.options.map((x, m) => m === k ? e.target.value : x))} />
                <PicSlot url={q.option_images?.[k]} label="Picture" onFile={f => uploadPic(f, url => setQ(i, 'option_images', q.options.map((_, m) => m === k ? url : (q.option_images?.[m] || ''))))}
                  onClear={() => setQ(i, 'option_images', q.options.map((_, m) => m === k ? '' : (q.option_images?.[m] || '')))} />
                <button className="sm ghost" onClick={() => removeOpt(i, k)}>✕</button>
              </div>
            ))}
            <div className="row"><button className="sm" onClick={() => setT(x => ({ ...x, questions: x.questions.map((qq, j) => j !== i ? qq : { ...qq, options: [...qq.options, ''], option_images: [...(qq.option_images || qq.options.map(() => '')), ''] }) }))}>Add option</button>
              <span className="small muted">{q.kind === 'mcq' ? 'Select the radio button next to the correct answer.' : 'Tick every correct answer. The candidate gets the points only if they pick exactly these.'}</span></div>
          </div>}
        </div>
      ))}
      <datalist id="sections">{[...new Set(t.questions.map(q => q.section).filter(Boolean))].map(x => <option key={x} value={x} />)}</datalist>
      <div className="card row"><span className="muted">Add question:</span>
        {Object.entries(KINDS).filter(([k]) => k !== 'file' || t.allow_file_upload).map(([k, v]) => <button key={k} onClick={() => addQ(k)}>{v}</button>)}
      </div>
      {confirmDel && <Confirm title="Delete test" danger confirmLabel="Delete" message="Tests that candidates have already taken are switched off instead, so their results stay." onClose={() => setConfirmDel(false)}
        onConfirm={() => del(`/api/tests/${id}`).then(() => { refreshMeta(); nav('/tests') })} />}
    </div>
  )
}

function PicSlot({ url, label, onFile, onClear, big }) {
  const pick = e => { const f = e.target.files[0]; e.target.value = ''; if (f) onFile(f) }
  if (url) return (
    <span className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
      <img src={url} alt="" style={{ maxHeight: big ? 160 : 44, maxWidth: big ? 320 : 70, borderRadius: 6, border: '1px solid var(--line)', background: '#fff' }} />
      <button className="sm ghost" onClick={onClear} title="Remove picture">✕</button>
    </span>
  )
  return <label className="btn sm ghost" style={{ whiteSpace: 'nowrap', alignSelf: 'flex-start' }}>+ {label}<input type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden onChange={pick} /></label>
}
