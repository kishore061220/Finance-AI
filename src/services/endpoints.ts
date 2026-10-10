/**
 * Typed API surface.
 *
 * The only place that knows API URLs and query-string shapes. Screens call these
 * wrappers, never `http.get` with a hand-written path, so a route change is a
 * one-file change and a typo is a type error rather than a 404 at runtime.
 *
 * Nothing here sends a user id. Every endpoint is scoped by the bearer token on
 * the request interceptor in `services/api.ts`.
 */

import { http } from './api';
import type {
  AssistantConfig,
  AssistantRequest,
  AssistantResponse,
  AuthConfig,
  BackupListResponse,
  Budget,
  BudgetCreate,
  BudgetListResponse,
  BudgetUpdate,
  CategorizeResponse,
  DashboardResponse,
  EmiResponse,
  FamilyGroup,
  FamilyMember,
  FraudAlert,
  FraudAlertListResponse,
  FraudAlertUpdate,
  FraudSummary,
  Loan,
  LoanCreate,
  LoanDetail,
  LoanPayment,
  LoanPortfolio,
  LoanUpdate,
  MlStatusResponse,
  NotificationItem,
  OcrParseResponse,
  PredictionResponse,
  PrepaymentEffect,
  ReportRecord,
  ReportRequest,
  ReportTypes,
  SmsParseResponse,
  Transaction,
  TransactionCreate,
  TransactionFilters,
  TransactionPage,
  TransactionUpdate,
  UnreadCountResponse,
  UserProfileResponse,
  UserResponse,
  UserUpdate,
} from '../types';

type QueryValue = string | number | boolean | null | undefined;

/**
 * Drop empty values before they reach the wire.
 *
 * Axios serialises `undefined` out but happily sends `null` and `''` as literal
 * query parameters, which FastAPI then rejects for a typed parameter such as
 * `page_size` or `transaction_type`. A blank filter must mean "not supplied".
 */
export function cleanQuery(params?: Record<string, QueryValue>): Record<string, QueryValue> {
  if (!params) return {};
  const out: Record<string, QueryValue> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    out[key] = value;
  }
  return out;
}

// ---------------------------------------------------------------- auth

export const authApi = {
  /**
   * Which provider the server uses. Sent without a token: it runs before a
   * session exists, and attaching a stale one would invite a 401 that looks like
   * an expired session.
   */
  config: () => http.get<AuthConfig>('/api/auth/config', undefined, { skipAuth: true }),

  me: () => http.get<UserResponse>('/api/auth/me'),

  profile: () => http.get<UserProfileResponse>('/api/auth/profile'),

  updateProfile: (changes: UserUpdate) => http.patch<UserResponse>('/api/auth/profile', changes),

  /** Best-effort acknowledgement so the server records the sign-out. */
  logout: () => http.post<{ signed_out: boolean }>('/api/auth/logout'),
};

// ---------------------------------------------------------------- dashboard

export const dashboardApi = {
  /**
   * The full dashboard for one calendar month.
   *
   * `month`/`year`, not `start_date`/`end_date`: the route derives the period
   * itself so that category shares, budget progress and the monthly trend all
   * cover exactly the same window. Passing raw bounds would leave the response's
   * own parts disagreeing with each other.
   */
  overview: (params?: { month?: number; year?: number }) =>
    http.get<DashboardResponse>('/api/dashboard', cleanQuery(params)),

  prediction: () => http.get<PredictionResponse>('/api/dashboard/prediction'),

  /**
   * There are no separate `/insights` or `/recurring` routes. Both arrive inside
   * `overview`, because they are computed from the same transaction set; calling
   * them separately would either 404 or re-fetch a wider set to produce less.
   */
};

// ---------------------------------------------------------------- transactions

export const transactionApi = {
  list: (filters?: TransactionFilters) =>
    http.get<TransactionPage>('/api/transactions', cleanQuery(filters as Record<string, QueryValue>)),

  get: (id: number) => http.get<Transaction>(`/api/transactions/${id}`),

  create: (payload: TransactionCreate) => http.post<Transaction>('/api/transactions', payload),

  update: (id: number, changes: TransactionUpdate) =>
    http.patch<Transaction>(`/api/transactions/${id}`, changes),

  /** The API returns 204 with no body, so there is nothing to return. */
  remove: (id: number) => http.delete<void>(`/api/transactions/${id}`),
};

// ---------------------------------------------------------------- budgets

export const budgetApi = {
  list: (month?: number, year?: number) =>
    http.get<BudgetListResponse>('/api/budgets', cleanQuery({ month, year })),

  create: (payload: BudgetCreate) => http.post<Budget>('/api/budgets', payload),

  update: (id: number, changes: BudgetUpdate) => http.patch<Budget>(`/api/budgets/${id}`, changes),

  remove: (id: number) => http.delete<void>(`/api/budgets/${id}`),
};

// ---------------------------------------------------------------- fraud

export const fraudApi = {
  /**
   * Alert list, filtered server-side.
   *
   * `unread_only` rather than `is_read`, and no `is_read=false` encoding: the
   * route takes booleans, so sending a filter the route does not declare is
   * silently ignored and would look like an empty filter that is not applied.
   * Dismissed alerts are excluded unless explicitly asked for.
   */
  alerts: (params?: {
    risk_level?: string;
    unread_only?: boolean;
    include_dismissed?: boolean;
    sort?: string;
    limit?: number;
    offset?: number;
  }) => http.get<FraudAlertListResponse>('/api/fraud/alerts', cleanQuery(params)),

  summary: () => http.get<FraudSummary>('/api/fraud/summary'),

  markRead: (id: number) => http.post<FraudAlert>(`/api/fraud/alerts/${id}/read`),

  dismiss: (id: number) => http.post<FraudAlert>(`/api/fraud/alerts/${id}/dismiss`),

  update: (id: number, changes: FraudAlertUpdate) =>
    http.patch<FraudAlert>(`/api/fraud/alerts/${id}`, changes),
};

