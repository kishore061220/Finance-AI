/**
 * Typed wrappers over the API's resource routes.
 *
 * Every function here mirrors one backend endpoint and returns the response
 * model as declared in `app/schemas/`. No endpoint takes a user id: ownership
 * comes from the bearer token.
 */

import { cleanParams, del, get, patch, post, request } from '@/lib/api'
import type {
  AuthConfig,
  BackupListResponse,
  BudgetCreate,
  BudgetListResponse,
  DashboardResponse,
  FamilyGroup,
  FamilyMember,
  FraudAlert,
  FraudAlertListResponse,
  Loan,
  LoanDetail,
  MlStatus,
  NotificationListResponse,
  PredictionResponse,
  RestoreResponse,
  Transaction,
  TransactionCreate,
  TransactionFilters,
  TransactionListResponse,
  TransactionUpdate,
  UserProfileResponse,
  UserResponse,
} from '@/types'

// ---------------------------------------------------------------- auth

export const authApi = {
  config: (): Promise<AuthConfig> =>
    request<AuthConfig>({ method: 'GET', url: '/api/auth/config' }, { skipAuth: true }),
  me: (): Promise<UserResponse> => get<UserResponse>('/api/auth/me'),
  profile: (): Promise<UserProfileResponse> => get<UserProfileResponse>('/api/auth/profile'),
  /**
   * `phone_number: null` clears the field. `UserUpdate` accepts null for that
   * one field, so the type reflects it rather than forcing a cast.
   */
  updateProfile: (changes: {
    name?: string
    phone_number?: string | null
  }): Promise<UserResponse> => patch<UserResponse>('/api/auth/profile', changes),
  /**
   * Acknowledges sign-out server-side so the audit trail is complete.
   * The token itself is discarded locally regardless of whether this succeeds.
   */
  logout: (): Promise<{ signed_out: boolean }> => post('/api/auth/logout'),
}

// ---------------------------------------------------------------- dashboard

/**
 * Declared as a type alias, not an interface.
 *
 * TypeScript gives a type alias an implicit index signature but not an
 * interface, so an interface here could not be passed as query params without a
 * cast at every call site.
 */
export type DashboardQuery = {
  start_date?: string
  end_date?: string
}

export const dashboardApi = {
  full: (query?: DashboardQuery): Promise<DashboardResponse> =>
    get<DashboardResponse>('/api/dashboard', query),
  categories: (query?: DashboardQuery): Promise<DashboardResponse['category_breakdown']> =>
    get('/api/dashboard/categories', query),
  trends: (query?: DashboardQuery): Promise<DashboardResponse['monthly_trend']> =>
    get('/api/dashboard/trends', query),
  insights: (query?: DashboardQuery): Promise<DashboardResponse['insights']> =>
    get('/api/dashboard/insights', query),
  prediction: (): Promise<PredictionResponse> => get<PredictionResponse>('/api/dashboard/prediction'),
  dataHealth: (): Promise<{ transaction_count: number; earliest: string | null; latest: string | null }> =>
    get('/api/dashboard/health'),
}

/**
 * Empty state for `prediction` responses.
 *
 * `insufficient_data` arrives as HTTP 200 with `prediction: null`. Returning null
 * lets the UI say "not enough history yet" instead of rendering `NaN`.
 */
/**
 * Extract a forecast, or null when the backend declined to produce one.
 *
 * The status string is checked rather than the presence of `prediction`. The
 * backend returns `"insufficient_data"` with a null prediction and HTTP 200, and
 * `"predicted"` with a forecast. Trusting the object alone would let a future
 * degraded-but-populated response render as if the model had spoken, so an
 * unrecognised status is treated as "no forecast" and the UI says so.
 */
export function extractForecast(response: PredictionResponse) {
  if (response.status !== 'predicted' || !response.prediction) {
    return null
  }
  return response.prediction
}

// ---------------------------------------------------------------- transactions

export const transactionApi = {
  list: (filters?: TransactionFilters): Promise<TransactionListResponse> => {
    /**
     * `flagged_only` is dropped when false on purpose: sending
     * `?flagged_only=false` is harmless, but omitting it keeps the query string
     * to only what the user actually asked for.
     */
    const params = cleanParams(filters as Record<string, string | number | boolean | undefined>)

    /**
     * `flagged_only=false` is dropped rather than sent.
     *
     * The backend default is already false, so sending it adds noise to the
     * query string and to server logs without changing the result. `true` is
     * kept.
     */
    if (!filters?.flagged_only) {
      delete params.flagged_only
    }

    return request<TransactionListResponse>({
      method: 'GET',
      url: '/api/transactions',
      params,
    })
  },
  get: (id: number): Promise<Transaction> => get<Transaction>(`/api/transactions/${id}`),
  create: (payload: TransactionCreate): Promise<Transaction> =>
    post<Transaction>('/api/transactions', payload),
  update: (id: number, payload: TransactionUpdate): Promise<Transaction> =>
    patch<Transaction>(`/api/transactions/${id}`, payload),
  remove: (id: number): Promise<{ deleted: boolean }> => del(`/api/transactions/${id}`),
}

// ---------------------------------------------------------------- budgets

export const budgetApi = {
  list: (month?: number, year?: number): Promise<BudgetListResponse> =>
    // Omitted params let the server default to the current period, which is
    // what the backend does and avoids duplicating "now" logic in two places.
    get<BudgetListResponse>('/api/budgets', { month, year }),
  create: (payload: BudgetCreate): Promise<unknown> => post('/api/budgets', payload),
  update: (id: number, payload: Partial<BudgetCreate>): Promise<unknown> =>
    patch(`/api/budgets/${id}`, payload),
  remove: (id: number): Promise<{ deleted: boolean }> => del(`/api/budgets/${id}`),
}

