from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import uuid
from ..config import settings
from ..db import get_db
from ..models import Plan, PlanFeature, Subscription, SubscriptionStatus, User
from ..security import create_access_token
router = APIRouter(prefix="/bot", tags=["bot"])


def _check_internal_key(x_bot_key: str | None = Header(default=None)):
    if x_bot_key != settings.bot_internal_key:
        raise HTTPException(status_code=401, detail="Invalid bot key")


@router.get("/user-by-telegram/{telegram_id}")
def get_user_by_telegram(
    telegram_id: int,
    _: None = Depends(_check_internal_key),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"ok": False, "user": None}

    sub = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user.id,
            Subscription.status == SubscriptionStatus.active,
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )

    plan_data = None
    if sub:
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()
        features = db.query(PlanFeature).filter(PlanFeature.plan_id == plan.id).all() if plan else []
        plan_data = {
            "code": plan.code,
            "title": plan.title,
            "monthly_minutes": plan.monthly_minutes,
            "meeting_storage_limit": plan.meeting_storage_limit,
            "features": {
                f.feature_code: {
                    "is_enabled": f.is_enabled,
                    "feature_value": f.feature_value,
                }
                for f in features
            },
        } if plan else None

    return {
        "ok": True,
        "user": {
            "id": str(user.id),
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role.value,
            "is_active": user.is_active,
        },
        "plan": plan_data,
    }

class BotTelegramAuthIn(BaseModel):
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


@router.post("/auth/by-telegram")
def bot_auth_by_telegram(
    payload: BotTelegramAuthIn,
    _: None = Depends(_check_internal_key),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.telegram_id == payload.id).first()
    if not user:
        user = User(
            id=uuid.uuid4(),
            telegram_id=payload.id,
            username=payload.username,
            first_name=payload.first_name,
            last_name=payload.last_name,
            role="user",
            is_active=True,
        )
        db.add(user)
    else:
        user.username = payload.username
        user.first_name = payload.first_name
        user.last_name = payload.last_name

    db.commit()
    db.refresh(user)

    token = create_access_token(str(user.id))

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role.value,
            "is_active": user.is_active,
        },
    }