import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..api_schemas import TelegramAuthIn, AuthOut, UserOut, MeOut, PlanOut
from ..db import get_db
from ..deps.auth import get_current_user
from ..models import User, Subscription, Plan, SubscriptionStatus
from ..security import validate_telegram_init_data, create_access_token
from ..services.usage import plan_to_payload

router = APIRouter(prefix="/auth", tags=["auth"])


def user_to_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        telegram_id=user.telegram_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        is_active=user.is_active,
    )


def get_active_subscription(db: Session, user_id: uuid.UUID):
    return (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.active,
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )


def build_plan_out(db: Session, plan: Plan) -> PlanOut:
    payload = plan_to_payload(db, plan) or {}
    return PlanOut(**payload)


def authenticate_telegram_payload(payload: TelegramAuthIn, db: Session) -> dict:
    try:
        tg_user = validate_telegram_init_data(payload.init_data)
        print("TG AUTH OK:", tg_user)
    except Exception as e:
        print("TG AUTH FAIL:", repr(e))
        raise HTTPException(status_code=401, detail=str(e))

    telegram_id = tg_user.get("id")
    if not telegram_id:
        raise HTTPException(status_code=401, detail="Telegram user id is missing")

    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        user = User(
            telegram_id=telegram_id,
            username=tg_user.get("username"),
            first_name=tg_user.get("first_name"),
            last_name=tg_user.get("last_name"),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.username = tg_user.get("username")
        user.first_name = tg_user.get("first_name")
        user.last_name = tg_user.get("last_name")
        db.commit()
        db.refresh(user)

    access_token = create_access_token(str(user.id))
    return {"access_token": access_token, "user": user}


@router.post("/telegram", response_model=AuthOut)
def auth_telegram(payload: TelegramAuthIn, db: Session = Depends(get_db)):
    return authenticate_telegram_payload(payload, db)


@router.get("/me", response_model=MeOut)
def me(current_user: User = Depends(get_current_user)):
    return MeOut(user=user_to_out(current_user))


@router.get("/me/plan", response_model=PlanOut)
def me_plan(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = get_active_subscription(db, current_user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="Active subscription not found")

    plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    return build_plan_out(db, plan)
