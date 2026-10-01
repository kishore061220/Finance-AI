"""Fraud, dashboard, analytics, loan, family, notification, backup, report and
assistant schemas.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.fraud_alert import DetectionLayer, RiskLevel
from app.models.loan import LoanStatus, LoanType, PaymentStatus
from app.models.notification import NotificationType
from app.models.user import UserRole
from app.schemas.budget import BudgetProgressResponse
from app.schemas.user import ORMModel

# ---------------------------------------------------------------------------
# Fraud
# ---------------------------------------------------------------------------
class FraudAnalysisResponse(BaseModel):
    is_fraud: bool
    risk_score: int
    risk_level: str
    reasons: List[str]
    signals: List[str] = []
    detection_layer: str = "RULES"
    ml_score: Optional[int] = None
    combined_score: Optional[int] = None
    model: Optional[str] = None
    message: str = ""


class FraudAlertResponse(ORMModel):
    id: int
    user_id: int
    transaction_id: Optional[int] = None
    risk_score: int
    risk_level: RiskLevel
    is_fraud: bool
    detection_layer: DetectionLayer
    reasons: Optional[List[str]] = None
    amount_snapshot: Optional[Decimal] = None
    merchant_snapshot: Optional[str] = None
    category_snapshot: Optional[str] = None
    is_read: bool
    is_dismissed: bool
    created_at: Optional[datetime] = None


class FraudAlertListResponse(BaseModel):
    items: List[FraudAlertResponse]
    total: int
    unread: int
    by_level: Dict[str, int]


class FraudAlertUpdate(BaseModel):
    is_read: Optional[bool] = None
    is_dismissed: Optional[bool] = None


# ---------------------------------------------------------------------------
# Dashboard / analytics
# ---------------------------------------------------------------------------
class TotalsResponse(BaseModel):
    income: Decimal
    expense: Decimal
    net: Decimal
    savings_rate_percent: float


class CategoryBreakdownResponse(BaseModel):
    category: str
    amount: Decimal
    percent: float


class MerchantBreakdownResponse(BaseModel):
    merchant: str
    amount: Decimal


class MonthlyTrendResponse(BaseModel):
    year: int
    month: int
    label: str
    income: Decimal
    expense: Decimal
    net: Decimal


class DailySeriesResponse(BaseModel):
    date: str
    amount: Decimal


class InsightResponse(BaseModel):
    type: str
    severity: str
    title: str
    message: str
    data: Dict[str, Any] = {}


class RecurringResponse(BaseModel):
    merchant: str
    occurrences: int
    average_amount: Decimal
    coefficient_of_variation: float
    monthly_cost: Decimal
    annual_cost: Decimal


class FraudSummaryResponse(BaseModel):
    total: int
    unread: int


class ForecastRange(BaseModel):
    low: Decimal
    high: Decimal


class ForecastResponse(BaseModel):
    month: int
    year: int
    label: str
    predicted_expense: Decimal
    range: ForecastRange
    average_monthly_expense: Decimal
    months_of_history: int
    volatility: Decimal
    # How the figure was derived, so a client can show its provenance.
    basis: str
    notes: List[str] = []


class CategoryForecastResponse(BaseModel):
    category: str
    total: Decimal
    average_per_month: Decimal


class BudgetProjectionResponse(BaseModel):
    category: str
    budget: Decimal
    spent: Decimal
    projected: Decimal
    over_projected: bool
    projected_ratio: float


class HistoryPointResponse(BaseModel):
    label: str
    expense: Decimal


class PredictionResponse(BaseModel):
    """Spending forecast for the caller.

    ``status`` is the contract: ``predicted`` when there is enough history for a
    figure, ``insufficient_data`` when there is not. In the insufficient case
    ``prediction`` is null rather than a fabricated number, and ``message``
    explains exactly how much more history is needed.
    """

    status: str
    message: str
    prediction: Optional[ForecastResponse] = None
    required_months: int
    available_months: int
    months_needed: int
    observed_average: Optional[Decimal] = None
    history: List[HistoryPointResponse] = []
    categories: List[CategoryForecastResponse] = []
    budget_projection: List[BudgetProjectionResponse] = []

class DashboardResponse(BaseModel):
    totals: TotalsResponse
    category_breakdown: List[CategoryBreakdownResponse]
    top_merchants: List[MerchantBreakdownResponse]
    budget_progress: List["BudgetProgressResponse"]
    monthly_trend: List[MonthlyTrendResponse]
    insights: List[InsightResponse]
    fraud_summary: FraudSummaryResponse
    recurring: List[RecurringResponse]
    generated_at: str


# ---------------------------------------------------------------------------
# Loans
# ---------------------------------------------------------------------------
class LoanCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    lender: Optional[str] = Field(default=None, max_length=150)
    loan_type: LoanType = LoanType.OTHER
    principal: Decimal = Field(..., gt=0, max_digits=14, decimal_places=2)
    interest_rate: Decimal = Field(..., ge=0, le=100, max_digits=6, decimal_places=3)
    tenure_months: int = Field(..., gt=0, le=600)
    start_date: date
    notes: Optional[str] = Field(default=None, max_length=255)


class LoanUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    lender: Optional[str] = Field(default=None, max_length=150)
    loan_type: Optional[LoanType] = None
    interest_rate: Optional[Decimal] = Field(default=None, ge=0, le=100, max_digits=6, decimal_places=3)
    tenure_months: Optional[int] = Field(default=None, gt=0, le=600)
    status: Optional[LoanStatus] = None
    notes: Optional[str] = Field(default=None, max_length=255)


class LoanResponse(ORMModel):
    id: int
    user_id: int
    name: str
    lender: Optional[str] = None
    loan_type: LoanType
    principal: Decimal
    interest_rate: Decimal
    tenure_months: int
    monthly_emi: Decimal
    total_payable: Decimal
    start_date: date
    status: LoanStatus
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class LoanSummaryResponse(BaseModel):
    loan_id: int
    total_due: Decimal
    total_paid: Decimal
    outstanding: Decimal
    installments_paid: int
    installments_total: int
    overdue_count: int
    principal_repaid: Decimal
    completion_percent: float
    next_due_date: Optional[date] = None


class LoanDetailResponse(LoanResponse):
    summary: LoanSummaryResponse
    upcoming: List[Dict[str, Any]] = []


class EmiRequest(BaseModel):
    principal: Decimal = Field(..., gt=0, max_digits=14, decimal_places=2)
    annual_rate: Decimal = Field(..., ge=0, le=100, max_digits=6, decimal_places=3)
    tenure_months: int = Field(..., gt=0, le=600)
    include_schedule: bool = False


class EmiScheduleEntry(BaseModel):
    installment_number: int
    emi: Decimal
    principal: Decimal
    interest: Decimal
    balance_after: Decimal


class EmiResponse(BaseModel):
    principal: Decimal
    annual_rate: Decimal
    tenure_months: int
    monthly_emi: Decimal
    total_payable: Decimal
    total_interest: Decimal
    schedule: List[EmiScheduleEntry] = []


class LoanPaymentCreate(BaseModel):
    installment_number: int = Field(..., gt=0)
    amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    paid_date: Optional[date] = None
    status: PaymentStatus = PaymentStatus.PAID
    transaction_id: Optional[int] = None


class LoanPaymentResponse(ORMModel):
    id: int
    loan_id: int
    installment_number: int
    amount: Decimal
    principal_component: Optional[Decimal] = None
    interest_component: Optional[Decimal] = None
    due_date: date
    paid_date: Optional[date] = None
    status: PaymentStatus
    transaction_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Family
# ---------------------------------------------------------------------------
class FamilyGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=255)


class FamilyGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=255)
    is_active: Optional[bool] = None


class FamilyMemberResponse(ORMModel):
    id: int
    family_id: int
    user_id: Optional[int] = None
    invited_email: Optional[str] = None
    name: Optional[str] = None
    role: str
    status: str
    can_view_all: bool
    joined_at: Optional[datetime] = None


class FamilyGroupResponse(ORMModel):
    id: int
    name: str
    owner_id: int
    description: Optional[str] = None
    is_active: bool
    member_count: int = 0
    created_at: Optional[datetime] = None


class FamilyMemberInvite(BaseModel):
    email: str = Field(..., max_length=150)
    can_view_all: bool = False


class SplitInput(BaseModel):
    user_id: int
    amount: Decimal = Field(..., ge=0, max_digits=12, decimal_places=2)


class SharedExpenseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=255)
    category: Optional[str] = Field(default=None, max_length=100)
    total_amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    expense_date: datetime
    transaction_id: Optional[int] = None
    equal_split: bool = True
    splits: List[SplitInput] = []


class SharedExpenseResponse(ORMModel):
    id: int
    family_id: int
    created_by_id: int
    transaction_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    total_amount: Decimal
    expense_date: datetime
    is_settled: bool
    created_at: Optional[datetime] = None


class ExpenseSplitResponse(ORMModel):
    id: int
    shared_expense_id: int
    user_id: int
    owed_amount: Decimal
    settled_amount: Decimal
    is_settled: bool


class FamilyBalanceResponse(BaseModel):
    user_id: int
    name: Optional[str] = None
    you_owe: Decimal
    owed_to_you: Decimal
    net: Decimal


class SettleUpRequest(BaseModel):
    from_user_id: int
    to_user_id: int
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)


# ---------------------------------------------------------------------------
# Notifications / devices
# ---------------------------------------------------------------------------
class NotificationResponse(ORMModel):
    id: int
    notification_type: NotificationType
    title: str
    body: str
    data: Optional[Dict[str, Any]] = None
    is_read: bool
    read_at: Optional[datetime] = None
    deep_link: Optional[str] = None
    created_at: Optional[datetime] = None


class NotificationListResponse(BaseModel):
    items: List[NotificationResponse]
    total: int
    unread: int
    page: int
    page_size: int


class DeviceTokenCreate(BaseModel):
    token: str = Field(..., min_length=10, max_length=512)
    platform: str = Field(..., pattern="^(ANDROID|IOS|WEB)$")
    device_name: Optional[str] = Field(default=None, max_length=120)
    app_version: Optional[str] = Field(default=None, max_length=32)


class DeviceTokenResponse(ORMModel):
    id: int
    platform: str
    device_name: Optional[str] = None
    app_version: Optional[str] = None
    is_active: bool
    last_seen_at: Optional[datetime] = None


class PushResult(BaseModel):
    success_count: int
    failure_count: int
    provider: str
    message: str


class NotificationCreate(BaseModel):
    """Create an in-app notification and optionally push it."""

    title: str = Field(..., min_length=1, max_length=150)
    body: str = Field(..., min_length=1, max_length=255)
    notification_type: NotificationType = NotificationType.SYSTEM
    data: Optional[Dict[str, Any]] = None
    deep_link: Optional[str] = Field(default=None, max_length=120)
    push: bool = True


class NotificationWithPushResponse(BaseModel):
    notification: NotificationResponse
    push: Optional[PushResult] = None


# ---------------------------------------------------------------------------
# Backup / reports
# ---------------------------------------------------------------------------
class BackupRequest(BaseModel):
    provider: Optional[str] = Field(
        default=None, pattern="^(FIREBASE_STORAGE|GOOGLE_CLOUD_STORAGE|GOOGLE_DRIVE)$"
    )
    include_fraud_alerts: bool = True
    include_budgets: bool = True
    include_loans: bool = True


class BackupStatusResponse(ORMModel):
    id: int
    provider: str
    status: str
    remote_path: Optional[str] = None
    remote_url: Optional[str] = None
    record_count: Optional[int] = None
    size_bytes: Optional[int] = None
    checksum: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class BackupListResponse(BaseModel):
    items: List[BackupStatusResponse]
    total: int
    provider: Optional[str] = None
    configured: bool
    message: str


class RestoreTablePlan(BaseModel):
    table: str
    inserts: int
    updates: int
    skips: int
    conflicts: int = 0
    notes: List[str] = []


class RestoreTotals(BaseModel):
    inserts: int
    updates: int
    skips: int
    conflicts: int = 0


class RestoreResponse(BaseModel):
    """Result of a restore preview, or of a restore that has been applied.

    ``checksum_verified`` is always true when this object is returned at all: a
    corrupt backup raises instead of being reported, so reaching this schema
    already means the stored bytes matched the checksum taken at upload time.
    """

    backup_id: int
    backup_version: int
    generated_at: Optional[str] = None
    checksum_verified: bool
    checksum: str
    tables: List[RestoreTablePlan]
    totals: RestoreTotals
    warnings: List[str] = []
    # False for a preview, true once the upsert has been committed.
    applied: bool = False


class RestoreRequest(BaseModel):
    """Explicit confirmation for the destructive half of a restore.

    ``confirm`` must be true. It exists so that a mis-wired client which POSTs
    an empty body cannot wipe a ledger by accident.
    """

    confirm: bool = False


class ReportRequest(BaseModel):
    report_type: str = Field(
        ...,
        pattern="^(TRANSACTIONS|INCOME|EXPENSES|CATEGORIES|FRAUD|BUDGETS|SPENDING_TRENDS|LOANS)$",
    )
    report_format: str = Field(..., pattern="^(CSV|EXCEL|PDF)$")
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    category: Optional[str] = Field(default=None, max_length=100)


class ReportResponse(ORMModel):
    id: int
    report_type: str
    report_format: str
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    category: Optional[str] = None
    row_count: Optional[int] = None
    file_size_bytes: Optional[int] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Assistant
# ---------------------------------------------------------------------------
class AssistantMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=4000)


class AssistantRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: List[AssistantMessage] = []
    include_context: bool = True


class AssistantResponse(BaseModel):
    reply: str
    provider: str
    model: Optional[str] = None
    context_used: List[str] = []
    suggestions: List[str] = []
    fallback: bool = False


DashboardResponse.model_rebuild()


__all__ = [
    "AssistantMessage",
    "AssistantRequest",
    "AssistantResponse",
    "BackupListResponse",
    "BackupRequest",
    "BackupStatusResponse",
    "BudgetProgressResponse",
    "CategoryBreakdownResponse",
    "DailySeriesResponse",
    "DashboardResponse",
    "DeviceTokenCreate",
    "DeviceTokenResponse",
    "EmiRequest",
    "EmiResponse",
    "ExpenseSplitResponse",
    "FamilyBalanceResponse",
    "FamilyGroupCreate",
    "FamilyGroupResponse",
    "FamilyGroupUpdate",
    "FamilyMemberInvite",
    "FamilyMemberResponse",
    "FraudAlertListResponse",
    "FraudAlertResponse",
    "FraudAlertUpdate",
    "FraudAnalysisResponse",
    "FraudSummaryResponse",
    "InsightResponse",
    "LoanCreate",
    "LoanDetailResponse",
    "LoanPaymentCreate",
    "LoanPaymentResponse",
    "LoanResponse",
    "LoanSummaryResponse",
    "LoanUpdate",
    "MerchantBreakdownResponse",
    "MonthlyTrendResponse",
    "NotificationListResponse",
    "NotificationResponse",
    "PushResult",
    "RecurringResponse",
    "ReportRequest",
    "ReportResponse",
    "SettleUpRequest",
    "SharedExpenseCreate",
    "SharedExpenseResponse",
    "SplitInput",
    "TotalsResponse",
    "UserRole",
]
