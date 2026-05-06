import secrets
import string
from datetime import datetime, timedelta
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..api_schemas import (
    ConnectExtensionIn,
    ConnectExtensionOut,
    GenerateExtensionCodeOut,
    PlanOut,
    SubscriptionShortOut,
    UsageOut,
)
from ..config import settings
from ..db import get_db
from ..deps.auth import get_current_user
from ..models import (
    ExtensionDevice,
    ExtensionLinkCode,
    Meeting,
    User,
)
from ..services.exports import make_docx_bytes, make_pdf_bytes
from ..services.usage import (
    get_active_subscription,
    get_user_plan_context,
    meeting_to_payload,
    plan_to_payload,
    search_meetings_query,
)

router = APIRouter(prefix="/extension", tags=["extension"])


def _rand_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))



def _require_device(db: Session, device_token: str) -> ExtensionDevice:
    device = db.query(ExtensionDevice).filter(ExtensionDevice.device_token == device_token, ExtensionDevice.is_active == True).first()
    if not device:
        raise HTTPException(status_code=401, detail="Устройство не найдено или отключено")
    device.last_seen_at = datetime.utcnow()
    db.commit()
    db.refresh(device)
    return device



def _connect_response(db: Session, user_id) -> ConnectExtensionOut:
    ctx = get_user_plan_context(db, user_id)
    sub = ctx["subscription"]
    plan = ctx["plan"]
    usage = ctx["usage"]

    plan_out = PlanOut(**(plan_to_payload(db, plan) or {})) if plan else None
    subscription_out = None
    if sub:
        subscription_out = SubscriptionShortOut(
            status=sub.status.value if hasattr(sub.status, "value") else str(sub.status),
            starts_at=sub.starts_at.isoformat() if sub.starts_at else "",
            ends_at=sub.ends_at.isoformat() if sub.ends_at else None,
        )

    usage_out = UsageOut(
        period_year=usage["period_year"],
        period_month=usage["period_month"],
        used_minutes=usage["used_minutes"],
        remaining_minutes=usage["remaining_minutes"],
        meetings_count=usage["stored_meetings_count"],
    )
    return ConnectExtensionOut(
        ok=True,
        device_token="",
        user_id=str(user_id),
        plan=plan_out,
        subscription=subscription_out,
        usage=usage_out,
    )


@router.post("/generate-link-code", response_model=GenerateExtensionCodeOut)
def generate_link_code(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db.query(ExtensionLinkCode).filter(
        ExtensionLinkCode.user_id == current_user.id,
        ExtensionLinkCode.is_active == True,
    ).update({"is_active": False})

    expires_at = datetime.utcnow() + timedelta(minutes=settings.extension_link_code_ttl_minutes)
    code = _rand_code(8)

    row = ExtensionLinkCode(
        user_id=current_user.id,
        code=code,
        expires_at=expires_at,
        is_active=True,
    )
    db.add(row)
    db.commit()

    return GenerateExtensionCodeOut(
        code=code,
        expires_at=expires_at.isoformat(),
    )


@router.post("/connect", response_model=ConnectExtensionOut)
def connect_extension(payload: ConnectExtensionIn, db: Session = Depends(get_db)):
    now = datetime.utcnow()

    code_row = (
        db.query(ExtensionLinkCode)
        .filter(
            ExtensionLinkCode.code == payload.code.strip().upper(),
            ExtensionLinkCode.is_active == True,
        )
        .first()
    )
    if not code_row:
        raise HTTPException(status_code=404, detail="Link code not found")

    if code_row.expires_at < now:
        code_row.is_active = False
        db.commit()
        raise HTTPException(status_code=400, detail="Link code expired")

    user = db.query(User).filter(User.id == code_row.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    device_token = secrets.token_urlsafe(32)

    device = ExtensionDevice(
        user_id=user.id,
        device_name=payload.device_name,
        browser_name=payload.browser_name,
        os_name=payload.os_name,
        extension_version=payload.extension_version,
        device_token=device_token,
        is_active=True,
        last_seen_at=now,
    )
    db.add(device)

    code_row.is_active = False
    code_row.used_at = now
    db.commit()

    resp = _connect_response(db, user.id)
    resp.device_token = device_token
    return resp


@router.get("/device-dashboard")
def device_dashboard(device_token: str = Query(...), db: Session = Depends(get_db)):
    device = _require_device(db, device_token)
    resp = _connect_response(db, device.user_id)
    payload = resp.model_dump()
    payload["device_token"] = device_token
    return payload


@router.get("/meetings")
def device_meetings(
    device_token: str = Query(...),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    device = _require_device(db, device_token)
    ctx = get_user_plan_context(db, device.user_id)
    features = ctx["features"]
    if q and not (features.get("meeting_search") or {}).get("is_enabled"):
        raise HTTPException(status_code=403, detail="Поиск по встречам недоступен на текущем тарифе")
    rows = search_meetings_query(db, device.user_id, q=q).limit(100).all()
    return {
        "items": [meeting_to_payload(row, features) for row in rows],
        "features": features,
    }


@router.delete("/meetings/{meeting_id}")
def delete_device_meeting(meeting_id: str, device_token: str = Query(...), db: Session = Depends(get_db)):
    device = _require_device(db, device_token)
    row = db.query(Meeting).filter(Meeting.id == meeting_id, Meeting.user_id == device.user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Встреча не найдена")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/meetings/{meeting_id}/export/{fmt}")
def export_device_meeting(meeting_id: str, fmt: str, device_token: str = Query(...), db: Session = Depends(get_db)):
    device = _require_device(db, device_token)
    ctx = get_user_plan_context(db, device.user_id)
    features = ctx["features"]
    row = db.query(Meeting).filter(Meeting.id == meeting_id, Meeting.user_id == device.user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Встреча не найдена")

    meeting_payload = meeting_to_payload(row, features)
    safe_name = "vocmind_meeting"
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
    filename = f"{safe_name}.{fmt}"
    return StreamingResponse(
        BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
