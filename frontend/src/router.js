import { createRouter, createWebHistory } from 'vue-router'
import { state, load, roleHome } from './auth.js'
import LoginView from './views/LoginView.vue'
import VerifyView from './views/VerifyView.vue'
import EnrolView from './views/EnrolView.vue'
import CustomersView from './views/CustomersView.vue'
import HistoryView from './views/HistoryView.vue'

const routes = [
  { path: '/login', name: 'login', component: LoginView },
  { path: '/verify', name: 'verify', component: VerifyView, meta: { roles: ['verifier', 'clerk'] } },
  { path: '/enrol', name: 'enrol', component: EnrolView, meta: { roles: ['clerk'] } },
  { path: '/customers', name: 'customers', component: CustomersView, meta: { roles: ['clerk'] } },
  { path: '/history', name: 'history', component: HistoryView, meta: { roles: ['verifier', 'clerk'] } },
  { path: '/', redirect: () => roleHome() },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (!state.loaded) {
    await load()
  }

  const isAuthenticated = !!state.user

  if (!isAuthenticated) {
    if (to.path !== '/login') return { path: '/login' }
    return true
  }

  if (to.path === '/login') return { path: roleHome() }

  const allowedRoles = to.meta?.roles
  if (allowedRoles && !allowedRoles.includes(state.user.role)) {
    return { path: roleHome() }
  }

  return true
})

export default router
