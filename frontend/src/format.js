
export const BORDERLINE_MARGIN = 0.05

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

/**
 * Three outcomes, not two. A distance sitting within BORDERLINE_MARGIN of the
 * threshold is a coin flip from an 84%-accurate model, and the interface has to
 * say so rather than painting it solid green or solid red.
 */
export function classifyDecision(distance, threshold) {
  const gap = Math.abs(Number(distance) - Number(threshold))
  if (gap < BORDERLINE_MARGIN) return 'borderline'
  return Number(distance) < Number(threshold) ? 'valid' : 'fraud'
}

export function decisionLabel(kind, verdict) {
  if (kind === 'borderline') return 'BORDERLINE'
  return verdict
}
