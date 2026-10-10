/**
 * Wire-level types, mirrored from the backend's Pydantic schemas.
 *
 * These exist so a contract change shows up as a type error here rather than as
 * `undefined` in a rendered chart. Field names and nullability must match
 * `app/schemas/*.py`.
 */

export type TransactionType = 'income' | 'expense'

export type TransactionSource = 'MANUAL' | 'SMS' | 'OCR' | 'IMPORT'

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type DetectionLayer = 'RULES' | 'ML' | 'COMBINED'

export interface UserResponse {
  id: number
  name: string
  email: string | null
  role: string
  is_active: boolean
  email_verified: boolean
  phone_number: string | null
  created_at: string | null
  last_login_at: string | null
}

export interface UserProfileResponse extends UserResponse {
  transaction_count: number
  budget_count: number
  family_count: number
  loan_count: number
}

export interface TotalsResponse {
  income: string
  expense: string
  net: string
  savings_rate_percent: number
}

export interface CategoryBreakdown {
  category: string
  amount: string
  percent: number
}

export interface MerchantBreakdown {
  merchant: string
  amount: string
}

export interface MonthlyTrend {
  year: number
  month: number
  label: string
  income: string
  expense: string
  net: string
}

export interface BudgetProgress {
  budget_id: number
  category: string
  month: number
  year: number
  limit: string
  spent: string
  remaining: string
  used_percent: number
  status: string
}

export interface Insight {
  type: string
  severity: string
  title: string
  message: string
  data: Record<string, unknown>
}

export interface Recurring {
  merchant: string
  occurrences: number
  average_amount: string
  coefficient_of_variation: number
  monthly_cost: string
  annual_cost: string
}

export interface FraudSummary {
  total: number
  unread: number
}

export interface DashboardResponse {
  totals: TotalsResponse
  category_breakdown: CategoryBreakdown[]
  top_merchants: MerchantBreakdown[]
  budget_progress: BudgetProgress[]
  monthly_trend: MonthlyTrend[]
  insights: Insight[]
  fraud_summary: FraudSummary
  recurring: Recurring[]
  generated_at: string
}

export interface Transaction {
  id: number
  user_id: number
  transaction_type: TransactionType
  amount: string
  category: string
  emi_type: string | null
  merchant: string | null
  description: string | null
  transaction_date: string
  source: TransactionSource
  bank_reference: string | null
  raw_source_text: string | null
  categorization_source: string | null
  fraud_score: number | null
  is_flagged: boolean
  created_at: string | null
  updated_at: string | null
}

