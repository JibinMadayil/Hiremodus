import { createContext, useContext, useEffect, useState } from 'react'

export const DEFAULT_BRAND = { brand_name: 'HireModus', brand_tagline: 'BY NOVAMODUS', brand_color: '#E5484D', brand_navy: '#1B2A4A', brand_logo: '' }
export const BrandCtx = createContext(DEFAULT_BRAND)
export const useBrand = () => useContext(BrandCtx)

export function applyBrand(b) {
  const root = document.documentElement
  root.style.setProperty('--brand', b.brand_color || DEFAULT_BRAND.brand_color)
  root.style.setProperty('--navy', b.brand_navy || DEFAULT_BRAND.brand_navy)
  document.title = b.brand_name || 'HireModus'
}

export function usePublicBrand() {
  const [b, setB] = useState(DEFAULT_BRAND)
  useEffect(() => {
    fetch('/api/branding').then(r => r.ok ? r.json() : null).then(d => { if (d) { const m = { ...DEFAULT_BRAND, ...d }; setB(m); applyBrand(m) } }).catch(() => {})
  }, [])
  return b
}

/* Split "HireModus" into the coral first word and navy remainder, like the Novamodus wordmark */
function splitName(name) {
  const m = (name || 'HireModus').match(/^([A-Z][a-z]+)(.*)$/)
  return m && m[2] ? [m[1], m[2]] : [name, '']
}

export function Logo({ brand, height = 40, light = false }) {
  const b = { ...DEFAULT_BRAND, ...(brand || {}) }
  if (b.brand_logo) return <img src={b.brand_logo} alt={b.brand_name} style={{ height, maxWidth: 200, objectFit: 'contain' }} />
  const [a, rest] = splitName(b.brand_name)
  const navy = light ? '#ffffff' : b.brand_navy
  return (
    <svg height={height} viewBox="0 0 230 64" role="img" aria-label={b.brand_name} style={{ display: 'block' }}>
      {/* cloud mark */}
      <g transform="translate(2,6)" fill="none" stroke={b.brand_color} strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 30 h22 a8 8 0 0 0 0-16 a11 11 0 0 0-21-2 a7.5 7.5 0 0 0-1 18z" />
        <path d="M17 24 l4-5 l4 3 l5-6" strokeWidth="2.6" />
      </g>
      <text x="50" y="36" fontFamily="'Segoe UI', Arial, sans-serif" fontWeight="800" fontSize="30" letterSpacing="-0.5">
        <tspan fill={b.brand_color}>{a}</tspan><tspan fill={navy}>{rest.toLowerCase()}</tspan>
      </text>
      {b.brand_tagline && <text x="52" y="54" fontFamily="'Segoe UI', Arial, sans-serif" fontWeight="600" fontSize="9.5" letterSpacing="3.2" fill={light ? '#cbd5e1' : '#8a94a6'}>{b.brand_tagline}</text>}
    </svg>
  )
}
