import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..api_schemas import ActivateKeyIn, ActivateKeyOut, CreateActivationKeyOut, BotActivateKeyIn
from ..db import get_db
from ..deps.auth import get_current_user, require_internal_key
from ..models import (
    User,
    Plan,
    PlanFeature,
    Subscription,
    SubscriptionStatus,
    ActivationKey,
    ActivationKeyUsage,
)
from .auth import build_plan_out

router = APIRouter(prefix="/billing", tags=["billing"])


def _find_active_subscription(db: Session, user_id):
    return (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.active,
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )


def _apply_key_to_user(db: Session, user: User, key_obj: ActivationKey):
    now = datetime.utcnow()

    if not key_obj.is_active:
        raise HTTPException(status_code=400, detail="Key is inactive")

    if getattr(key_obj, "status", None):
        status_val = key_obj.status.value if hasattr(key_obj.status, "value") else str(key_obj.status)
        if status_val not in ("active",):
            raise HTTPException(status_code=400, detail="Key is not active")

    if key_obj.expires_at and key_obj.expires_at < now:
        raise HTTPException(status_code=400, detail="Key expired")

    if key_obj.max_uses is not None and key_obj.used_count >= key_obj.max_uses:
        raise HTTPException(status_code=400, detail="Key usage limit exceeded")

    plan = db.query(Plan).filter(Plan.id == key_obj.plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    active_sub = _find_active_subscription(db, user.id)
    if active_sub:
        active_sub.status = SubscriptionStatus.canceled
        active_sub.canceled_at = now

    ends_at = None
    if key_obj.duration_days:
        ends_at = now + timedelta(days=key_obj.duration_days)

    new_sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status=SubscriptionStatus.active,
        starts_at=now,
        ends_at=ends_at,
        notes=f"Activated by key {key_obj.key_value}",
    )
    db.add(new_sub)
    db.flush()

    key_obj.used_count += 1
    key_obj.used_at = now

    if key_obj.max_uses is not None and key_obj.used_count >= key_obj.max_uses:
        key_obj.is_active = False
        if hasattr(key_obj, "status"):
            key_obj.status = "used"

    usage = ActivationKeyUsage(
        activation_key_id=key_obj.id,
        user_id=user.id,
        subscription_id=new_sub.id,
    )
    db.add(usage)

    db.commit()
    db.refresh(new_sub)

    return new_sub, plan


@router.post("/activate-key", response_model=ActivateKeyOut)
def activate_key(
    payload: ActivateKeyIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    key_obj = db.query(ActivationKey).filter(ActivationKey.key_value == payload.key.strip()).first()
    if not key_obj:
        raise HTTPException(status_code=404, detail="Key not found")

    sub, plan = _apply_key_to_user(db, current_user, key_obj)

    return ActivateKeyOut(
        ok=True,
        plan=build_plan_out(db, plan),
        starts_at=sub.starts_at.isoformat(),
        ends_at=sub.ends_at.isoformat() if sub.ends_at else None,
    )


@router.post("/bot/activate-key", response_model=ActivateKeyOut, dependencies=[Depends(require_internal_key)])
def bot_activate_key(
    payload: BotActivateKeyIn,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.telegram_id == payload.telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    key_obj = db.query(ActivationKey).filter(ActivationKey.key_value == payload.key.strip()).first()
    if not key_obj:
        raise HTTPException(status_code=404, detail="Key not found")

    sub, plan = _apply_key_to_user(db, user, key_obj)

    return ActivateKeyOut(
        ok=True,
        plan=build_plan_out(db, plan),
        starts_at=sub.starts_at.isoformat(),
        ends_at=sub.ends_at.isoformat() if sub.ends_at else None,
    )


@router.post("/bot/create-demo-key", response_model=CreateActivationKeyOut, dependencies=[Depends(require_internal_key)])
def create_demo_key(
    plan_code: str,
    duration_days: int | None = 30,
    max_uses: int | None = 1,
    db: Session = Depends(get_db),
):
    plan = db.query(Plan).filter(Plan.code == plan_code).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    key_value = secrets.token_urlsafe(18)

    key_obj = ActivationKey(
        key_value=key_value,
        plan_id=plan.id,
        duration_days=duration_days,
        max_uses=max_uses,
        used_count=0,
        is_active=True,
        status="active",
    )
    db.add(key_obj)
    db.commit()
    db.refresh(key_obj)

    return CreateActivationKeyOut(
        key=key_obj.key_value,
        plan_code=plan.code,
        duration_days=key_obj.duration_days,
        max_uses=key_obj.max_uses,
        expires_at=key_obj.expires_at.isoformat() if key_obj.expires_at else None,
    )