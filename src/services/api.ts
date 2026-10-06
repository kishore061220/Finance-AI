/**
 * HTTP client.
 *
 * One axios instance for the whole app. It owns three things:
 *
 *  - the base URL, from `src/config`
 *  - attachment of the bearer token on every request
 *  - translation of transport and HTTP failures into a single `ApiError` shape,
 *    so screens never have to reach into `error.response`
 *
 * Ownership is derived from that bearer token by the backend. Nothing in this
 * app may send or read a user id to decide whose data to show.
 */

import axios, {
  AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios';

import { API_BASE_URL } from '../config';

/** A validation error returned by FastAPI, keyed by the field that failed. */
export interface FieldError {
  loc: (string | number)[];
  msg: string;
  type: string;
}

interface FastAPIErrorBody {
  detail?: string | FieldError[];
  message?: string;
}

/**
 * Normalised API failure.
 *
 * `status` is 0 when the request never reached the server, which is how a
 * caller distinguishes "the API is down" from "the API said no".
 */
export class ApiError extends Error {
  readonly status: number;
  readonly fieldErrors: FieldError[];

  constructor(message: string, status: number, fieldErrors: FieldError[] = []) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.fieldErrors = fieldErrors;
    // Restores the prototype chain, which is otherwise lost when a built-in is
    // subclassed and compiled to ES5-era output.
    Object.setPrototypeOf(this, ApiError.prototype);
  }

  /** True when the session is missing or no longer valid. */
  get isUnauthorized(): boolean {
    return this.status === 401 || this.status === 403;
  }

  /** True when nothing came back at all - no network, or the server never bound. */
  get isOffline(): boolean {
    return this.status === 0;
  }

  /**
   * Field errors keyed by the last path segment of `loc`, which is the field
   * name for body and query validation errors.
   */
  byField(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const error of this.fieldErrors) {
      const key = error.loc[error.loc.length - 1];
      if (typeof key === 'string') out[key] = error.msg;
    }
    return out;
  }
}

/**
 * Holds the current token.
 *
 * A mutable module-level holder rather than a React value, because the axios
 * interceptor is not a component and re-registering it on every token change
 * would drop requests in flight.
 */
let tokenRef: string | null = null;
/** Called when the API rejects the token, so the session can be torn down. */
let onUnauthorized: (() => void) | null = null;

export function setToken(token: string | null): void {
  tokenRef = token;
}

export function getToken(): string | null {
  return tokenRef;
}

/**
 * Register the handler invoked when the backend rejects the token.
 *
 * Kept separate from `setToken` because the session provider owns that policy,
 * and the client should not decide what "unauthorized" means for the UI.
 */
export function configureAuth(handlers: {
  getToken: () => string | null;
  onUnauthorized: () => void;
}): void {
  tokenRef = handlers.getToken();
  onUnauthorized = handlers.onUnauthorized;
}

/** Per-request opt-out from attaching the bearer token. */
export interface RequestOptions {
  /**
   * Send without an `Authorization` header.
   *
   * Needed for `/api/auth/config` and `/api/auth/dev-token`, which run before a
   * session exists. Attaching a stale token to those invites a 401 that would
   * be misread as an expired session.
   */
  skipAuth?: boolean;
}

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20_000,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const requestConfig = config as InternalAxiosRequestConfig & { skipAuth?: boolean };
  const skipAuth = requestConfig.skipAuth;
  // Removed rather than merely read: it is not an HTTP option, and leaving it on
  // the config that reaches the adapter makes a request log harder to interpret.
  delete requestConfig.skipAuth;

  if (skipAuth) {
    delete config.headers.Authorization;
    return config;
  }
  if (tokenRef) {
    config.headers.set('Authorization', `Bearer ${tokenRef}`);
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<FastAPIErrorBody>) => {
    if (error.response?.status === 401) {
      // The token was rejected. Tear the session down exactly once, at the
      // source, so no screen has to remember to check.
      onUnauthorized?.();
    }
    return Promise.reject(toApiError(error));
  },
);

function toApiError(error: AxiosError<FastAPIErrorBody>): ApiError {
  const response = error.response;

  if (!response) {
    // No response: DNS failure, refused connection, or the timeout above.
    return new ApiError(
      'Cannot reach the API. Check that the server is running and that the ' +
        'base URL is correct.',
      0,
    );
  }

  const body = response.data;
  const detail = body?.detail;
  const status = response.status;

  if (status >= 500) {
    // Checked before the body is read on purpose. A 5xx body is for the server log,
    // not the user: if it contains a traceback or an internal exception string,
    // surfacing it as a message would leak implementation detail. So the body of a
    // 5xx is never used, whatever shape it is.
    return new ApiError('The server ran into an error. Try again shortly.', status);
  }

  if (Array.isArray(detail)) {
    // FastAPI 422. The first message is the most specific one available, and the
    // full list stays available for field-level display.
    return new ApiError(detail[0]?.msg ?? 'Validation failed.', status, detail);
  }

  if (typeof detail === 'string' && detail.length > 0) {
    return new ApiError(detail, status);
  }

  if (body?.message) {
    return new ApiError(body.message, status);
  }

  return new ApiError(`Request failed (${status}).`, status);
}

/**
 * Perform a request and return only its body.
 *
 * `skipAuth` rides on the config object because axios exposes no other per-request
 * channel. The request interceptor reads and removes it before the adapter runs.
 */
export async function request<T>(
  config: AxiosRequestConfig,
  options: RequestOptions = {},
): Promise<T> {
  const response = await api.request<T>({
    ...config,
    skipAuth: options.skipAuth,
  } as AxiosRequestConfig & { skipAuth?: boolean });
  return response.data;
}

export const http = {
  get: <T>(url: string, params?: Record<string, unknown>, options?: RequestOptions) =>
    request<T>({ method: 'GET', url, params }, options),
  post: <T>(url: string, data?: unknown, options?: RequestOptions) =>
    request<T>({ method: 'POST', url, data }, options),
  put: <T>(url: string, data?: unknown, options?: RequestOptions) =>
    request<T>({ method: 'PUT', url, data }, options),
  patch: <T>(url: string, data?: unknown, options?: RequestOptions) =>
    request<T>({ method: 'PATCH', url, data }, options),
  delete: <T>(url: string, options?: RequestOptions) =>
    request<T>({ method: 'DELETE', url }, options),
};

/** Narrowing helper for `catch` blocks. */
export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** Best-effort message for any thrown value, including non-Error throws. */
export function errorMessage(error: unknown, fallback = 'Something went wrong.'): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}
