from __future__ import annotations

import math
import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import Meeting, Plan, PlanFeature, Subscription, SubscriptionStatus
from .plan_features import enrich_feature_payload
from .exports import export_runtime_status
from .protocol import render_protocol_text


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


def get_plan_features(db: Session, plan_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    rows = db.query(PlanFeature).filter(PlanFeature.plan_id == plan_id).all()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        out[row.feature_code] = enrich_feature_payload(
            row.feature_code,
            {
                "is_enabled": bool(row.is_enabled),
                "feature_value": row.feature_value,
            },
        )
    return out


def plan_to_payload(db: Session, plan: Plan | None) -> dict[str, Any] | None:
    if not plan:
        return None
    features = get_plan_features(db, plan.id)
    return {
        "code": plan.code,
        "title": plan.title,
        "description": plan.description,
        "monthly_minutes": plan.monthly_minutes,
        "meeting_storage_limit": plan.meeting_storage_limit,
        "features": features,
    }


def feature_enabled(features: dict[str, dict[str, Any]] | None, feature_code: str) -> bool:
    if not features:
        return False
    return bool((features.get(feature_code) or {}).get("is_enabled"))


def meeting_storage_limit(plan: Plan | None, features: dict[str, dict[str, Any]] | None) -> int | None:
    if not plan:
        return None
    if feature_enabled(features, "unlimited_storage"):
        return None
    return plan.meeting_storage_limit


def _usage_time_bounds(sub: Subscription | None) -> tuple[datetime | None, datetime | None]:
    if not sub:
        return None, None
    start = sub.starts_at
    end = sub.ends_at or datetime.utcnow()
    return start, end


def compute_usage(db: Session, user_id: uuid.UUID, sub: Subscription | None, plan: Plan | None, features: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    now = datetime.utcnow()
    start, end = _usage_time_bounds(sub)

    meetings_q = db.query(Meeting).filter(Meeting.user_id == user_id)
    if start is not None:
        meetings_q = meetings_q.filter(Meeting.created_at >= start)
    if end is not None:
        meetings_q = meetings_q.filter(Meeting.created_at <= end)

    total_seconds = meetings_q.with_entities(func.coalesce(func.sum(Meeting.duration_seconds), 0)).scalar() or 0
    meetings_count = meetings_q.count()
    used_minutes = int(math.ceil(max(int(total_seconds), 0) / 60.0)) if total_seconds else 0

    remaining_minutes = None
    if plan and plan.monthly_minutes is not None:
        remaining_minutes = max(int(plan.monthly_minutes) - int(used_minutes), 0)

    storage_limit = meeting_storage_limit(plan, features)
    stored_meetings_count = db.query(Meeting).filter(Meeting.user_id == user_id).count()

    return {
        "period_year": now.year,
        "period_month": now.month,
        "used_minutes": used_minutes,
        "remaining_minutes": remaining_minutes,
        "meetings_count": meetings_count,
        "stored_meetings_count": stored_meetings_count,
        "storage_limit": storage_limit,
        "storage_remaining": None if storage_limit is None else max(storage_limit - stored_meetings_count, 0),
        "total_seconds": int(total_seconds or 0),
    }


def get_user_plan_context(db: Session, user_id: uuid.UUID) -> dict[str, Any]:
    sub = get_active_subscription(db, user_id)
    plan = db.query(Plan).filter(Plan.id == sub.plan_id).first() if sub else None
    features = get_plan_features(db, plan.id) if plan else {}
    usage = compute_usage(db, user_id, sub, plan, features)
    return {
        "subscription": sub,
        "plan": plan,
        "features": features,
        "usage": usage,
    }


def ensure_recording_allowed(db: Session, user_id: uuid.UUID) -> dict[str, Any]:
    ctx = get_user_plan_context(db, user_id)
    sub = ctx["subscription"]
    plan = ctx["plan"]
    features = ctx["features"]
    usage = ctx["usage"]

    if not sub or not plan:
        return {"ok": False, "detail": "Нет активного тарифа"}

    if not feature_enabled(features, "transcription"):
        return {"ok": False, "detail": "На тарифе недоступна запись и транскрибация"}

    if usage["remaining_minutes"] is not None and usage["remaining_minutes"] <= 0:
        return {"ok": False, "detail": "Минуты по тарифу закончились"}

    storage_limit = usage["storage_limit"]
    if storage_limit is not None and usage["stored_meetings_count"] >= storage_limit:
        return {"ok": False, "detail": "Достигнут лимит хранения встреч. Удалите старые записи или перейдите на более высокий тариф"}

    return {"ok": True, **ctx}


def strip_speaker_labels(transcript: str) -> str:
    lines: list[str] = []
    for raw in (transcript or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("===") and line.endswith("==="):
            continue
        for prefix in ("ME:", "THEM:"):
            if line.upper().startswith(prefix):
                line = line[len(prefix):].strip()
                break
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def meeting_to_payload(meeting: Meeting, features: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    runtime_exports = export_runtime_status()
    allow_export_pdf = feature_enabled(features, "export_pdf") and runtime_exports.get("pdf", False)
    allow_export_docx = feature_enabled(features, "export_docx") and runtime_exports.get("docx", False)
    allow_analytics = feature_enabled(features, "meeting_analytics")
    protocol_json = meeting.protocol_json or {}
    protocol_text = render_protocol_text(protocol_json) if isinstance(protocol_json, dict) and protocol_json else (meeting.protocol_text or "")
    return {
        "id": str(meeting.id),
        "title": meeting.title or "Встреча",
        "status": meeting.status.value if hasattr(meeting.status, "value") else str(meeting.status),
        "started_at": meeting.started_at.isoformat() if meeting.started_at else None,
        "finished_at": meeting.finished_at.isoformat() if meeting.finished_at else None,
        "duration_seconds": int(meeting.duration_seconds or 0),
        "capture_mode": meeting.capture_mode,
        "source_type": meeting.source_type,
        "language_code": meeting.language_code,
        "transcript_text": meeting.transcript_text or "",
        "protocol_text": protocol_text,
        "protocol_json": protocol_json,
        "analytics_json": meeting.analytics_json if allow_analytics else None,
        "live_hints_json": meeting.live_hints_json or {},
        "exports": {
            "pdf": allow_export_pdf,
            "docx": allow_export_docx,
        },
    }


def search_meetings_query(db: Session, user_id: uuid.UUID, q: str | None = None):
    query = db.query(Meeting).filter(Meeting.user_id == user_id)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Meeting.title.ilike(pattern),
                Meeting.searchable_text.ilike(pattern),
                Meeting.transcript_text.ilike(pattern),
                Meeting.protocol_text.ilike(pattern),
            )
        )
    return query.order_by(Meeting.created_at.desc())


def summarize_meeting_analytics(db: Session, user_id: uuid.UUID, features: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    from .meeting_analytics import build_meeting_analytics

    if not feature_enabled(features, "meeting_analytics"):
        return {
            "enabled": False,
            "totals": {},
            "timeline": [],
            "top_keywords": [],
            "top_topics": [],
            "recent_meetings": [],
            "talk_balance": {"me_percent": None, "them_percent": None},
        }

    rows = (
        db.query(Meeting)
        .filter(Meeting.user_id == user_id)
        .order_by(Meeting.started_at.desc().nullslast(), Meeting.created_at.desc())
        .all()
    )

    keyword_counter: Counter[str] = Counter()
    topic_counter: Counter[str] = Counter()
    timeline_map: dict[str, dict[str, Any]] = {}
    recent_meetings: list[dict[str, Any]] = []

    meetings_with_analytics = 0
    total_duration_seconds = 0
    total_words = 0
    total_questions = 0
    total_topics = 0
    total_decisions = 0
    total_action_items = 0
    total_risks = 0
    total_me_words = 0.0
    total_them_words = 0.0

    for row in rows:
        analytics = row.analytics_json or build_meeting_analytics(row.transcript_text or "", row.protocol_json or {})
        started = row.started_at or row.created_at
        started_iso = started.isoformat() if started else None
        duration_seconds = int(row.duration_seconds or 0)
        total_duration_seconds += duration_seconds

        word_count = int((analytics or {}).get("word_count") or 0)
        questions_count = int((analytics or {}).get("questions_count") or 0)
        topics_count = int((analytics or {}).get("topics_count") or 0)
        decisions_count = int((analytics or {}).get("decisions_count") or 0)
        action_items_count = int((analytics or {}).get("action_items_count") or 0)
        risks_count = int((analytics or {}).get("risks_count") or 0)

        if analytics:
            meetings_with_analytics += 1

        total_words += word_count
        total_questions += questions_count
        total_topics += topics_count
        total_decisions += decisions_count
        total_action_items += action_items_count
        total_risks += risks_count

        balance = (analytics or {}).get("talk_balance") or {}
        me_percent = balance.get("me_percent")
        them_percent = balance.get("them_percent")
        if isinstance(me_percent, (int, float)):
            total_me_words += word_count * float(me_percent) / 100.0
        if isinstance(them_percent, (int, float)):
            total_them_words += word_count * float(them_percent) / 100.0

        for keyword in (analytics or {}).get("top_keywords") or []:
            keyword = str(keyword or "").strip().lower()
            if keyword:
                keyword_counter[keyword] += 1

        for topic in (analytics or {}).get("topics") or []:
            topic = str(topic or "").strip()
            if topic:
                topic_counter[topic] += 1

        if started:
            day_key = started.strftime("%Y-%m-%d")
            bucket = timeline_map.setdefault(day_key, {
                "date": day_key,
                "label": started.strftime("%d.%m"),
                "meetings": 0,
                "duration_seconds": 0,
                "word_count": 0,
                "questions_count": 0,
                "decisions_count": 0,
                "action_items_count": 0,
            })
            bucket["meetings"] += 1
            bucket["duration_seconds"] += duration_seconds
            bucket["word_count"] += word_count
            bucket["questions_count"] += questions_count
            bucket["decisions_count"] += decisions_count
            bucket["action_items_count"] += action_items_count

        if len(recent_meetings) < 8:
            recent_meetings.append({
                "id": str(row.id),
                "title": row.title or "Встреча",
                "started_at": started_iso,
                "duration_seconds": duration_seconds,
                "word_count": word_count,
                "questions_count": questions_count,
                "decisions_count": decisions_count,
                "action_items_count": action_items_count,
                "risks_count": risks_count,
            })

    timeline = sorted(timeline_map.values(), key=lambda x: x["date"])[-10:]
    total_speaker_words = total_me_words + total_them_words
    avg_duration_seconds = int(round(total_duration_seconds / len(rows))) if rows else 0
    talk_balance = {
        "me_percent": round((total_me_words / total_speaker_words) * 100, 1) if total_speaker_words else None,
        "them_percent": round((total_them_words / total_speaker_words) * 100, 1) if total_speaker_words else None,
    }

    return {
        "enabled": True,
        "totals": {
            "meetings_total": len(rows),
            "meetings_with_analytics": meetings_with_analytics,
            "total_duration_seconds": total_duration_seconds,
            "avg_duration_seconds": avg_duration_seconds,
            "word_count": total_words,
            "questions_count": total_questions,
            "topics_count": total_topics,
            "decisions_count": total_decisions,
            "action_items_count": total_action_items,
            "risks_count": total_risks,
        },
        "timeline": timeline,
        "top_keywords": [{"keyword": k, "count": v} for k, v in keyword_counter.most_common(12)],
        "top_topics": [{"topic": k, "count": v} for k, v in topic_counter.most_common(8)],
        "recent_meetings": recent_meetings,
        "talk_balance": talk_balance,
    }
