/**
 * Which roles each protected route admits.
 *
 * Kept as plain data, apart from the route table, so it can be checked without a
 * browser — see routing.check.mjs. The rule these have to satisfy is that roleHome()
 * always returns a path the user is admitted to; when it does not, the guard redirects
 * a user to a page that rejects them, which redirects them again, and the tab locks up.
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
