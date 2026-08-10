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

async function handleResponse(res) {
  let body = null
  try {
    body = await res.json()
  } catch {
    body = null
  }

  if (!res.ok) {
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