export interface TransactionListResponse {
  items: Transaction[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface TransactionCreate {
  transaction_type: TransactionType
  amount: string
  category: string
  emi_type?: string | null
  merchant?: string | null
  description?: string | null
  transaction_date: string
  source?: TransactionSource
  bank_reference?: string | null
}

export interface TransactionUpdate {
  transaction_type?: TransactionType
  amount?: string
  category?: string
  emi_type?: string | null
  merchant?: string | null
  description?: string | null
  transaction_date?: string
}

export interface TransactionFilters {
  transaction_type?: TransactionType | ''
  category?: string
  emi_type?: string
  merchant?: string
  start_date?: string
  end_date?: string
  min_amount?: string
  max_amount?: string
  flagged_only?: boolean
  search?: string
  page?: number
  page_size?: number
  sort?: string
}

export interface BudgetListResponse {
  items: BudgetProgress[]
  total: number
  month: number
  year: number
}

export interface BudgetCreate {
  category: string
  amount: string
  month: number
  year: number
}

export interface FraudAlert {
  id: number
  user_id: number
  transaction_id: number | null
  risk_score: number
  risk_level: RiskLevel
  is_fraud: boolean
  detection_layer: DetectionLayer
  reasons: string[] | null
  amount_snapshot: string | null
  merchant_snapshot: string | null
  category_snapshot: string | null
  is_read: boolean
  is_dismissed: boolean
  created_at: string | null
}

export interface FraudAlertListResponse {
  items: FraudAlert[]
  total: number
  unread: number
  by_level: Record<string, number>
}

export interface ForecastRange {
  low: string
  high: string
}

export interface Forecast {
  month: number
  year: number
  label: string
  predicted_expense: string
  range: ForecastRange
  average_monthly_expense: string
  months_of_history: number
  volatility: string
  basis: string
  notes: string[]
}

export interface CategoryForecast {
  category: string
  total: string
  average_per_month: string
}

export interface BudgetProjection {
  category: string
  budget: string
  spent: string
  projected: string
  over_projected: boolean
  projected_ratio: number
}

export interface HistoryPoint {
  label: string
  expense: string
}

/**
 * `status` is deliberately carried through rather than assumed.
 *
 * The backend returns `insufficient_data` with HTTP 200 and no `prediction`
 * object when there is not enough history. Rendering `prediction.predicted_expense`
 * without checking this produces "undefined" on screen, and quietly pretending
 * to a number the model did not produce is worse than saying nothing.
 */
export interface PredictionResponse {
  status: string
  message: string
  prediction: Forecast | null
  required_months: number
  available_months: number
  months_needed: number
  observed_average: string | null
  history: HistoryPoint[]
  categories: CategoryForecast[]
  budget_projection: BudgetProjection[]
}

export interface Loan {
  id: number
  user_id: number
  name: string
  lender: string | null
  loan_type: string
  principal: string
  interest_rate: string
  tenure_months: number
  monthly_emi: string
  total_payable: string
  start_date: string
  status: string
  notes: string | null
  created_at: string | null
}

export interface LoanSummary {
  loan_id: number
  total_due: string
  total_paid: string
  outstanding: string
  installments_paid: number
  installments_total: number
  overdue_count: number
  principal_repaid: string
  completion_percent: number
  next_due_date: string | null
}

export interface LoanDetail extends Loan {
  summary: LoanSummary
  upcoming: Record<string, unknown>[]
}

export interface FamilyGroup {
  id: number
  name: string
  owner_id: number
  description: string | null
  is_active: boolean
  member_count: number
  created_at: string | null
}

export interface FamilyMember {
  id: number
  family_id: number
  user_id: number | null
  invited_email: string | null
  name: string | null
  role: string
  status: string
  can_view_all: boolean
  joined_at: string | null
}

export interface NotificationItem {
  id: number
  notification_type: string
  title: string
  body: string
  data: Record<string, unknown> | null
  is_read: boolean
  read_at: string | null
  deep_link: string | null
  created_at: string | null
}

export interface NotificationListResponse {
  items: NotificationItem[]
  total: number
  unread: number
  page: number
  page_size: number
}

export interface BackupStatus {
  id: number
  provider: string
  status: string
  remote_path: string | null
  remote_url: string | null
  record_count: number | null
  size_bytes: number | null
  checksum: string | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string | null
}

export interface BackupListResponse {
  items: BackupStatus[]
  total: number
  provider: string | null
  configured: boolean
  message: string
}

export interface RestoreTablePlan {
  table: string
  inserts: number
  updates: number
  skips: number
  conflicts: number
  notes: string[]
}

export interface RestoreResponse {
  backup_id: number
  backup_version: number
  generated_at: string | null
  checksum_verified: boolean
  checksum: string
  tables: RestoreTablePlan[]
  totals: {
    inserts: number
    updates: number
    skips: number
    conflicts: number
  }
  warnings: string[]
  applied: boolean
}

export interface MlStatus {
  model_loaded: boolean
  model: string | null
  trained_at: string | null
  features: string[]
  error: string
}

export interface AuthConfig {
  provider: 'firebase' | 'dev' | 'unconfigured'
  firebase_enabled: boolean
  registration_enabled: boolean
  app_env: string
  /** The Firebase project id the backend verifies, when it is on Firebase. */
  project_id?: string | null
}
