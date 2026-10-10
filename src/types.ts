/**
 * Response shapes, mirroring the backend Pydantic schemas.
 *
 * Two conventions worth knowing before editing this file:
 *
 *  - Money arrives as a string. The API serialises `Numeric` to a string so JSON
 *    float rounding cannot corrupt a ledger. Parse with the helpers in
 *    `src/lib/format.ts` rather than with `parseFloat` on a raw field.
 *  - Absent values are typed `| null` rather than left optional, because the API
 *    serialises a missing value as an explicit `null`. Treating them as possibly
 *    absent would hide the real "present but empty" cases.
 *
 * `user_id` shows up in several payloads. It is never read on this side: the
 * backend scopes every query to the token's principal, so a client-supplied id
 * could not change what comes back even if one were sent.
 */

// ---------------------------------------------------------------- auth

export interface AuthConfig {
  /**
   * Three states, not two. The API answers `"unconfigured"` when Firebase is off
   * *and* dev auth is disabled, which is the correct production posture for a
   * misconfigured server. Treating that as `"dev"` would offer a sign-in button
   * that cannot work; treating it as `"firebase"` would offer a Firebase flow
   * against a server with no Firebase project.
   */
  provider: 'firebase' | 'dev' | 'unconfigured';
  firebase_enabled: boolean;
  /**
   * Mirrors `firebase_enabled` on the server: there is no separate self-service
   * registration route, so this tells the client whether to advertise sign-up.
   */
  registration_enabled: boolean;
  app_env: string;
  /**
   * The Firebase project id the server verifies tokens for, when it is on
   * Firebase. The client compares it against its own configured project so a
   * mismatched build can warn before a sign-in succeeds and then 401s.
   */
  project_id?: string | null;
}

export interface DevTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  provider: string;
}

export interface UserResponse {
  id: number;
  name: string;
  email: string | null;
  role: string;
  is_active: boolean;
  email_verified: boolean;
  phone_number: string | null;
  created_at: string | null;
  last_login_at: string | null;
}

/**
 * Profile counts, without `is_active`.
 *
 * The profile schema genuinely omits `is_active` - it is a different response
 * model from `UserResponse`, not a partial one. So `refreshUser` must not be used
 * to overwrite session state read from it.
 */
export interface UserProfileResponse {
  id: number;
  name: string;
  email: string | null;
  role: string;
  email_verified: boolean;
  phone_number: string | null;
  created_at: string | null;
  transaction_count: number;
  budget_count: number;
  family_count: number;
  loan_count: number;
}

export interface UserUpdate {
  name?: string;
  /**
   * `null` clears the field. An empty string is not the same thing: the API
   * would store a blank value the UI then has to hide.
   */
  phone_number?: string | null;
}

// ---------------------------------------------------------------- dashboard

export interface DashboardTotals {
  income: string;
  expense: string;
  net: string;
  savings_rate_percent: number;
}

export interface CategoryBreakdown {
  category: string;
  amount: string;
  percent: number;
}

export interface MerchantBreakdown {
  merchant: string;
  amount: string;
}

export interface MonthlyTrend {
  year: number;
  month: number;
  label: string;
  income: string;
  expense: string;
  net: string;
}

export interface Insight {
  type: string;
  severity: string;
  title: string;
  message: string;
  data: Record<string, unknown>;
}

export interface Recurring {
  merchant: string;
  occurrences: number;
  average_amount: string;
  coefficient_of_variation: number;
  monthly_cost: string;
  annual_cost: string;
}

export interface FraudSummary {
  total: number;
  unread: number;
}

export interface DashboardResponse {
  totals: DashboardTotals;
  category_breakdown: CategoryBreakdown[];
  top_merchants: MerchantBreakdown[];
  budget_progress: BudgetProgress[];
  monthly_trend: MonthlyTrend[];
  insights: Insight[];
  fraud_summary: FraudSummary;
  recurring: Recurring[];
  generated_at: string;
}

// ---------------------------------------------------------------- prediction

export interface ForecastRange {
  low: string;
  high: string;
}

export interface Forecast {
  month: number;
  year: number;
  label: string;
  predicted_expense: string;
  range: ForecastRange;
  average_monthly_expense: string;
  months_of_history: number;
  volatility: string;
  /** How the figure was derived, so the UI can show its provenance. */
  basis: string;
  notes: string[];
}

export interface HistoryPoint {
  label: string;
  expense: string;
}

export interface CategoryForecast {
  category: string;
  total: string;
  average_per_month: string;
}

export interface BudgetProjection {
  category: string;
  budget: string;
  spent: string;
  projected: string;
  over_projected: boolean;
  projected_ratio: number;
}

/**
 * The forecast contract.
 *
 * `status` is the thing to branch on: `"predicted"` when there is enough history
 * for a figure, `"insufficient_data"` when there is not. In the insufficient
 * case `prediction` is null rather than a fabricated number, so a client must
 * never read `prediction.predicted_expense` without checking `status`.
 */
export type PredictionStatus = 'predicted' | 'insufficient_data';

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export type DetectionLayer = 'RULES' | 'ML' | 'COMBINED';

