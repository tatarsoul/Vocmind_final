from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import decode_access_token
from ..config import settings


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()

    try:
        payload = decode_access_token(token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is disabled")

    return user


def require_internal_key(x_internal_key: str | None = Header(default=None)) -> None:
    if not x_internal_key or x_internal_key != settings.bot_internal_key:
        raise HTTPException(status_code=401, detail="Invalid internal key")