/**
 * What the enrolment wizard keeps across a refresh.
 *
 * The wizard held the national ID, name, consent and crop selection in component refs,
 * so a reload or an unmounting tab switch discarded all of it while the staging entry
 * behind it stayed alive on the server for a full fifteen minutes.
 *
 * The candidate images are deliberately not kept. They are megabytes against a ~5 MB
 * quota, and the server can hand them back from the staged enrolment — this project has
 * already had one bug where a phone discarded a page under memory pressure.
 *
 * The store is passed in rather than reached for, so this is checkable without a browser.
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
