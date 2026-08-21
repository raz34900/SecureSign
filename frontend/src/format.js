
export function formatDistance(value) {
  return Number(value).toFixed(4)
}

export function formatConfidence(value) {
  return `${Number(value).toFixed(1)}%`
}

/** The API can emit an offset and a trailing Z together ("...+00:00Z"), which Date rejects. */
export function formatDateTime(value) {
  if (!value) return ''
  const cleaned = String(value).replace(/([+-]\d{2}:\d{2})Z$/, '$1')
  const parsed = new Date(cleaned)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return parsed.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** The server decides the band; this only names it. */
export function decisionLabel(band, verdict) {
  return band === 'borderline' ? 'BORDERLINE' : verdict
}

export function isNationalId(value) {
  return /^\d{9}$/.test(String(value ?? '').trim())
}

export function pngSrc(base64) {
  return `data:image/png;base64,${base64}`
}
