/**
 * HTTP client tests.
 *
 * The behaviour under test is the one the backend depends on: the bearer token
 * is attached from the registered provider, a 401 clears the session, and other
 * failures do not.
 */

import { AxiosError, AxiosHeaders } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, API_BASE_URL, api, configureAuth, request } from '@/lib/api'

function errorWithStatus(status: number | undefined, data: unknown = null): AxiosError {
  const error = new AxiosError('failed')
  if (status !== undefined) {
    error.response = { status, data, statusText: '', headers: {}, config: undefined }
  }
  return error
}

/** A real axios error for "the request never reached the server". */
function networkError(): AxiosError {
  return new AxiosError('Network Error')
}

describe('base URL', () => {
  it('is relative by default so requests stay same-origin in dev', () => {
    // An absolute default would hardcode a backend address into the bundle and
    // require CORS in development.
    expect(API_BASE_URL).toBe('')
  })
})

describe('authorization header', () => {
  beforeEach(() => {
    configureAuth(() => null, () => {})
  })

  it('is attached when a token is registered', () => {
    configureAuth(() => 'token-123', () => {})

    // Run the registered request interceptor directly. Going through a real
    // request would need a network stub and would not assert the header.
    const handler = api.interceptors.request.handlers[0]?.fulfilled
    expect(handler).toBeTypeOf('function')

    const config = { headers: new AxiosHeaders(), url: '/api/auth/me' } as never
    handler?.(config)

    expect((config as { headers: AxiosHeaders }).headers.get('Authorization')).toBe('Bearer token-123')
  })

  it('is omitted when signed out', () => {
    configureAuth(() => null, () => {})
    const handler = api.interceptors.request.handlers[0]?.fulfilled
    const config = { headers: new AxiosHeaders(), url: '/x' } as never
    handler?.(config)
    expect((config as { headers: AxiosHeaders }).headers.get('Authorization')).toBeUndefined()
  })
})

/**
 * Run the registered response interceptor's rejection handler.
 *
 * The handler is invoked directly rather than through `request()`. Mocking
 * `api.request` short-circuits the interceptor chain entirely, so an assertion
 * about interceptor behaviour under a mocked transport would pass for the wrong
 * reason - or fail for one.
 */
function runResponseInterceptor(error: unknown): Promise<unknown> {
  const handler = api.interceptors.response.handlers[0]?.rejected
  expect(handler).toBeTypeOf('function')
  return handler?.(error) as Promise<unknown>
}

describe('401 handling', () => {
  it('invokes the sign-out handler', async () => {
    const onUnauthorized = vi.fn()
    configureAuth(() => 'bad-token', onUnauthorized)

    await expect(runResponseInterceptor(errorWithStatus(401, { detail: 'Invalid token' }))).rejects.toBeDefined()
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('does not sign out on 403 or 404', async () => {
    const onUnauthorized = vi.fn()
    configureAuth(() => 'good-token', onUnauthorized)

    await expect(runResponseInterceptor(errorWithStatus(403))).rejects.toBeDefined()
    await expect(runResponseInterceptor(errorWithStatus(404))).rejects.toBeDefined()
    await expect(runResponseInterceptor(networkError())).rejects.toBeDefined()

    // A 403, a 404, or an unreachable server is a real answer about one
    // request. Tearing down the session for any of them would log the user out
    // for an ordinary mistake or a flaky connection.
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('ignores a non-axios rejection', async () => {
    const onUnauthorized = vi.fn()
    configureAuth(() => 'token', onUnauthorized)

    await expect(runResponseInterceptor(new TypeError('bug'))).rejects.toBeDefined()
    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})

describe('ApiError normalisation', () => {
  it('exposes a string detail as the message', async () => {
    configureAuth(() => 't', () => {})
    vi.spyOn(api, 'request').mockRejectedValueOnce(
      errorWithStatus(400, { detail: 'Email already registered' }),
    )

    await expect(request({ method: 'GET', url: '/x' })).rejects.toMatchObject({
      status: 400,
      detail: 'Email already registered',
    })
  })

  it('flattens a FastAPI 422 validation array into one sentence', async () => {
    configureAuth(() => 't', () => {})
    vi.spyOn(api, 'request').mockRejectedValueOnce(
      errorWithStatus(422, {
        detail: [
          { loc: ['body', 'amount'], msg: 'Input should be greater than 0' },
          { loc: ['body', 'category'], msg: 'Field required' },
        ],
      }),
    )

    try {
      await request({ method: 'POST', url: '/api/transactions' })
      expect.unreachable('should have thrown')
    } catch (error) {
      const apiError = error as ApiError
      expect(apiError).toBeInstanceOf(ApiError)
      expect(apiError.detail).toContain('amount')
      expect(apiError.detail).toContain('greater than 0')
      expect(apiError.fields).toEqual([
        { field: 'amount', message: 'Input should be greater than 0' },
        { field: 'category', message: 'Field required' },
      ])
    }
  })

  it('reports a network failure as status 0, not as a server error', async () => {
    configureAuth(() => 't', () => {})
    // No response object: the request never reached the server.
    vi.spyOn(api, 'request').mockRejectedValueOnce(networkError())

    try {
      await request({ method: 'GET', url: '/x' })
      expect.unreachable('should have thrown')
    } catch (error) {
      const apiError = error as ApiError
      expect(apiError.status).toBe(0)
      expect(apiError.isNetworkError).toBe(true)
      expect(apiError.isAuthError).toBe(false)
      expect(apiError.detail).toMatch(/could not reach the server/i)
    }
  })

  it('recognises auth errors', async () => {
    configureAuth(() => 't', () => {})
    vi.spyOn(api, 'request').mockRejectedValueOnce(errorWithStatus(401, { detail: 'nope' }))
    await expect(request({ method: 'GET', url: '/x' })).rejects.toMatchObject({ isAuthError: true })
  })

  it('handles a response body that is not JSON at all', async () => {
    configureAuth(() => 't', () => {})
    vi.spyOn(api, 'request').mockRejectedValueOnce(errorWithStatus(502, '<html>Bad Gateway</html>'))
    await expect(request({ method: 'GET', url: '/x' })).rejects.toMatchObject({ status: 502 })
  })
})

describe('request unwrapping', () => {
  it('returns the response body', async () => {
    configureAuth(() => 't', () => {})
    vi.spyOn(api, 'request').mockResolvedValueOnce({ data: { ok: true } })
    await expect(request({ method: 'GET', url: '/x' })).resolves.toEqual({ ok: true })
  })

  it('rethrows non-Axios failures untouched', async () => {
    configureAuth(() => 't', () => {})
    vi.spyOn(api, 'request').mockRejectedValueOnce(new Error('boom'))
    await expect(request({ method: 'GET', url: '/x' })).rejects.toThrow('boom')
  })
})