export interface PredictionResponse {
  status: PredictionStatus;
  message: string;
  prediction: Forecast | null;
  required_months: number;
  available_months: number;
  months_needed: number;
  observed_average: string | null;
  history: HistoryPoint[];
  categories: CategoryForecast[];
  budget_projection: BudgetProjection[];
}

// ---------------------------------------------------------------- transactions

/**
 * Lowercase, matching the API's enum values.
 *
 * There is no `TRANSFER`: the API coerces the field and rejects anything else,
 * so a third variant here would only describe a request the server refuses.
 */
export type TransactionType = 'income' | 'expense';

export type TransactionSource = 'MANUAL' | 'SMS' | 'OCR' | 'IMPORT';

export interface Transaction {
  id: number;
  user_id: number;
  transaction_type: TransactionType;
  amount: string;
  category: string;
  emi_type: string | null;
  merchant: string | null;
  description: string | null;
  transaction_date: string;
  source: TransactionSource;
  bank_reference: string | null;
  raw_source_text: string | null;
  categorization_source: string | null;
  fraud_score: number | null;
  is_flagged: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface TransactionPage {
  items: Transaction[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

/** `transaction_date` is a datetime on the wire; send an ISO 8601 string. */
export interface TransactionCreate {
  transaction_type: TransactionType;
  amount: string;
  category: string;
  transaction_date: string;
  emi_type?: string | null;
  merchant?: string | null;
  description?: string | null;
  source?: TransactionSource;
  bank_reference?: string | null;
  raw_source_text?: string | null;
}

export type TransactionUpdate = Partial<TransactionCreate>;

/** Query filters accepted by `GET /api/transactions`. */
export interface TransactionFilters {
  transaction_type?: TransactionType;
  category?: string;
  emi_type?: string;
  merchant?: string;
  start_date?: string;
  end_date?: string;
  min_amount?: string;
  max_amount?: string;
  flagged_only?: boolean;
  search?: string;
  page?: number;
  page_size?: number;
  sort?: string;
}

export interface SmsParseResponse {
  amount: string | null;
  transaction_type: TransactionType | null;
  merchant: string | null;
  category: string | null;
  transaction_date: string | null;
  bank_reference: string | null;
  confidence: number;
  parser: string;
  raw_text: string;
  notes: string[];
}

export interface OcrLineItem {
  description: string;
  amount: string;
  transaction_type: TransactionType | null;
  date: string | null;
  confidence: number;
  raw_line: string;
}

/**
 * Receipt parse result.
 *
 * There is no top-level `category`: the API categorises each line item on commit,
 * so a per-receipt category would be a guess on top of per-item guesses.
 */
export interface OcrParseResponse {
  merchant: string | null;
  total: string | null;
  currency: string | null;
  transaction_date: string | null;
  line_items: OcrLineItem[];
  confidence: number;
  parser: string;
  notes: string[];
}

export interface CategorizeResponse {
  category: string;
  confidence: number;
  scores: Record<string, number>;
  matched_keywords: string[];
  notes: string[];
  engine: string;
}

// ---------------------------------------------------------------- budgets

export interface BudgetProgress {
  budget_id: number;
  category: string;
  month: number;
  year: number;
  limit: string;
  spent: string;
  remaining: string;
  used_percent: number;
  status: string;
}

export interface BudgetListResponse {
  items: BudgetProgress[];
  total: number;
  month: number;
  year: number;
}

export interface Budget {
  id: number;
  user_id: number;
  category: string;
  amount: string;
  month: number;
  year: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface BudgetCreate {
  category: string;
  /** The API field is `amount`, not `limit_amount`. */
  amount: string;
  month: number;
  year: number;
}

export type BudgetUpdate = Partial<BudgetCreate>;

// ---------------------------------------------------------------- fraud

export interface FraudAlert {
  id: number;
  user_id: number;
  transaction_id: number | null;
  risk_score: number;
  risk_level: RiskLevel;
  is_fraud: boolean;
  detection_layer: DetectionLayer;
  reasons: string[] | null;
  amount_snapshot: string | null;
  merchant_snapshot: string | null;
  category_snapshot: string | null;
  is_read: boolean;
  is_dismissed: boolean;
  created_at: string | null;
}

export interface FraudAlertListResponse {
  items: FraudAlert[];
  total: number;
  unread: number;
  by_level: Record<string, number>;
}

export interface FraudAlertUpdate {
  is_read?: boolean;
  is_dismissed?: boolean;
}

// ---------------------------------------------------------------- loans

export interface Loan {
  id: number;
  user_id: number;
  name: string;
  lender: string | null;
  loan_type: string;
  principal: string;
  interest_rate: string;
  tenure_months: number;
  monthly_emi: string;
  total_payable: string;
  start_date: string;
  status: string;
  notes: string | null;
  created_at: string | null;
}

export interface LoanCreate {
  name: string;
  lender?: string | null;
  loan_type?: string;
  principal: string;
  interest_rate: string;
  tenure_months: number;
  start_date: string;
  notes?: string | null;
}

export type LoanUpdate = Partial<LoanCreate>;

export interface LoanSummary {
  loan_id: number;
  total_due: string;
  total_paid: string;
  outstanding: string;
  installments_paid: number;
  installments_total: number;
  overdue_count: number;
  principal_repaid: string;
  completion_percent: number;
  next_due_date: string | null;
}

/** Loan detail: the loan, its summary, and the next instalments. */
export interface LoanDetail extends Loan {
  summary: LoanSummary;
  upcoming: UpcomingInstallment[];
}

export interface EmiScheduleEntry {
  installment_number: number;
  emi: string;
  principal: string;
  interest: string;
  balance_after: string;
}

export interface EmiResponse {
  principal: string;
  annual_rate: string;
  tenure_months: number;
  monthly_emi: string;
  total_payable: string;
  total_interest: string;
  schedule: EmiScheduleEntry[];
}

/**
 * `GET /api/loans/portfolio`, aggregated across every loan.
 *
 * Key names are the route's, not the loan list's: `loan_count`/`active_count`
 * rather than `total_loans`/`active_loans`, and `total_monthly_emi`. The
 * response carries only active loans in the EMI total.
 */
export interface LoanPortfolio {
  loan_count: number;
  active_count: number;
  total_outstanding: string;
  total_monthly_emi: string;
  next_due_date: string | null;
}

/**
 * `GET /api/loans/{id}/prepayment`, typed here because the route returns an
 * unvalidated dict and its two shapes are meaningfully different.
 *
 * On `valid: false` the only other key is `reason`; every figure below is absent.
 * A client must read `valid` before any of the money fields, not treat a missing
 * value as zero - zero saved would be a false reassurance.
 */
export interface PrepaymentEffect {
  valid: boolean;
  reason?: string;
  prepayment?: string;
  original_emi?: string;
  revised_emi?: string;
  original_interest?: string;
  revised_interest?: string;
  interest_saved?: string;
}

/**
 * One entry of `LoanDetail.upcoming`.
 *
 * These are the loan's stored instalment rows, so the keys are `due_date` and
 * `status` rather than the EMI calculator's schedule keys.
 */
export interface UpcomingInstallment {
  installment_number: number;
  due_date: string;
  amount: string;
  status: string;
}

export interface LoanPayment {
  id: number;
  loan_id: number;
  installment_number: number;
  amount: string;
  principal_component: string | null;
  interest_component: string | null;
  due_date: string;
  paid_date: string | null;
  status: string;
  transaction_id: number | null;
}

// ---------------------------------------------------------------- notifications

export interface NotificationItem {
  id: number;
  notification_type: string;
  title: string;
  body: string;
  data: Record<string, unknown> | null;
  is_read: boolean;
  read_at: string | null;
  deep_link: string | null;
  created_at: string | null;
}

export interface UnreadCountResponse {
  unread: number;
}

// ---------------------------------------------------------------- ml / backups

/**
 * `/api/ml/status`. Shapes the no-model and model-present cases into one object
 * rather than a union, so a screen can read `message` in either case.
 */
export interface MlStatusResponse {
  sklearn_available: boolean;
  sklearn_reason: string | null;
  model_loaded: boolean;
  model_name: string | null;
  feature_count: number;
  load_error: string | null;
  user_transaction_count: number;
  scoring_mode: string;
  message: string;
}

export interface BackupItem {
  id: number;
  provider: string;
  status: string;
  remote_path: string | null;
  remote_url: string | null;
  record_count: number | null;
  size_bytes: number | null;
  checksum: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export interface BackupListResponse {
  items: BackupItem[];
  total: number;
  provider: string | null;
  configured: boolean;
  message: string;
}

// ---------------------------------------------------------------- reports

export interface ReportRequest {
  report_type: string;
  report_format: string;
  period_start?: string;
  period_end?: string;
  category?: string;
}

export interface ReportRecord {
  id: number;
  report_type: string;
  report_format: string;
  period_start: string | null;
  period_end: string | null;
  category: string | null;
  row_count: number | null;
  file_size_bytes: number | null;
  created_at: string | null;
}

export interface ReportTypes {
  report_types: string[];
  report_formats: string[];
}


// ---------------------------------------------------------------- assistant

export interface AssistantMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface AssistantRequest {
  message: string;
  history?: AssistantMessage[];
  include_context?: boolean;
}

export interface AssistantResponse {
  reply: string;
  provider: string;
  model: string | null;
  context_used: string[];
  suggestions: string[];
  fallback: boolean;
}

export interface AssistantConfig {
  provider: string;
  model: string | null;
  remote_configured: boolean;
  message: string;
  suggestions: string[];
}


// ---------------------------------------------------------------- family

export interface FamilyGroup {
  id: number;
  name: string;
  owner_id: number;
  description: string | null;
  is_active: boolean;
  member_count: number;
  created_at: string | null;
}

export interface FamilyMember {
  id: number;
  family_id: number;
  user_id: number | null;
  invited_email: string | null;
  name: string | null;
  role: string;
  status: string;
  can_view_all: boolean;
  joined_at: string | null;
}
