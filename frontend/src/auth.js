import { computed, reactive } from 'vue'
import { get, postJson, setUnauthorizedHandler } from './api.js'

export const state = reactive({
  user: null,
  loaded: false,
})

// A rejected request is the server telling us this session is gone. Believe it.
setUnauthorizedHandler(() => {
  state.user = null
})

export async function load() {
  try {
    state.user = await get('/auth/me')
  } catch {
    state.user = null
  } finally {
    state.loaded = true
  }
}

export async function login(orgCode, username, password) {
  await postJson('/auth/login', { org_code: orgCode, username, password })
  await load()
}

/**
 * Signing out must always succeed locally, even when the request does not. If the
 * server call is the only thing that clears state, a failed call strands the user on
 * a page they cannot leave and cannot sign out of.
 */
export async function logout() {
  try {
    await postJson('/auth/logout', {})
  } catch {
    // The cookie may outlive this, but the user still gets back to the login screen.
  }
  state.user = null
}

export const isEngineer = computed(() => state.user?.role === 'engineer')
export const isOrgAdmin = computed(() => state.user?.role === 'org_admin')
export const mustChangePassword = computed(() => !!state.user?.must_change_password)

/**
 * An org_admin holds the senior account for its kind of organisation, so it can do
 * whatever that organisation does. This mirrors IMPLIED_ROLES on the server, and the
 * router must check against this rather than the bare role — a route that admits
 * "clerk" admits an org_admin at a bank, and checking the literal role instead sends
 * them into a redirect loop.
 */
const IMPLIED_ROLES = {
  financial: ['clerk', 'verifier'],
  subscriber: ['verifier'],
}

export const effectiveRoles = computed(() => {
  const role = state.user?.role
  if (!role) return []
  if (role !== 'org_admin') return [role]
  return [role, ...(IMPLIED_ROLES[state.user.org_type] ?? [])]
})

export function hasRole(...roles) {
  return roles.some((role) => effectiveRoles.value.includes(role))
}

export const isClerk = computed(() => hasRole('clerk'))
export const isVerifier = computed(() => hasRole('verifier'))

/** Must always return somewhere this user can actually go, or the guard will loop. */
export function roleHome() {
  if (!state.user) return '/login'
  if (state.user.must_change_password) return '/change-password'
  if (isEngineer.value) return '/engineering'
  if (isClerk.value) return '/enrol'
  if (isVerifier.value) return '/verify'
  if (isOrgAdmin.value) return '/team'
  return '/login'
}
