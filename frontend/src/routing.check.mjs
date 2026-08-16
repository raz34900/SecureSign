/**
 * The routing rules have to agree with each other, or the browser locks up.
 *
 *   node src/routing.check.mjs
 *
 * An org_admin at a bank was sent to /enrol by roleHome(), /enrol admitted only the
 * literal role "clerk", so the guard redirected to roleHome() again — the same path —
 * and the tab froze. No amount of clicking helps, because the loop is synchronous.
 *
 * This asserts the invariant that makes that impossible: for every kind of account,
 * roleHome() returns a path that account is admitted to.
 */
import assert from 'node:assert/strict'

import { state } from './auth.js'
import { hasRole, roleHome } from './auth.js'
import { ACCOUNT_KINDS, ROUTE_ROLES } from './accessRules.js'

function as(user) {
  state.user = user
  state.loaded = true
}

let checks = 0

for (const kind of ACCOUNT_KINDS) {
  as({ ...kind, username: 'u', org_code: 'XX00', must_change_password: false })

  const home = roleHome()
  assert.notEqual(home, '/login', `${kind.role}/${kind.org_type} has no home to go to`)

  const required = ROUTE_ROLES[home]
  if (required) {
    assert.ok(hasRole(...required),
      `${kind.role}/${kind.org_type} is sent to ${home}, which admits only ` +
      `${required.join(', ')} — the guard would redirect there forever`)
  }
  checks += 1
}

// A handed-out password overrides everything, and that page is never role-guarded.
as({ role: 'clerk', org_type: 'financial', must_change_password: true })
assert.equal(roleHome(), '/change-password')
assert.equal(ROUTE_ROLES['/change-password'], undefined)
checks += 1

// An org_admin at a bank does a clerk's work; at a shop it does not.
as({ role: 'org_admin', org_type: 'financial', must_change_password: false })
assert.ok(hasRole('clerk') && hasRole('verifier'))
as({ role: 'org_admin', org_type: 'subscriber', must_change_password: false })
assert.ok(hasRole('verifier'))
assert.ok(!hasRole('clerk'), 'a shop does not enrol, so its administrator does not either')
checks += 2

// No institutional role may ever reach the engineering panel.
for (const kind of ACCOUNT_KINDS.filter((k) => k.org_type !== 'operator')) {
  as({ ...kind, must_change_password: false })
  assert.ok(!hasRole('engineer'), `${kind.role}/${kind.org_type} must not be an engineer`)
  checks += 1
}

console.log(`routing rules consistent (${checks} checks)`)
