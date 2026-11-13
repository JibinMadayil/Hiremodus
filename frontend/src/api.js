const KEY = 'hm_token'

export const auth = {
  get token() { try { return localStorage.getItem(KEY) } catch { return null } },
  set(t) { try { t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY) } catch { /* ignore */ } },
}

let onUnauthorized = () => {}
export function setUnauthorizedHandler(fn) { onUnauthorized = fn }

export async function api(path, { method = 'GET', body, token, form, raw } = {}) {
  const headers = {}
  const t = token === undefined ? auth.token : token
  if (t) headers.Authorization = 'Bearer ' + t
  let payload
  if (form) payload = form
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  const res = await fetch(path, { method, headers, body: payload })
  if (raw) return res
  let data = null
  const text = await res.text()
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    if (res.status === 401 && token === undefined) onUnauthorized()
    const msg = data && data.detail ? (typeof data.detail === 'string' ? data.detail : data.detail.map(d => d.msg).join(', ')) : `Request failed (${res.status})`
    const err = new Error(msg)
    err.status = res.status
    throw err
  }
  return data
}

export const get = (p, o) => api(p, o)
export const post = (p, body, o = {}) => api(p, { ...o, method: 'POST', body })
export const put = (p, body, o = {}) => api(p, { ...o, method: 'PUT', body })
export const patch = (p, body, o = {}) => api(p, { ...o, method: 'PATCH', body })
export const del = (p, o = {}) => api(p, { ...o, method: 'DELETE' })

export function fmtDate(iso, withTime = true) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d)) return iso
  const opts = { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }
  if (withTime) { opts.hour = 'numeric'; opts.minute = '2-digit' }
  return d.toLocaleString('en-CA', opts)
}

export function fmtUtc(iso) {
  // timestamps the server stores in UTC (logs, jobs)
  if (!iso) return ''
  return fmtDate(iso.endsWith('Z') ? iso : iso + 'Z')
}

export const fullName = c => `${c.first_name || ''} ${c.last_name || ''}`.trim() || '(no name)'
