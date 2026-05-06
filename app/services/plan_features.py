from __future__ import annotations

from typing import Any

FEATURE_CATALOG: dict[str, dict[str, str]] = {
    "transcription": {
        "title": "Базовая транскрибация",
        "description": "Распознавание записи в текст.",
    },
    "ai_protocol": {
        "title": "AI-протокол встречи",
        "description": "Краткая сводка встречи с ключевыми темами.",
    },
    "export_pdf": {
        "title": "Экспорт в PDF",
        "description": "Выгрузка встречи и протокола в PDF.",
    },
    "export_docx": {
        "title": "Экспорт в DOCX",
        "description": "Выгрузка встречи и протокола в DOCX.",
    },
    "tasks_and_decisions": {
        "title": "Задачи и решения",
        "description": "Автоматическое выделение решений и action items.",
    },
    "speaker_diarization": {
        "title": "Разделение спикеров",
        "description": "Отдельные реплики говорящих: ME и THEM.",
    },
    "meeting_search": {
        "title": "Поиск по встречам",
        "description": "Поиск по названию, транскрипту и протоколу встреч.",
    },
    "live_hints": {
        "title": "Live-подсказки",
        "description": "Подсказки и инсайты во время звонка.",
    },
    "meeting_analytics": {
        "title": "Аналитика встреч",
        "description": "Метрики разговора, баланс спикеров, вопросы и риски.",
    },
    "unlimited_storage": {
        "title": "Неограниченное хранение",
        "description": "История встреч без лимита на количество сохранений.",
    },
}


def enrich_feature_payload(feature_code: str, value: dict[str, Any] | None) -> dict[str, Any]:
    meta = FEATURE_CATALOG.get(feature_code, {})
    out = dict(value or {})
    out.setdefault("title", meta.get("title") or feature_code)
    out.setdefault("description", meta.get("description") or "Функция активна")
    return out
