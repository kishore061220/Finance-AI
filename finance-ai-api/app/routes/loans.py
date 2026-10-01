"""Loan, EMI and repayment routes.

EMI maths is delegated to :mod:`app.services.loan_service` so the calculation is
unit-tested independently of HTTP.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database.connection import get_db
from app.models.loan import (
    Loan,
    LoanPayment,
    LoanStatus,
    LoanType,
    PaymentStatus,
)
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.common import (
    EmiRequest,
    EmiResponse,
    LoanCreate,
    LoanDetailResponse,
    LoanPaymentCreate,
    LoanPaymentResponse,
    LoanResponse,
    LoanUpdate,
)
from app.services import loan_service
from app.utils.money import to_decimal

router = APIRouter(prefix="/api/loans", tags=["loans"])


def _due_date(start: date, installment_number: int) -> date:
    """Monthly due date, clamped to the last day of short months."""
    month_index = start.month - 1 + (installment_number - 1)
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _find(db: Session, loan_id: int, user_id: int) -> Loan:
    loan = db.get(Loan, loan_id)
    if loan is None or loan.user_id != user_id:
        raise HTTPException(status_code=404, detail="Loan not found")
    return loan


def _payments(db: Session, loan_id: int) -> List[LoanPayment]:
    return list(
        db.execute(
            select(LoanPayment)
            .where(LoanPayment.loan_id == loan_id)
            .order_by(LoanPayment.installment_number)
        ).scalars()
    )


def _generate_schedule(db: Session, loan: Loan) -> List[LoanPayment]:
    """Create the full installment schedule for a loan."""
    schedule = loan_service.amortisation_schedule(
        loan.principal, loan.interest_rate, loan.tenure_months
    )
    payments = [
        LoanPayment(
            loan_id=loan.id,
            user_id=loan.user_id,
            installment_number=row["installment_number"],
            amount=row["emi"],
            principal_component=row["principal"],
            interest_component=row["interest"],
            due_date=_due_date(loan.start_date, row["installment_number"]),
            status=PaymentStatus.PENDING,
        )
        for row in schedule
    ]
    db.add_all(payments)
    return payments


@router.post("/emi/calculate", response_model=EmiResponse, summary="EMI calculator")
def calculate_emi(payload: EmiRequest) -> EmiResponse:
    result = loan_service.emi_calculator(
        payload.principal, payload.annual_rate, payload.tenure_months
    )
    response = EmiResponse(
        principal=payload.principal,
        annual_rate=payload.annual_rate,
        tenure_months=payload.tenure_months,
        monthly_emi=result["monthly_emi"],
        total_payable=result["total_payable"],
        total_interest=result["total_interest"],
    )
    if payload.include_schedule:
        response.schedule = [
            {
                "installment_number": r["installment_number"],
                "emi": r["emi"],
                "principal": r["principal"],
                "interest": r["interest"],
                "balance_after": r["balance_after"],
            }
            for r in loan_service.amortisation_schedule(
                payload.principal, payload.annual_rate, payload.tenure_months
            )
        ]
    return response


@router.post(
    "",
    response_model=LoanDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a loan and its schedule",
)
def create_loan(
    payload: LoanCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LoanDetailResponse:
    terms = loan_service.build_loan_terms(
        payload.principal, payload.interest_rate, payload.tenure_months
    )
    loan = Loan(
        user_id=current_user.id,
        name=payload.name,
        lender=payload.lender,
        loan_type=payload.loan_type,
        principal=payload.principal,
        interest_rate=payload.interest_rate,
        tenure_months=payload.tenure_months,
        monthly_emi=terms["monthly_emi"],
        total_payable=terms["total_payable"],
        start_date=payload.start_date,
        status=LoanStatus.ACTIVE,
        notes=payload.notes,
    )
    db.add(loan)
    db.flush()

    payments = _generate_schedule(db, loan)
    db.commit()
    db.refresh(loan)

    return LoanDetailResponse(
        **LoanResponse.model_validate(loan).model_dump(),
        summary=_summary(loan, payments),
        upcoming=loan_service.upcoming_installments(payments),
    )


def _summary(loan: Loan, payments: List[LoanPayment]) -> dict:
    # ``loan_summary`` deliberately takes only the schedule, so the loan id is
    # attached here to satisfy the response contract.
    return {"loan_id": loan.id, **loan_service.loan_summary(payments)}


@router.get("", response_model=List[LoanResponse], summary="List loans")
def list_loans(
    loan_status: Optional[LoanStatus] = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Loan]:
    stmt = select(Loan).where(Loan.user_id == current_user.id)
    if loan_status:
        stmt = stmt.where(Loan.status == loan_status)
    return list(db.execute(stmt.order_by(Loan.created_at.desc())).scalars())


@router.get("/portfolio", summary="Aggregate position across all loans")
def portfolio(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    loans = list(
        db.execute(
            select(Loan).where(Loan.user_id == current_user.id)
        ).scalars()
    )
    total_outstanding = to_decimal(0)
    total_monthly_emi = to_decimal(0)
    next_due = None

    for loan in loans:
        payments = _payments(db, loan.id)
        summary = loan_service.loan_summary(payments)
        total_outstanding += summary["outstanding"]
        if loan.status == LoanStatus.ACTIVE:
            total_monthly_emi += loan.monthly_emi
        if summary.get("next_due_date"):
            candidate = summary["next_due_date"]
            if next_due is None or candidate < next_due:
                next_due = candidate

    return {
        "loan_count": len(loans),
        "active_count": sum(1 for l in loans if l.status == LoanStatus.ACTIVE),
        "total_outstanding": str(total_outstanding),
        "total_monthly_emi": str(total_monthly_emi),
        "next_due_date": next_due.isoformat() if next_due else None,
    }


@router.get("/{loan_id}", response_model=LoanDetailResponse, summary="Loan detail")
def get_loan(
    loan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LoanDetailResponse:
    loan = _find(db, loan_id, current_user.id)
    payments = _payments(db, loan.id)
    return LoanDetailResponse(
        **LoanResponse.model_validate(loan).model_dump(),
        summary=_summary(loan, payments),
        upcoming=loan_service.upcoming_installments(payments),
    )


@router.patch("/{loan_id}", response_model=LoanResponse, summary="Update loan")
def update_loan(
    loan_id: int,
    payload: LoanUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Loan:
    loan = _find(db, loan_id, current_user.id)
    data = payload.model_dump(exclude_unset=True)

    # Changing the rate or tenure invalidates the stored schedule, so the
    # schedule is rebuilt and unpaid installments are reset.
    reschedule = {"interest_rate", "tenure_months"} & set(data)
    for field, value in data.items():
        setattr(loan, field, value)

    if reschedule and loan.status == LoanStatus.ACTIVE:
        terms = loan_service.build_loan_terms(
            loan.principal, loan.interest_rate, loan.tenure_months
        )
        loan.monthly_emi = terms["monthly_emi"]
        loan.total_payable = terms["total_payable"]

        paid = [
            p
            for p in _payments(db, loan.id)
            if p.status == PaymentStatus.PAID
        ]
        if not paid:
            for existing in _payments(db, loan.id):
                db.delete(existing)
            db.flush()
            _generate_schedule(db, loan)
        # If installments were already paid the schedule is left untouched,
        # because rebuilding it would contradict recorded history.

    db.commit()
    db.refresh(loan)
    return loan


@router.delete(
    "/{loan_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete loan"
)
def delete_loan(
    loan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    loan = _find(db, loan_id, current_user.id)
    for payment in _payments(db, loan.id):
        db.delete(payment)
    db.delete(loan)
    db.commit()


@router.get(
    "/{loan_id}/payments", response_model=List[LoanPaymentResponse], summary="Schedule"
)
def list_payments(
    loan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[LoanPayment]:
    _find(db, loan_id, current_user.id)
    return _payments(db, loan_id)


@router.post(
    "/{loan_id}/payments",
    response_model=LoanPaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a repayment",
)
def record_payment(
    loan_id: int,
    payload: LoanPaymentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LoanPayment:
    loan = _find(db, loan_id, current_user.id)
    payment = db.execute(
        select(LoanPayment).where(
            LoanPayment.loan_id == loan_id,
            LoanPayment.installment_number == payload.installment_number,
        )
    ).scalar_one_or_none()
    if payment is None:
        raise HTTPException(
            status_code=404, detail="Installment not found in this loan's schedule"
        )

    if payload.transaction_id is not None:
        linked = db.get(Transaction, payload.transaction_id)
        if linked is None or linked.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Transaction not found")

    if payload.amount is not None:
        payment.amount = payload.amount
    payment.status = payload.status
    payment.paid_date = payload.paid_date or date.today()
    if payload.transaction_id is not None:
        payment.transaction_id = payload.transaction_id

    db.commit()
    db.refresh(payment)

    # Mark the loan settled once every installment is paid.
    remaining = db.execute(
        select(func.count())
        .select_from(LoanPayment)
        .where(LoanPayment.loan_id == loan_id, LoanPayment.status != PaymentStatus.PAID)
    ).scalar_one()
    if remaining == 0:
        loan.status = LoanStatus.CLOSED
        db.commit()
    return payment


@router.get("/{loan_id}/prepayment", summary="Effect of a prepayment")
def prepayment(
    loan_id: int,
    amount: float = Query(..., gt=0, description="Prepayment amount"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    loan = _find(db, loan_id, current_user.id)
    return loan_service.prepayment_impact(
        loan.principal,
        float(loan.interest_rate),
        loan.tenure_months,
        amount,
    )