// ---------------------------------------------------------------- capture

/**
 * SMS and receipt capture.
 *
 * `parse` and `commit` are separate on the API on purpose: the parse returns a
 * proposal with a confidence score, and only `commit` writes. The screens show
 * the parsed fields for confirmation rather than trusting the parser blindly.
 */
export const captureApi = {
  categories: () => http.get<Record<string, unknown>>('/api/categorization/categories'),

  parseSms: (rawText: string) =>
    http.post<SmsParseResponse>('/api/categorization/sms/parse', { raw_text: rawText }),

  commitSms: (rawText: string) =>
    http.post<{ transaction_id: number }>('/api/categorization/sms/commit', { raw_text: rawText }),

  /** `text` is what on-device OCR read from the photo. */
  parseOcr: (text: string) =>
    http.post<OcrParseResponse>('/api/categorization/ocr/parse', { text }),

  commitOcr: (text: string) =>
    http.post<{ transaction_ids: number[] }>('/api/categorization/ocr/commit', { text }),

  predictCategory: (payload: { merchant?: string; description?: string; amount?: string }) =>
    http.post<CategorizeResponse>('/api/categorization/predict', payload),
};

// ---------------------------------------------------------------- loans

export const loanApi = {
  list: (status?: string) => http.get<Loan[]>('/api/loans', cleanQuery({ status })),

  /**
   * Detail, which is the loan plus its summary and upcoming instalments.
   *
   * There is no separate summary endpoint: `LoanDetailResponse` carries
   * `summary` and `upcoming` alongside the loan fields, so this is the only call
   * needed for a detail screen.
   */
  get: (id: number) => http.get<LoanDetail>(`/api/loans/${id}`),

  create: (payload: LoanCreate) => http.post<LoanDetail>('/api/loans', payload),

  update: (id: number, changes: LoanUpdate) => http.patch<Loan>(`/api/loans/${id}`, changes),

  remove: (id: number) => http.delete<void>(`/api/loans/${id}`),

  schedule: (id: number) => http.get<LoanPayment[]>(`/api/loans/${id}/payments`),

  portfolio: () => http.get<LoanPortfolio>('/api/loans/portfolio'),

  /** Announced in the API, useful for a savings pitch before a loan is created. */
  calculateEmi: (payload: {
    principal: string;
    annual_rate: string;
    tenure_months: number;
    include_schedule?: boolean;
  }) => http.post<EmiResponse>('/api/loans/emi/calculate', payload),

  prepayment: (id: number, amount: string) =>
    http.get<PrepaymentEffect>(`/api/loans/${id}/prepayment`, cleanQuery({ amount })),
};

// ---------------------------------------------------------------- notifications

export const notificationApi = {
  unreadCount: () => http.get<UnreadCountResponse>('/api/notifications/unread-count'),

  list: (page = 1, pageSize = 25) =>
    http.get<{ items: NotificationItem[]; total: number; unread: number }>(
      '/api/notifications',
      cleanQuery({ page, page_size: pageSize }),
    ),

  markRead: (id: number) => http.post<NotificationItem>(`/api/notifications/${id}/read`),

  markAllRead: () => http.post<{ updated: number }>('/api/notifications/read-all'),

  /** Registers this device for push. The token comes from the FCM SDK. */
  registerDevice: (token: string, platform: 'ANDROID' | 'IOS') =>
    http.post<{ registered: boolean }>('/api/notifications/devices', {
      token,
      platform,
    }),

  unregisterDevice: (id: number) => http.delete<void>(`/api/notifications/devices/${id}`),
};

// ---------------------------------------------------------------- ml

export const mlApi = {
  status: () => http.get<MlStatusResponse>('/api/ml/status'),
};

// ---------------------------------------------------------------- backups

export const backupApi = {
  list: () => http.get<BackupListResponse>('/api/backups'),
};

// ---------------------------------------------------------------- reports

export const reportApi = {
  types: () => http.get<ReportTypes>('/api/reports/types'),

  /**
   * Generates a report and streams the file back.
   *
   * The response body is a binary download, not JSON, so it is requested as an
   * array buffer and never `JSON.parse`d. The generation is still recorded in the
   * history, which `list` reads back.
   */
  generate: (payload: ReportRequest) =>
    http.post<ArrayBuffer>('/api/reports/generate', payload, { responseType: 'arraybuffer' }),

  list: (params?: { report_type?: string; limit?: number }) =>
    http.get<ReportRecord[]>('/api/reports', cleanQuery(params as Record<string, QueryValue>)),
};

// ---------------------------------------------------------------- assistant

export const assistantApi = {
  config: () => http.get<AssistantConfig>('/api/assistant/config'),

  ask: (payload: AssistantRequest) => http.post<AssistantResponse>('/api/assistant', payload),
};

// ---------------------------------------------------------------- family

export const familyApi = {
  groups: () => http.get<FamilyGroup[]>('/api/family'),

  create: (payload: { name: string; description?: string }) =>
    http.post<FamilyGroup>('/api/family', payload),

  members: (groupId: number) => http.get<FamilyMember[]>(`/api/family/${groupId}/members`),

  invite: (groupId: number, email: string, canViewAll = false) =>
    http.post<FamilyMember>(`/api/family/${groupId}/members`, {
      email,
      can_view_all: canViewAll,
    }),
};
