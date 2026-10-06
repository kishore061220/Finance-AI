/**
 * HTTP client behaviour.
 *
 * Exercised through a fake axios adapter rather than a mock of axios itself, so the
 * interceptors under test are the real ones: the assertions are about the headers
 * and errors a screen would actually receive.
 */

import { api, ApiError, http, setToken, configureAuth } from '../src/services/api';

interface CapturedConfig {
  url?: string;
  method?: string;
  headers: Record<string, string>;
  params?: unknown;
  data?: unknown;
  skipAuth?: boolean;
}

const captured: CapturedConfig[] = [];

/** Installs an adapter that records the request and replies with `response`. */
function mockAdapter(response: { status?: number; data?: unknown } = {}) {
  api.defaults.adapter = (async (config: CapturedConfig) => {
    captured.push(config);
    return {
      data: response.data ?? {},
      status: response.status ?? 200,
      statusText: 'OK',
      headers: {},
      config,
    };
  }) as never;
}

/** Installs an adapter that rejects the way axios rejects a failed response. */
function mockError(status: number, data?: unknown, withResponse = true) {
  api.defaults.adapter = (async (config: CapturedConfig) => {
    captured.push(config);
    const error: Record<string, unknown> = { message: 'failed', config };
    if (withResponse) {
      error.response = {
        data,
        status,
        statusText: 'Error',
        headers: {},
        config,
      };
    }
    throw error;
  }) as never;
}

beforeEach(() => {
  captured.length = 0;
  setToken(null);
  mockAdapter();
});

/**
 * Awaits a failing request and returns the normalised error.
 *
 * The `.catch` is typed so the tests read the same `ApiError` fields the UI does,
 * instead of casting at every call site.
 */
async function failure(action: () => Promise<unknown>): Promise<ApiError> {
  try {
    await action();
  } catch (cause) {
    return cause as ApiError;
  }
  throw new Error('Expected the request to fail, but it resolved.');
}

describe('Authorization header', () => {
  it('attaches the bearer token when one is set', async () => {
    setToken('token-abc');

    await http.get('/api/dashboard');

    expect(captured[0].headers.Authorization).toBe('Bearer token-abc');
  });

  it('omits the header when there is no token', async () => {
    await http.get('/api/dashboard');

    expect(captured[0].headers.Authorization).toBeUndefined();
  });

  it('sends no header for a skipAuth request even when a token is held', async () => {
    setToken('stale-token');

    await http.get('/api/auth/config', undefined, { skipAuth: true });

    expect(captured[0].headers.Authorization).toBeUndefined();
  });

  it('strips a stale Authorization header rather than leaving it in place', async () => {
    setToken('stale-token');
    // A pre-set header models axios reusing a config object across requests.
    api.defaults.headers.common = { Authorization: 'Bearer stale-token' } as never;

    await http.get('/api/auth/config', undefined, { skipAuth: true });

    expect(captured[0].headers.Authorization).toBeUndefined();
    api.defaults.headers.common = {} as never;
  });

  it('does not leave skipAuth on the config that reaches the adapter', async () => {
    await http.get('/api/auth/config', undefined, { skipAuth: true });

    expect(captured[0].skipAuth).toBeUndefined();
  });
});

describe('error normalisation', () => {
  it('reports an unreachable server as status 0', async () => {
    mockError(0, undefined, false);

    await expect(http.get('/api/dashboard')).rejects.toMatchObject({
      status: 0,
    });
  });

  it('marks status 0 as offline', async () => {
    mockError(0, undefined, false);

    const error = await failure(() => http.get('/api/dashboard'));

    expect(error.isOffline).toBe(true);
    expect(error.isUnauthorized).toBe(false);
  });

  it('passes through a string detail from the API', async () => {
    mockError(404, { detail: 'No such loan.' });

    const error = await failure(() => http.get('/api/loans/9'));

    expect(error.message).toBe('No such loan.');
    expect(error.status).toBe(404);
  });

  it('exposes a 422 field error list keyed by field name', async () => {
    mockError(422, {
      detail: [
        { loc: ['body', 'amount'], msg: 'ensure this value is greater than 0', type: 'value_error' },
        { loc: ['body', 'category'], msg: 'field required', type: 'missing' },
      ],
    });

    const error = await failure(() => http.post('/api/transactions', {}));

    expect(error.status).toBe(422);
    expect(error.byField()).toEqual({
      amount: 'ensure this value is greater than 0',
      category: 'field required',
    });
  });

  it('does not leak an internal server message', async () => {
    mockError(500, { detail: 'Traceback: sqlalchemy.exc.IntegrityError at /app/...' });

    const error = await failure(() => http.get('/api/dashboard'));

    expect(error.message).toBe('The server ran into an error. Try again shortly.');
    expect(error.message).not.toContain('Traceback');
  });

  it('treats 401 and 403 as an unauthorized session', async () => {
    mockError(403, { detail: 'Not allowed.' });

    const error = await failure(() => http.get('/api/dashboard'));

    expect(error.isUnauthorized).toBe(true);
  });
});

describe('unauthorized handling', () => {
  it('tears the session down exactly once on a 401', async () => {
    const onUnauthorized = jest.fn();
    configureAuth({ getToken: () => 'bad-token', onUnauthorized });
    mockError(401, { detail: 'Invalid token.' });

    await http.get('/api/dashboard').catch(() => undefined);

    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('does not tear the session down for a 500', async () => {
    const onUnauthorized = jest.fn();
    configureAuth({ getToken: () => 'good-token', onUnauthorized });
    mockError(500);

    await http.get('/api/dashboard').catch(() => undefined);

    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});

describe('request bodies', () => {
  it('returns only the response body', async () => {
    mockAdapter({ data: { unread: 3 } });

    await expect(http.get('/api/notifications/unread-count')).resolves.toEqual({ unread: 3 });
  });

  it('forwards query parameters', async () => {
    await http.get('/api/transactions', { page: 2, page_size: 25 });

    expect(captured[0].params).toEqual({ page: 2, page_size: 25 });
  });
});
