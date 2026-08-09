import { computed, reactive } from 'vue'
import { get, postJson } from './api.js'

export const state = reactive({
  user: null,
  loaded: false,
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

export async function login(orgName, username, password) {
  await postJson('/auth/login', { org_name: orgName, username, password })
  await load()
}

export async function logout() {
  await postJson('/auth/logout', {})
  state.user = null
}

export const isClerk = computed(() => state.user?.role === 'clerk')
export const isVerifier = computed(() => state.user?.role === 'verifier')

export function roleHome() {
  if (state.user?.role === 'clerk') return '/enrol'
  if (state.user?.role === 'verifier') return '/verify'
  return '/login'
}
