/**
 * Endpoint wrapper behaviour.
 *
 * Two properties matter and are easy to regress: empty filters must not reach the
 * wire (FastAPI rejects a blank typed query parameter), and no wrapper may send a
 * user id - ownership comes from the bearer token alone.
 */

import { api } from '../src/services/api';
import {
  authApi,
  budgetApi,
  captureApi,
  cleanQuery,
  dashboardApi,
  fraudApi,
  loanApi,
  notificationApi,
  transactionApi,
} from '../src/services/endpoints';

const captured: { url?: string; method?: string; params?: unknown; data?: unknown }[] = [];

beforeEach(() => {
  captured.length = 0;
  api.defaults.adapter = (async (config: (typeof captured)[number]) => {
    captured.push(config);
    return { data: {}, status: 200, statusText: 'OK', headers: {}, config };
  }) as never;
});

/**
 * The request body as an object.
 *
 * Axios serialises `data` to JSON before the adapter runs, so the adapter sees a
 * string. Parsing it back keeps the assertions readable and mirrors what the server
 * actually receives.
 */
function body(index = 0): Record<string, unknown> {
  const raw = captured[index].data;
  return typeof raw === 'string' ? JSON.parse(raw) : (raw as Record<string, unknown>);
}

describe('cleanQuery', () => {
  it('drops undefined, null and empty string', () => {
    expect(
      cleanQuery({ page: 2, search: '', type: undefined, flagged: null }),
    ).toEqual({ page: 2 });
  });

  it('keeps false and zero, which are meaningful values', () => {
    // A dropped `false` would turn "include dismissed" into "exclude dismissed".
    expect(cleanQuery({ unread_only: false, offset: 0 })).toEqual({
      unread_only: false,
      offset: 0,
    });
  });

  it('returns an empty object for no params', () => {
    expect(cleanQuery()).toEqual({});
  });
});

describe('budgets', () => {
  it('omits the period when none is given, so the server answers for the current month', async () => {
    await budgetApi.list();

    expect(captured[0].params).toEqual({});
  });

  it('sends the period when one is given', async () => {
    await budgetApi.list(3, 2026);

    expect(captured[0].params).toEqual({ month: 3, year: 2026 });
  });
});

describe('transactions', () => {
  it('omits filters that are not set', async () => {
    await transactionApi.list({
      page: 1,
      page_size: 25,
      search: '',
      transaction_type: undefined,
      flagged_only: false,
    });

    expect(captured[0].params).toEqual({ page: 1, page_size: 25, flagged_only: false });
  });

  it('never sends a user id', async () => {
    await transactionApi.create({
      transaction_type: 'expense',
      amount: '100.00',
      category: 'Food',
      transaction_date: '2026-01-31T00:00:00',
    });

    expect(JSON.stringify(captured[0].data)).not.toContain('user_id');
  });
});

describe('fraud alerts', () => {
  it('asks for dismissed alerts only when the caller wants them', async () => {
    await fraudApi.alerts();
    expect(captured[0].params).toEqual({});

    await fraudApi.alerts({ include_dismissed: true, risk_level: 'HIGH' });
    expect(captured[1].params).toEqual({ include_dismissed: true, risk_level: 'HIGH' });
  });
});

describe('loans', () => {
  it('reads the portfolio from the route that returns it', async () => {
    await loanApi.portfolio();

    expect(captured[0].url).toBe('/api/loans/portfolio');
  });

  it('sends the prepayment amount as a query parameter', async () => {
    await loanApi.prepayment(3, '50000');

    expect(captured[0].url).toBe('/api/loans/3/prepayment');
    expect(captured[0].params).toEqual({ amount: '50000' });
  });
});

describe('dashboard', () => {
  it('requests the period as month and year', async () => {
    await dashboardApi.overview({ month: 2, year: 2026 });

    expect(captured[0].url).toBe('/api/dashboard');
    expect(captured[0].params).toEqual({ month: 2, year: 2026 });
  });
});

describe('capture', () => {
  it('parses an SMS without committing it', async () => {
    await captureApi.parseSms('INR 450 debited at SWIGGY');

    expect(captured[0].url).toBe('/api/categorization/sms/parse');
    expect(String(captured[0].method).toUpperCase()).toBe('POST');
    expect(body()).toEqual({ raw_text: 'INR 450 debited at SWIGGY' });
  });

  it('sends recognised OCR text, not an image', async () => {
    await captureApi.parseOcr('SWIGGY\nTOTAL 308.00');

    expect(captured[0].url).toBe('/api/categorization/ocr/parse');
    expect(JSON.stringify(captured[0].data)).toContain('SWIGGY');
    expect(JSON.stringify(captured[0].data)).not.toContain('base64');
  });
});

describe('notifications', () => {
  it('registers a device with the platform the app runs on', async () => {
    await notificationApi.registerDevice('fcm-token', 'ANDROID');

    expect(captured[0].url).toBe('/api/notifications/devices');
    expect(body()).toEqual({ token: 'fcm-token', platform: 'ANDROID' });
  });
});

describe('auth config', () => {
  it('requests the provider config without a token', async () => {
    await authApi.config();

    expect(captured[0].url).toBe('/api/auth/config');
  });

  it('mints a dev token for a subject derived from the email', async () => {
    await authApi.devToken('dev@example.com');

    expect(captured[0].url).toBe('/api/auth/dev-token');
    expect(body()).toMatchObject({ subject: 'dev-dev@example.com' });
  });
});
