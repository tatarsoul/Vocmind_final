from typing import Any
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..api_schemas import TelegramAuthIn, ActivateKeyIn
from ..db import get_db
from ..deps.auth import get_current_user
from ..models import Meeting, User
from ..services.exports import make_docx_bytes, make_pdf_bytes
from ..services.usage import (
    get_user_plan_context,
    meeting_to_payload,
    plan_to_payload,
    search_meetings_query,
    summarize_meeting_analytics,
)
from .auth import authenticate_telegram_payload
from .billing import _apply_key_to_user
from .extension import generate_link_code

router = APIRouter(prefix="/miniapp", tags=["miniapp"])



def _user_payload(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.post("/auth")
def miniapp_auth(payload: TelegramAuthIn, db: Session = Depends(get_db)):
    return authenticate_telegram_payload(payload, db)


@router.get("/dashboard")
def miniapp_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ctx = get_user_plan_context(db, current_user.id)
    sub = ctx["subscription"]
    plan = ctx["plan"]
    usage = ctx["usage"]

    return {
        "me": {"user": _user_payload(current_user)},
        "plan": plan_to_payload(db, plan),
        "subscription_status": sub.status.value if sub and hasattr(sub.status, "value") else (str(sub.status) if sub else None),
        "starts_at": sub.starts_at.isoformat() if sub and sub.starts_at else None,
        "ends_at": sub.ends_at.isoformat() if sub and sub.ends_at else None,
        "usage_minutes": usage["used_minutes"],
        "remaining_minutes": usage["remaining_minutes"],
        "meetings_count": usage["stored_meetings_count"],
        "storage_limit": usage["storage_limit"],
        "storage_remaining": usage["storage_remaining"],
    }


@router.get("/history")
def miniapp_history(
    q: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ctx = get_user_plan_context(db, current_user.id)
    features = ctx["features"]
    if q and not (features.get("meeting_search") or {}).get("is_enabled"):
        raise HTTPException(status_code=403, detail="Поиск по встречам доступен только на тарифе Профессиональный и выше")
    rows = search_meetings_query(db, current_user.id, q=q).limit(100).all()
    return {
        "items": [meeting_to_payload(row, features) for row in rows],
        "features": features,
    }




@router.get("/history-analytics")
def miniapp_history_analytics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ctx = get_user_plan_context(db, current_user.id)
    features = ctx["features"]
    if not (features.get("meeting_analytics") or {}).get("is_enabled"):
        raise HTTPException(status_code=403, detail="Аналитика встреч доступна только на тарифе Расширенный и выше")
    return summarize_meeting_analytics(db, current_user.id, features)


@router.delete("/history/{meeting_id}")
def miniapp_delete_history(
    meeting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(Meeting).filter(Meeting.id == meeting_id, Meeting.user_id == current_user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Встреча не найдена")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/history/{meeting_id}/export/{fmt}")
def miniapp_export_history(
    meeting_id: str,
    fmt: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ctx = get_user_plan_context(db, current_user.id)
    features = ctx["features"]
    row = db.query(Meeting).filter(Meeting.id == meeting_id, Meeting.user_id == current_user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Встреча не найдена")
    meeting_payload = meeting_to_payload(row, features)
    if fmt == "pdf":
        if not (features.get("export_pdf") or {}).get("is_enabled"):
            raise HTTPException(status_code=403, detail="Экспорт в PDF недоступен на текущем тарифе")
        try:
            content = make_pdf_bytes(meeting_payload)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        media_type = "application/pdf"
    elif fmt == "docx":
        if not (features.get("export_docx") or {}).get("is_enabled"):
            raise HTTPException(status_code=403, detail="Экспорт в DOCX недоступен на текущем тарифе")
        try:
            content = make_docx_bytes(meeting_payload)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        raise HTTPException(status_code=400, detail="Неподдерживаемый формат")

    filename = f"vocmind_meeting.{fmt}"
    return StreamingResponse(
        BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/activate-key")
def miniapp_activate_key(
    payload: ActivateKeyIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from ..models import ActivationKey

    key_obj = db.query(ActivationKey).filter(ActivationKey.key_value == payload.key.strip()).first()
    if not key_obj:
        raise HTTPException(status_code=404, detail="Key not found")

    sub, plan = _apply_key_to_user(db, current_user, key_obj)
    return {
        "ok": True,
        "plan": plan_to_payload(db, plan),
        "starts_at": sub.starts_at.isoformat() if sub.starts_at else None,
        "ends_at": sub.ends_at.isoformat() if sub.ends_at else None,
        "message": "Ключ активирован",
    }


@router.post("/extension-code")
def miniapp_extension_code(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return generate_link_code(db=db, current_user=current_user)

from urllib.parse import parse_qsl
import hashlib
import hmac

from ..config import settings
@router.post("/debug-init-data")
def debug_init_data(payload: TelegramAuthIn):
    pairs = dict(parse_qsl(payload.init_data, keep_blank_values=True))
    return {
        "bot_token_prefix": settings.telegram_bot_token[:12],
        "has_hash": "hash" in pairs,
        "has_signature": "signature" in pairs,
        "auth_date": pairs.get("auth_date"),
        "keys": sorted(list(pairs.keys())),
        "user": pairs.get("user"),
    }


@router.post("/debug-hash")
def debug_hash(payload: TelegramAuthIn):
    pairs = dict(parse_qsl(payload.init_data, keep_blank_values=True))

    received_hash = pairs.pop("hash", None)

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(pairs.items())
    )

    secret_key = hmac.new(
        b"WebAppData",
        settings.telegram_bot_token.strip().encode(),
        hashlib.sha256,
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    return {
        "bot_token_prefix": settings.telegram_bot_token[:12],
        "received_hash": received_hash,
        "calculated_hash": calculated_hash,
        "match": received_hash == calculated_hash,
        "data_check_string": data_check_string,
    }