// ---------------------------------------------------------------- fraud

export const fraudApi = {
  alerts: (params?: { is_read?: boolean; risk_level?: string }): Promise<FraudAlertListResponse> =>
    get<FraudAlertListResponse>('/api/fraud/alerts', params),
  summary: (): Promise<{ total: number; unread: number }> => get('/api/fraud/summary'),
  markRead: (id: number): Promise<FraudAlert> =>
    post<FraudAlert>(`/api/fraud/alerts/${id}/read`),
  dismiss: (id: number): Promise<FraudAlert> =>
    post<FraudAlert>(`/api/fraud/alerts/${id}/dismiss`),
}

// ---------------------------------------------------------------- loans

export const loanApi = {
  list: (): Promise<Loan[]> => get<Loan[]>('/api/loans'),
  detail: (id: number): Promise<LoanDetail> => get<LoanDetail>(`/api/loans/${id}`),
  create: (payload: Record<string, unknown>): Promise<Loan> => post<Loan>('/api/loans', payload),
  remove: (id: number): Promise<{ deleted: boolean }> => del(`/api/loans/${id}`),
  calculateEmi: (payload: {
    principal: string
    annual_rate: string
    tenure_months: number
  }): Promise<{ monthly_emi: string; total_payable: string }> =>
    post('/api/loans/emi/calculate', payload),
}

// ---------------------------------------------------------------- family

export const familyApi = {
  groups: (): Promise<FamilyGroup[]> => get<FamilyGroup[]>('/api/family'),
  create: (payload: { name: string; description?: string }): Promise<FamilyGroup> =>
    post<FamilyGroup>('/api/family', payload),
  members: (groupId: number): Promise<FamilyMember[]> =>
    get<FamilyMember[]>(`/api/family/${groupId}/members`),
  invite: (groupId: number, email: string, canViewAll = false): Promise<FamilyMember> =>
    post<FamilyMember>(`/api/family/${groupId}/members`, { email, can_view_all: canViewAll }),
  removeMember: (groupId: number, memberId: number): Promise<unknown> =>
    del(`/api/family/${groupId}/members/${memberId}`),
}

// ---------------------------------------------------------------- notifications

export const notificationApi = {
  list: (page = 1): Promise<NotificationListResponse> =>
    get<NotificationListResponse>('/api/notifications', { page }),
  unreadCount: (): Promise<{ unread: number }> => get('/api/notifications/unread-count'),
  markRead: (id: number): Promise<unknown> => post(`/api/notifications/${id}/read`),
  markAllRead: (): Promise<unknown> => post('/api/notifications/read-all'),
}

// ---------------------------------------------------------------- backups

export const backupApi = {
  list: (): Promise<BackupListResponse> => get<BackupListResponse>('/api/backups'),
  create: (provider?: string): Promise<unknown> =>
    post('/api/backups', provider ? { provider } : {}),
  verify: (id: number): Promise<{ verified: boolean; checksum: string }> =>
    post(`/api/backups/${id}/verify`),
  restorePreview: (id: number): Promise<RestoreResponse> =>
    get<RestoreResponse>(`/api/backups/${id}/restore/preview`),
  restoreApply: (id: number): Promise<RestoreResponse> =>
    post<RestoreResponse>(`/api/backups/${id}/restore`, { confirm: true }),
}

// ---------------------------------------------------------------- ml

export const mlApi = {
  status: (): Promise<MlStatus> => get<MlStatus>('/api/ml/status'),
}

// ---------------------------------------------------------------- reports

/** A row from the report history (`ReportResponse`). */
export interface ReportRecord {
  id: number
  report_type: string
  report_format: string
  period_start: string | null
  period_end: string | null
  category: string | null
  row_count: number | null
  file_size_bytes: number | null
  created_at: string | null
}

export interface ReportRequest {
  report_type: string
  report_format: string
  period_start?: string
  period_end?: string
  category?: string
}

export const reportApi = {
  types: (): Promise<{ report_types: string[]; report_formats: string[] }> =>
    get('/api/reports/types'),
  generate: (payload: ReportRequest): Promise<Blob> =>
    request<Blob>({
      method: 'POST',
      url: '/api/reports/generate',
      data: payload,
      responseType: 'blob',
    }),
  list: (params?: { report_type?: string; limit?: number }): Promise<ReportRecord[]> =>
    get<ReportRecord[]>('/api/reports', params),
}

// ---------------------------------------------------------------- assistant

export interface AssistantRequest {
  message: string
  history?: Array<{ role: 'user' | 'assistant'; content: string }>
  include_context?: boolean
}

export const assistantApi = {
  config: (): Promise<{
    provider: string
    model: string | null
    remote_configured: boolean
    message: string
    suggestions: string[]
  }> => get('/api/assistant/config'),
  ask: (payload: AssistantRequest): Promise<{
    reply: string
    provider: string
    model: string | null
    context_used: string[]
    suggestions: string[]
    fallback: boolean
  }> => post('/api/assistant', payload),
}

// ---------------------------------------------------------------- categorization

export interface SmsParseResult {
  amount: string | null
  transaction_type: string | null
  merchant: string | null
  category: string | null
  transaction_date: string | null
  bank_reference: string | null
  confidence: number
  parser: string
  raw_text: string
  notes: string[]
}

export const categorizationApi = {
  categories: (): Promise<{ categories: string[] }> => get('/api/categorization/categories'),
  parseSms: (rawText: string): Promise<SmsParseResult> =>
    post<SmsParseResult>('/api/categorization/sms/parse', { raw_text: rawText }),
  commitSms: (rawText: string): Promise<{ transaction: Transaction }> =>
    post('/api/categorization/sms/commit', { raw_text: rawText }),
}
