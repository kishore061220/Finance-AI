/**
 * The single HTTP client every request goes through.
 *
 * Two rules this file exists to enforce:
 *
 * 1. **No `user_id` in any request.** The backend resolves the account from the
 *    verified bearer token. A client-supplied id would be ignored at best and a
 *    cross-account access bug at worst, so it is not part of any signature here.
 * 2. **One token source.** The `Authorization` header is attached here from the
 *    token provider, never assembled by a caller.
 */

import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'

import type { AuthConfig } from '@/types'

/**
 * Base URL handling.
 *
 * In development, requests go to the Vite dev server which proxies `/api` to the
 * backend (see `vite.config.ts`). That keeps the browser on one origin, so no
 * CORS preflight. An absolute URL is only used when one is configured for real,
 * which is the deployment case (separate API host).
 */
const configuredBase = import.meta.env?.VITE_API_BASE_URL as string | undefined

export const API_BASE_URL = (configuredBase ?? '').replace(/\/$/, '')

/** Supplies a fresh bearer token, or null when signed out. */
export type TokenProvider = () => string | null

/** Called when the API rejects our token, so the app can sign out. */
export type UnauthorizedHandler = () => void

let getToken: TokenProvider = () => null
let onUnauthorized: UnauthorizedHandler = () => {}

/**
 * Register the token source.
 *
 * Kept as a module-level setter rather than an axios instance factory because
 * the Firebase token changes while the app is running and the axios instance is
 * created once at import time.
 */
export function configureAuth(provider: TokenProvider, onUnauthorizedFn: UnauthorizedHandler): void {
  getToken = provider
  onUnauthorized = onUnauthorizedFn
}

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  /**
   * Unauthenticated requests must not carry a bearer token.
   *
   * `/api/auth/config` is called before sign-in and would otherwise send a stale
   * token if one were still around - which the backend answers with a 401 and
   * triggers a pointless sign-out.
   */
  if ((config as { skipAuth?: boolean }).skipAuth) {
    config.headers.delete('Authorization')
    return config
  }

  const token = getToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    /**
     * Only a 401 triggers sign-out. A 403 or 404 is a real answer about a
     * specific request and must not destroy the session.
     */
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      onUnauthorized()
    }
    return Promise.reject(error)
  },
)

/**
 * A validation error from FastAPI, normalised into one readable sentence.
 *
 * FastAPI returns `detail` as a string for HTTPException but as a list of
 * `{loc, msg}` objects for a 422. Components need to show one message, and a
 * raw array renders as "[object Object]".
 */
export interface FieldError {
  field: string
  message: string
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  readonly fields: FieldError[]

  constructor(message: string, status: number, detail: string, fields: FieldError[]) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.fields = fields
  }

  /** True when the failure is the network being absent, not the server saying no. */
  get isNetworkError(): boolean {
    return this.status === 0
  }

  get isAuthError(): boolean {
    return this.status === 401 || this.status === 403
  }
}

function parseDetail(data: unknown): { detail: string; fields: FieldError[] } {
  if (typeof data === 'string') {
    return { detail: data, fields: [] }
  }
  if (data && typeof data === 'object' && 'detail' in data) {
    const detail = (data as { detail: unknown }).detail

    if (typeof detail === 'string') {
      return { detail, fields: [] }
    }

    if (Array.isArray(detail)) {
      const fields: FieldError[] = []
      for (const entry of detail) {
        if (entry && typeof entry === 'object') {
          const { loc, msg } = entry as { loc?: unknown[]; msg?: unknown }
          const field = Array.isArray(loc) ? loc.filter((p) => p !== 'body').join('.') : ''
          if (typeof msg === 'string') {
            fields.push({ field, message: msg })
          }
        }
      }
      if (fields.length > 0) {
        return {
          detail: fields.map((f) => (f.field ? `${f.field}: ${f.message}` : f.message)).join('; '),
          fields,
        }
      }
    }

    return { detail: 'The request could not be completed.', fields: [] }
  }
  return { detail: 'The request could not be completed.', fields: [] }
}

/**
 * Perform a request and unwrap it, turning any failure into an `ApiError`.
 *
 * Components use this rather than `api.get(...)` so no `.data` unwrap is
 * forgotten and every thrown value has the same shape.
 */
export async function request<T>(
  config: AxiosRequestConfig,
  options: { skipAuth?: boolean } = {},
): Promise<T> {
  try {
    /**
     * `skipAuth` is a client-side marker, read by the request interceptor and
     * stripped before the adapter sees it. It rides along on the config object
     * because axios offers no other channel for per-request behaviour, and the
     * adapter ignores unknown keys.
     */
    const response = await api.request<T>({
      ...config,
      skipAuth: options.skipAuth,
    } as AxiosRequestConfig & { skipAuth?: boolean })
    return response.data
  } catch (error) {
    /**
     * `isAxiosError` rather than `instanceof AxiosError`.
     *
     * `instanceof` compares class identities, so it silently fails whenever a
     * second copy of axios is resolved - a common outcome of mixed CJS/ESM
     * resolution in bundlers and test runners - and then a network failure
     * would surface as a raw "Network Error" instead of a readable message.
     * The flag is set by axios itself and survives module duplication.
     */
    if (axios.isAxiosError(error)) {
      if (error.response) {
        const { detail, fields } = parseDetail(error.response.data)
        throw new ApiError(detail, error.response.status, detail, fields)
      }
      /**
       * No response object: the request never reached the server.
       *
       * `detail` is set to the same readable text as the message rather than
       * axios's raw "Network Error". `detail` is what every screen renders, so a
       * terse axios string would be what the user sees.
       */
      const readable =
        error.code === 'ECONNABORTED'
          ? 'The request timed out.'
          : 'Could not reach the server. Check that the API is running.'
      throw new ApiError(readable, 0, readable, [])
    }
    throw error
  }
}

/**
 * Query parameters.
 *
 * Values are deliberately restricted to the scalars axios can serialise. Using
 * `unknown` here would let an object or array reach the query string, where it
 * would be stringified as "[object Object]" and silently match nothing.
 */
export type QueryValue = string | number | boolean | null | undefined

export type QueryParams = Record<string, QueryValue>

/** Accepts a typed object as well as a loose record. */
export type QueryInput =
  | QueryParams
  | ({ [key: string]: QueryValue } & Record<string, unknown>)
  | undefined

/** Drop absent values so they do not become "match nothing" query filters. */
export function cleanParams(params?: QueryInput): QueryParams {
  const clean: QueryParams = {}
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === '') continue
    clean[key] = value as QueryValue
  }
  return clean
}

/** The auth configuration endpoint is deliberately unauthenticated. */
export async function fetchAuthConfig(): Promise<AuthConfig> {
  return request<AuthConfig>({ method: 'GET', url: '/api/auth/config' }, { skipAuth: true })
}

export const get = <T>(url: string, params?: QueryInput): Promise<T> =>
  request<T>({ method: 'GET', url, params: cleanParams(params) })

export const post = <T>(url: string, data?: unknown): Promise<T> =>
  request<T>({ method: 'POST', url, data })

export const patch = <T>(url: string, data?: unknown): Promise<T> =>
  request<T>({ method: 'PATCH', url, data })

export const del = <T>(url: string): Promise<T> => request<T>({ method: 'DELETE', url })
