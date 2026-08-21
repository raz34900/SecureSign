import { createRouter, createWebHistory } from 'vue-router'
import { state, load, roleHome, hasRole } from './auth.js'
import { ROUTE_ROLES } from './accessRules.js'
import LoginView from './views/LoginView.vue'
import VerifyView from './views/VerifyView.vue'
import EnrolView from './views/EnrolView.vue'
import CustomersView from './views/CustomersView.vue'
import HistoryView from './views/HistoryView.vue'
import EngineeringView from './views/EngineeringView.vue'
import AccountsView from './views/AccountsView.vue'
import OrgAccountsView from './views/OrgAccountsView.vue'
import ChangePasswordView from './views/ChangePasswordView.vue'

const guarded = (path, name, component) => ({
  path, name, component, meta: { roles: ROUTE_ROLES[path] },
})

const routes = [
  { path: '/login', name: 'login', component: LoginView },
  guarded('/verify', 'verify', VerifyView),
  guarded('/enrol', 'enrol', EnrolView),
  guarded('/customers', 'customers', CustomersView),
  guarded('/history', 'history', HistoryView),
  guarded('/engineering', 'engineering', EngineeringView),
  guarded('/accounts', 'accounts', AccountsView),
  guarded('/team', 'team', OrgAccountsView),
  { path: '/change-password', name: 'change-password', component: ChangePasswordView },
  { path: '/', redirect: () => roleHome() },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

/**
 * Redirecting to where we already are just runs the guard again and freezes the tab. If
 * the routing rules ever disagree, rendering the view is the lesser failure — the server
 * authorises every request independently, so at worst the page shows an error.
 */
function redirect(path, to) {
  return path === to.path ? true : { path }
}

router.beforeEach(async (to) => {
  if (!state.loaded) {
    await load()
  }

  const isAuthenticated = !!state.user

  if (!isAuthenticated) {
    if (to.path !== '/login') return { path: '/login' }
    return true
  }

  if (to.path === '/login') return redirect(roleHome(), to)

  // A password someone else chose is not yet a credential. Nothing else opens until
  // it has been replaced, which matches the server refusing every other endpoint.
  if (state.user.must_change_password && to.path !== '/change-password') {
    return { path: '/change-password' }
  }
  if (!state.user.must_change_password && to.path === '/change-password' && !to.query.voluntary) {
    return redirect(roleHome(), to)
  }

  // Against the effective roles, not the bare one: /enrol admits a clerk, and an
  // org_admin at a bank is a clerk as far as both this guard and the server are
  // concerned.
  const allowedRoles = to.meta?.roles
  if (allowedRoles && !hasRole(...allowedRoles)) {
    return redirect(roleHome(), to)
  }

  return true
})

export default router
