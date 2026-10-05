const BASE = '/api'

async function jfetch(url, opts) {
  const r = await fetch(BASE + url, opts)
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}))
    throw new Error(detail.detail || `${r.status} ${r.statusText}`)
  }
  return r.json()
}

export const api = {
  health: () => jfetch('/health'),
  cases: () => jfetch('/cases'),
  caseData: (name) => jfetch(`/cases/${name}`),
  compute: (project, options, save = false) =>
    jfetch('/compute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, options, save })
    }),
  async uploadXyz(file, surface, src, dst) {
    const fd = new FormData()
    fd.append('file', file)
    const params = new URLSearchParams({ surface })
    if (src) params.set('source_crs', src)
    if (dst) params.set('target_crs', dst)
    const r = await fetch(`${BASE}/parse-xyz?` + params, { method: 'POST', body: fd })
    if (!r.ok) {
      const d = await r.json().catch(() => ({}))
      throw new Error(d.detail || `${r.status}`)
    }
    return r.json()
  }
}

export function fmt(n, d = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Number(n).toLocaleString('zh-CN', {
    minimumFractionDigits: d, maximumFractionDigits: d
  })
}
