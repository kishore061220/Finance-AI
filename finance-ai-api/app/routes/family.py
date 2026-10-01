"""Family group, shared expense and settlement routes.

Membership is the authorisation boundary: a caller may only read a group in
which they hold an ACTIVE member row. The legacy routes had no membership
check at all.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database.connection import get_db
from app.models.family import (
    ExpenseSplit,
    FamilyGroup,
    FamilyMember,
    FamilyRole,
    MemberStatus,
    SharedExpense,
)
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.common import (
    ExpenseSplitResponse,
    FamilyBalanceResponse,
    FamilyGroupCreate,
    FamilyGroupResponse,
    FamilyGroupUpdate,
    FamilyMemberInvite,
    FamilyMemberResponse,
    SettleUpRequest,
    SharedExpenseCreate,
    SharedExpenseResponse,
)
from app.utils.money import money, to_decimal

router = APIRouter(prefix="/api/family", tags=["family"])


def _memberships(db: Session, user_id: int) -> List[FamilyMember]:
    return list(
        db.execute(
            select(FamilyMember).where(
                FamilyMember.user_id == user_id,
                FamilyMember.status == MemberStatus.ACTIVE,
            )
        ).scalars()
    )


def _require_member(db: Session, user_id: int, family_id: int) -> FamilyMember:
    membership = db.execute(
        select(FamilyMember).where(
            FamilyMember.family_id == family_id,
            FamilyMember.user_id == user_id,
            FamilyMember.status == MemberStatus.ACTIVE,
        )
    ).scalar_one_or_none()
    if membership is None:
        # 404 so we do not reveal that the group exists.
        raise HTTPException(status_code=404, detail="Family group not found")
    return membership


def _group_or_404(db: Session, group_id: int, user_id: int) -> FamilyGroup:
    group = db.get(FamilyGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Family group not found")
    _require_member(db, user_id, group_id)
    return group


def _group_response(db: Session, group: FamilyGroup) -> FamilyGroupResponse:
    member_count = db.execute(
        select(func.count())
        .select_from(FamilyMember)
        .where(
            FamilyMember.family_id == group.id,
            FamilyMember.status == MemberStatus.ACTIVE,
        )
    ).scalar_one()
    return FamilyGroupResponse(
        id=group.id,
        name=group.name,
        owner_id=group.owner_id,
        description=group.description,
        is_active=group.is_active,
        member_count=member_count,
        created_at=group.created_at,
    )


def _member_response(member: FamilyMember) -> FamilyMemberResponse:
    person = member.user or member.invited_user
    return FamilyMemberResponse(
        id=member.id,
        family_id=member.family_id,
        user_id=member.user_id,
        invited_email=member.invited_email,
        name=person.name if person else member.invited_email,
        role=member.role.value,
        status=member.status.value,
        can_view_all=member.can_view_all,
        joined_at=member.joined_at,
    )


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------
@router.post(
    "",
    response_model=FamilyGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a group (creator becomes owner)",
)
def create_group(
    payload: FamilyGroupCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FamilyGroupResponse:
    group = FamilyGroup(
        name=payload.name,
        owner_id=current_user.id,
        description=payload.description,
    )
    db.add(group)
    db.flush()
    db.add(
        FamilyMember(
            family_id=group.id,
            user_id=current_user.id,
            role=FamilyRole.OWNER,
            status=MemberStatus.ACTIVE,
            can_view_all=True,
        )
    )
    db.commit()
    db.refresh(group)
    return _group_response(db, group)


@router.get("", response_model=List[FamilyGroupResponse], summary="My groups")
def list_groups(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> List[FamilyGroupResponse]:
    ids = [m.family_id for m in _memberships(db, current_user.id)]
    if not ids:
        return []
    groups = list(
        db.execute(select(FamilyGroup).where(FamilyGroup.id.in_(ids))).scalars()
    )
    return [_group_response(db, g) for g in groups]


@router.get("/{group_id}", response_model=FamilyGroupResponse, summary="Get group")
def get_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FamilyGroupResponse:
    return _group_response(db, _group_or_404(db, group_id, current_user.id))


@router.patch("/{group_id}", response_model=FamilyGroupResponse, summary="Update group")
def update_group(
    group_id: int,
    payload: FamilyGroupUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FamilyGroupResponse:
    group = _group_or_404(db, group_id, current_user.id)
    if group.owner_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Only the group owner can update the group"
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    db.commit()
    db.refresh(group)
    return _group_response(db, group)


@router.delete(
    "/{group_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete group"
)
def delete_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    group = _group_or_404(db, group_id, current_user.id)
    if group.owner_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Only the group owner can delete the group"
        )
    for expense in db.execute(
        select(SharedExpense).where(SharedExpense.family_id == group_id)
    ).scalars():
        for split in expense.splits:
            db.delete(split)
        db.delete(expense)
    for member in db.execute(
        select(FamilyMember).where(FamilyMember.family_id == group_id)
    ).scalars():
        db.delete(member)
    db.delete(group)
    db.commit()


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
@router.get(
    "/{group_id}/members",
    response_model=List[FamilyMemberResponse],
    summary="List members",
)
def list_members(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[FamilyMemberResponse]:
    _require_member(db, current_user.id, group_id)
    members = list(
        db.execute(
            select(FamilyMember).where(FamilyMember.family_id == group_id)
        ).scalars()
    )
    return [_member_response(m) for m in members]


@router.post(
    "/{group_id}/members",
    response_model=FamilyMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a member",
)
def invite_member(
    group_id: int,
    payload: FamilyMemberInvite,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FamilyMemberResponse:
    group = _group_or_404(db, group_id, current_user.id)
    if group.owner_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Only the group owner can invite members"
        )

    existing = db.execute(
        select(FamilyMember).where(
            FamilyMember.family_id == group_id,
            FamilyMember.invited_email == payload.email,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{payload.email} has already been invited to this group.",
        )

    # Link the invite to a real account when the email matches one, so the
    # membership activates as soon as that user signs in.
    invited_user = db.execute(
        select(User).where(User.email == payload.email)
    ).scalar_one_or_none()

    member = FamilyMember(
        family_id=group_id,
        user_id=invited_user.id if invited_user else None,
        invited_user_id=invited_user.id if invited_user else None,
        invited_email=payload.email,
        role=FamilyRole.MEMBER,
        status=MemberStatus.ACTIVE if invited_user else MemberStatus.PENDING,
        can_view_all=payload.can_view_all,
        joined_at=None,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return _member_response(member)


@router.delete(
    "/{group_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove member",
)
def remove_member(
    group_id: int,
    member_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    group = _group_or_404(db, group_id, current_user.id)
    member = db.get(FamilyMember, member_id)
    if member is None or member.family_id != group_id:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot remove yourself")
    # Only the group owner may remove anyone. The previous check only fired
    # when the *target* held the OWNER role, which let an ordinary member
    # evict any other ordinary member - inconsistent with update_group,
    # delete_group and invite_member, which all gate on the group owner.
    if group.owner_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Only the group owner can remove a member"
        )
    db.delete(member)
    db.commit()


# ---------------------------------------------------------------------------
# Shared expenses
# ---------------------------------------------------------------------------
@router.get(
    "/{group_id}/expenses",
    response_model=List[SharedExpenseResponse],
    summary="List shared expenses",
)
def list_expenses(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[SharedExpense]:
    _require_member(db, current_user.id, group_id)
    return list(
        db.execute(
            select(SharedExpense)
            .where(SharedExpense.family_id == group_id)
            .order_by(SharedExpense.expense_date.desc())
        ).scalars()
    )


@router.post(
    "/{group_id}/expenses",
    status_code=status.HTTP_201_CREATED,
    summary="Create a shared expense",
)
def create_expense(
    group_id: int,
    payload: SharedExpenseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _require_member(db, current_user.id, group_id)

    if payload.transaction_id is not None:
        linked = db.get(Transaction, payload.transaction_id)
        if linked is None or linked.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Transaction not found")

    participants = _resolve_splits(db, group_id, payload)

    expense = SharedExpense(
        family_id=group_id,
        created_by_id=current_user.id,
        transaction_id=payload.transaction_id,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        total_amount=payload.total_amount,
        expense_date=payload.expense_date,
    )
    db.add(expense)
    db.flush()

    for split in participants:
        db.add(
            ExpenseSplit(
                shared_expense_id=expense.id,
                user_id=split["user_id"],
                owed_amount=split["owed_amount"],
            )
        )
    db.commit()
    db.refresh(expense)
    return {"id": expense.id, "split_count": len(participants)}


def _resolve_splits(
    db: Session, group_id: int, payload: SharedExpenseCreate
) -> List[dict]:
    """Work out who owes what, and reject splits that do not add up."""
    total = to_decimal(payload.total_amount)

    if payload.equal_split:
        member_rows = list(
            db.execute(
                select(FamilyMember).where(
                    FamilyMember.family_id == group_id,
                    FamilyMember.status == MemberStatus.ACTIVE,
                    FamilyMember.user_id.isnot(None),
                )
            ).scalars()
        )
        if not member_rows:
            raise HTTPException(
                status_code=422, detail="No active members to split between"
            )
        share = money(total / Decimal(len(member_rows)))
        # The final participant absorbs the rounding remainder so the split
        # always sums to the exact total.
        shares = [share] * (len(member_rows) - 1)
        shares.append(money(total - share * (len(member_rows) - 1)))
        return [
            {"user_id": m.user_id, "owed_amount": amount}
            for m, amount in zip(member_rows, shares)
        ]

    if not payload.splits:
        raise HTTPException(status_code=422, detail="Provide splits or set equal_split")

    member_ids = {
        m.user_id
        for m in db.execute(
            select(FamilyMember).where(
                FamilyMember.family_id == group_id,
                FamilyMember.status == MemberStatus.ACTIVE,
            )
        ).scalars()
        if m.user_id is not None
    }
    out: List[dict] = []
    for split in payload.splits:
        if split.user_id not in member_ids:
            raise HTTPException(
                status_code=403,
                detail=f"User {split.user_id} is not an active member of this group",
            )
        out.append({"user_id": split.user_id, "owed_amount": money(split.amount)})

    if money(sum((s["owed_amount"] for s in out), Decimal("0"))) != money(total):
        raise HTTPException(
            status_code=422,
            detail="The supplied splits do not add up to the total amount",
        )
    return out


@router.get(
    "/{group_id}/expenses/{expense_id}/splits",
    response_model=List[ExpenseSplitResponse],
    summary="Splits for an expense",
)
def expense_splits(
    group_id: int,
    expense_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[ExpenseSplit]:
    _require_member(db, current_user.id, group_id)
    expense = db.get(SharedExpense, expense_id)
    if expense is None or expense.family_id != group_id:
        raise HTTPException(status_code=404, detail="Shared expense not found")
    return list(
        db.execute(
            select(ExpenseSplit).where(ExpenseSplit.shared_expense_id == expense_id)
        ).scalars()
    )


@router.get(
    "/{group_id}/balances",
    response_model=List[FamilyBalanceResponse],
    summary="Who owes whom",
)
def balances(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[FamilyBalanceResponse]:
    """Net position for every member of the group.

    ``you_owe`` is what the member owes to others; ``owed_to_you`` is the
    reverse. Settlement history is not modelled separately - a settled split is
    simply recorded, so this is a current outstanding view.
    """
    _require_member(db, current_user.id, group_id)
    members = list(
        db.execute(
            select(FamilyMember).where(
                FamilyMember.family_id == group_id,
                FamilyMember.status == MemberStatus.ACTIVE,
                FamilyMember.user_id.isnot(None),
            )
        ).scalars()
    )
    member_ids = [m.user_id for m in members]

    expenses = list(
        db.execute(
            select(SharedExpense).where(SharedExpense.family_id == group_id)
        ).scalars()
    )
    expense_ids = [e.id for e in expenses]
    splits = (
        list(
            db.execute(
                select(ExpenseSplit).where(
                    ExpenseSplit.shared_expense_id.in_(expense_ids)
                )
            ).scalars()
        )
        if expense_ids
        else []
    )

    # net[user] = what others owe this user, minus what this user owes others.
    net: dict = {uid: to_decimal(0) for uid in member_ids}
    for split in splits:
        if split.is_settled or split.user_id not in net:
            continue
        expense = next(e for e in expenses if e.id == split.shared_expense_id)
        payer = expense.created_by_id
        if payer == split.user_id:
            continue
        net[payer] += to_decimal(split.owed_amount) - to_decimal(
            split.settled_amount
        )
        net[split.user_id] += to_decimal(split.settled_amount) - to_decimal(
            split.owed_amount
        )

    names = {m.user_id: (m.user.name if m.user else None) for m in members}
    out: List[FamilyBalanceResponse] = []
    for uid in member_ids:
        amount = money(net[uid])
        out.append(
            FamilyBalanceResponse(
                user_id=uid,
                name=names.get(uid),
                you_owe=money(-amount) if amount < 0 else money(0),
                owed_to_you=amount if amount > 0 else money(0),
                net=amount,
            )
        )
    return out


@router.post("/{group_id}/settle", summary="Record a settlement")
def settle(
    group_id: int,
    payload: SettleUpRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Mark a settlement by writing it into the split rows it clears.

    The request must come from one of the two parties, and the amount may not
    exceed what is outstanding.
    """
    _require_member(db, current_user.id, group_id)
    if current_user.id not in (payload.from_user_id, payload.to_user_id):
        raise HTTPException(
            status_code=403, detail="You can only record your own settlements"
        )
    if payload.from_user_id == payload.to_user_id:
        raise HTTPException(status_code=400, detail="A user cannot settle with themselves")

    splits = list(
        db.execute(
            select(ExpenseSplit)
            .join(SharedExpense, SharedExpense.id == ExpenseSplit.shared_expense_id)
            .where(
                SharedExpense.family_id == group_id,
                ExpenseSplit.user_id == payload.from_user_id,
                ExpenseSplit.is_settled.is_(False),
            )
        ).scalars()
    )

    remaining = money(payload.amount)
    touched = 0
    for split in splits:
        if remaining <= 0:
            break
        outstanding = money(
            to_decimal(split.owed_amount) - to_decimal(split.settled_amount)
        )
        if outstanding <= 0:
            continue
        applied = money(min(outstanding, remaining))
        split.settled_amount = money(to_decimal(split.settled_amount) + applied)
        remaining = money(remaining - applied)
        if split.settled_amount >= split.owed_amount:
            split.is_settled = True
        touched += 1

    if touched == 0:
        raise HTTPException(
            status_code=422, detail="Nothing outstanding to settle for that member"
        )

    db.commit()
    return {
        "settled": str(money(to_decimal(payload.amount) - remaining)),
        "unapplied": str(remaining),
        "splits_touched": touched,
    }
