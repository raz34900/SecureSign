const BASE = '/api'

export class ApiError extends Error {
  constructor(code, message, status) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.message = message
    this.status = status
  }
}

/**
 * Called whenever the server rejects us as unauthenticated. Registered by auth.js,
 * which cannot be imported here without a cycle.
 *
 * Without this, a session that dies server-side (expiry, revocation, a rebuilt
 * database) leaves the app believing it is still signed in. Every request then fails
 * while the router keeps bouncing /login back to the role's home page, and the only
 * way out is clearing site data by hand.
 */
let onUnauthorized = null

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

async function handleResponse(res) {
  let body = null
  try {
    body = await res.json()
  } catch {
    body = null // a proxy can answer with HTML; treat it as an empty envelope
  }

  if (!res.ok) {
    if (res.status === 401 && onUnauthorized) onUnauthorized()
    const error = body && body.error
    throw new ApiError(
      error?.code ?? 'UNKNOWN',
      error?.message ?? 'Something went wrong. Please try again.',
      res.status,
    )
  }

  return body
}

async function request(path, options) {
  let res
  try {
    res = await fetch(`${BASE}${path}`, options)
  } catch {
    throw new ApiError('NETWORK', 'Could not reach the server. Check your connection and try again.', 0)
  }
  return handleResponse(res)
}

export function get(path) {
  return request(path, { method: 'GET' })
}

export function postJson(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function postForm(path, formData) {
  return request(path, {
    method: 'POST',
    body: formData,
  })
}

export function del(path) {
  return request(path, { method: 'DELETE' })
}
