from pydantic import BaseModel, Field
from typing import Any


class TelegramAuthIn(BaseModel):
    init_data: str = Field(..., description="Telegram Mini App initData")


class UserOut(BaseModel):
    id: str
    telegram_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    role: str
    is_active: bool


class AuthOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class PlanOut(BaseModel):
    code: str
    title: str
    description: str | None = None
    monthly_minutes: int
    meeting_storage_limit: int | None = None
    features: dict[str, dict[str, Any]]


class MeOut(BaseModel):
    user: UserOut


class ActivateKeyIn(BaseModel):
    key: str


class ActivateKeyOut(BaseModel):
    ok: bool
    plan: PlanOut
    starts_at: str
    ends_at: str | None = None


class CreateActivationKeyOut(BaseModel):
    key: str
    plan_code: str
    duration_days: int | None = None
    max_uses: int | None = None
    expires_at: str | None = None


class GenerateExtensionCodeOut(BaseModel):
    code: str
    expires_at: str


class ConnectExtensionIn(BaseModel):
    code: str
    device_name: str | None = None
    browser_name: str | None = None
    os_name: str | None = None
    extension_version: str | None = None


class SubscriptionShortOut(BaseModel):
    status: str
    starts_at: str
    ends_at: str | None = None


class UsageOut(BaseModel):
    period_year: int
    period_month: int
    used_minutes: int
    remaining_minutes: int | None = None
    meetings_count: int = 0


class ConnectExtensionOut(BaseModel):
    ok: bool
    device_token: str
    user_id: str
    plan: PlanOut | None = None
    subscription: SubscriptionShortOut | None = None
    usage: UsageOut | None = None

class BotActivateKeyIn(BaseModel):
    telegram_id: int
    key: str