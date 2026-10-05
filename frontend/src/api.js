const BASE = ''

async function json(url, opts = {}) {
  const res = await fetch(BASE + url, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.detail || data.error || `HTTP ${res.status}`)
  }
  return data
}

export const api = {
  health: () => json('/api/health'),
  cases: () => json('/api/cases'),
  caseDetail: (key) => json(`/api/cases/${key}`),
  computeCase: (key) => json(`/api/cases/${key}/compute`, { method: 'POST' }),
  compute: (payload) => json('/api/compute', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  schemes: () => json('/api/schemes'),
  scheme: (id) => json(`/api/schemes/${id}`),
}
