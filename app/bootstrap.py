from sqlalchemy import select

from .db import engine, SessionLocal, Base
from . import models


PLAN_CONFIG = {
    "base": {
        "title": "Базовый (знакомство)",
        "description": "120 минут записи в месяц, AI-протокол встречи и хранение 3 встреч.",
        "monthly_minutes": 120,
        "meeting_storage_limit": 3,
        "sort_order": 1,
        "features": {
            "transcription": True,
            "ai_protocol": True,
            "export_pdf": False,
            "export_docx": False,
            "speaker_diarization": False,
            "meeting_search": False,
            "live_hints": False,
            "meeting_analytics": False,
            "unlimited_storage": False,
            "tasks_and_decisions": False,
        },
    },
    "personal": {
        "title": "Персональный",
        "description": "600 минут записи в месяц, AI-протокол встречи и экспорт в PDF/DOCX.",
        "monthly_minutes": 600,
        "meeting_storage_limit": 30,
        "sort_order": 2,
        "features": {
            "transcription": True,
            "ai_protocol": True,
            "export_pdf": True,
            "export_docx": True,
            "speaker_diarization": False,
            "meeting_search": False,
            "live_hints": False,
            "meeting_analytics": False,
            "unlimited_storage": False,
            "tasks_and_decisions": False,
        },
    },
    "pro": {
        "title": "Профессиональный",
        "description": "2000 минут записи, задачи и решения, разделение спикеров, поиск по встречам и live-подсказки.",
        "monthly_minutes": 2000,
        "meeting_storage_limit": 200,
        "sort_order": 3,
        "features": {
            "transcription": True,
            "ai_protocol": True,
            "export_pdf": True,
            "export_docx": True,
            "speaker_diarization": True,
            "meeting_search": True,
            "live_hints": True,
            "meeting_analytics": False,
            "unlimited_storage": False,
            "tasks_and_decisions": True,
        },
    },
    "extended": {
        "title": "Расширенный",
        "description": "Всё из профессионального тарифа плюс аналитика встреч и неограниченное хранение.",
        "monthly_minutes": 2000,
        "meeting_storage_limit": None,
        "sort_order": 4,
        "features": {
            "transcription": True,
            "ai_protocol": True,
            "export_pdf": True,
            "export_docx": True,
            "speaker_diarization": True,
            "meeting_search": True,
            "live_hints": True,
            "meeting_analytics": True,
            "unlimited_storage": True,
            "tasks_and_decisions": True,
        },
    },
    "admin": {
        "title": "Админский",
        "description": "Полный безлимит и все функции без ограничений.",
        "monthly_minutes": 999999,
        "meeting_storage_limit": None,
        "sort_order": 99,
        "features": {
            "transcription": True,
            "ai_protocol": True,
            "export_pdf": True,
            "export_docx": True,
            "speaker_diarization": True,
            "meeting_search": True,
            "live_hints": True,
            "meeting_analytics": True,
            "unlimited_storage": True,
            "tasks_and_decisions": True,
        },
    },
}


def seed_plans():
    db = SessionLocal()
    try:
        for code, data in PLAN_CONFIG.items():
            plan = db.execute(
                select(models.Plan).where(models.Plan.code == code)
            ).scalar_one_or_none()

            if not plan:
                plan = models.Plan(
                    code=code,
                    title=data["title"],
                    description=data["description"],
                    monthly_minutes=data["monthly_minutes"],
                    meeting_storage_limit=data["meeting_storage_limit"],
                    sort_order=data["sort_order"],
                    is_active=True,
                )
                db.add(plan)
                db.flush()
            else:
                plan.title = data["title"]
                plan.description = data["description"]
                plan.monthly_minutes = data["monthly_minutes"]
                plan.meeting_storage_limit = data["meeting_storage_limit"]
                plan.sort_order = data["sort_order"]
                plan.is_active = True

            existing = db.execute(
                select(models.PlanFeature).where(models.PlanFeature.plan_id == plan.id)
            ).scalars().all()

            existing_map = {x.feature_code: x for x in existing}

            for feature_code, enabled in data["features"].items():
                row = existing_map.get(feature_code)
                if not row:
                    row = models.PlanFeature(
                        plan_id=plan.id,
                        feature_code=feature_code,
                        is_enabled=bool(enabled),
                    )
                    db.add(row)
                else:
                    row.is_enabled = bool(enabled)
        db.commit()
    finally:
        db.close()



def bootstrap_database():
    Base.metadata.create_all(bind=engine)
    seed_plans()
