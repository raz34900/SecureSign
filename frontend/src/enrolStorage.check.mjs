/**
 * The enrolment wizard now survives a refresh, and the thing it must never do is come
 * back wrong. A restore that silently re-ticks specimens the clerk rejected, or that
 * throws on a store the browser has blocked, is worse than not restoring at all.
 *
 *   node src/enrolStorage.check.mjs
 */
import assert from 'node:assert/strict'

import { save, load, clear } from './enrolStorage.js'

function fakeStorage(initial = {}) {
  const data = { ...initial }
  return {
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v) },
    removeItem: (k) => { delete data[k] },
    data,
  }
}

let checks = 0

const state = {
  step: 3,
  nationalId: '123456789',
  fullName: 'Test Person',
  consentGranted: true,
  consentMethod: 'signed_form',
  enrolmentId: 'e-1',
  enrolMode: 'new',
  deselected: ['crop-2', 'crop-5'],
}

const store = fakeStorage()
assert.equal(save(store, state), true)
assert.deepEqual(load(store), state, 'a round trip must not change anything')
checks++

clear(store)
assert.equal(load(store), null, 'cleared means gone')
checks++

assert.equal(load(fakeStorage()), null, 'nothing saved reads as nothing')
checks++

// A half-written or hand-edited entry must not take the wizard down with it.
assert.equal(load(fakeStorage({ 'securesign.enrol': '{oops' })), null)
assert.equal(load(fakeStorage({ 'securesign.enrol': 'null' })), null)
assert.equal(load(fakeStorage({ 'securesign.enrol': '"a string"' })), null)
checks++

// Missing fields fall back rather than restoring `undefined` into the form.
const sparse = load(fakeStorage({ 'securesign.enrol': '{"step":2}' }))
assert.equal(sparse.nationalId, '')
assert.equal(sparse.consentGranted, false)
assert.equal(sparse.consentMethod, 'signed_form')
assert.equal(sparse.enrolmentId, null)
assert.deepEqual(sparse.deselected, [], 'a missing selection must not re-tick by accident')
checks++

// deselected has to survive as a list, or every rejected specimen comes back ticked.
const tampered = load(fakeStorage({ 'securesign.enrol': '{"deselected":"crop-2"}' }))
assert.deepEqual(tampered.deselected, [])
checks++

// Private browsing and full quotas throw on write. Losing the state is acceptable;
// losing the enrolment is not.
const blocked = {
  getItem: () => { throw new Error('blocked') },
  setItem: () => { throw new Error('blocked') },
  removeItem: () => { throw new Error('blocked') },
}
assert.equal(save(blocked, state), false)
assert.equal(load(blocked), null)
clear(blocked)
checks++

console.log(`enrolment wizard storage consistent (${checks} checks)`)
