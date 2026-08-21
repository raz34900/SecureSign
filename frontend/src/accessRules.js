/**
 * Which roles each protected route admits. Plain data, apart from the route table, so
 * routing.check.mjs can check it without a browser. The invariant: roleHome() must return
 * a path the user is admitted to, or the guard redirects into a loop and the tab locks up.
 */
export const ROUTE_ROLES = {
  '/verify': ['verifier', 'clerk'],
  '/enrol': ['clerk'],
  '/customers': ['clerk'],
  '/history': ['verifier', 'clerk'],
  '/engineering': ['engineer'],
  '/accounts': ['engineer'],
  '/team': ['org_admin'],
}

/** Every role and organisation type an account can actually have. */
export const ACCOUNT_KINDS = [
  { role: 'clerk', org_type: 'financial' },
  { role: 'verifier', org_type: 'subscriber' },
  { role: 'verifier', org_type: 'financial' },
  { role: 'org_admin', org_type: 'financial' },
  { role: 'org_admin', org_type: 'subscriber' },
  { role: 'engineer', org_type: 'operator' },
]
