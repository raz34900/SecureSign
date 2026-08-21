/**
 * What the enrolment wizard keeps across a refresh, while the server's staging entry
 * outlives it for fifteen minutes. Not the candidate images: megabytes against a ~5 MB
 * quota, and the server hands them back. The store is passed in so this is checkable
 * without a browser.
 */
const KEY = 'securesign.enrol'

/** Never throws: a full or blocked store costs the clerk a refresh, not the enrolment. */
export function save(storage, state) {
  try {
    storage.setItem(KEY, JSON.stringify(state))
  } catch {
    return false
  }
  return true
}

/** Null when there is nothing to restore, or when what is there is not readable. */
export function load(storage) {
  let raw = null
  try {
    raw = storage.getItem(KEY)
  } catch {
    return null
  }
  if (!raw) return null
  let parsed = null
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object') return null
  return {
    step: parsed.step ?? 1,
    nationalId: typeof parsed.nationalId === 'string' ? parsed.nationalId : '',
    fullName: typeof parsed.fullName === 'string' ? parsed.fullName : '',
    consentGranted: !!parsed.consentGranted,
    consentMethod: parsed.consentMethod || 'signed_form',
    enrolmentId: parsed.enrolmentId || null,
    enrolMode: parsed.enrolMode || null,
    deselected: Array.isArray(parsed.deselected) ? parsed.deselected : [],
  }
}

export function clear(storage) {
  try {
    storage.removeItem(KEY)
  } catch {
    // It was never written.
  }
}
