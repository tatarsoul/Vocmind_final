import json
import time
from typing import Dict, List

from .groq import groq_chat_json


TRIGGERS_PROMPT_RU = """Ты — ассистент для анализа звонков (продажи/переговоры).
Тебе дают ПОСЛЕДНИЕ ~90 секунд транскрипта с пометками SPEAKER_0/1.

Верни СТРОГО JSON-объект вида:
{
  "client_dissatisfaction": true/false,
  "client_doubt": true/false,
  "new_important_task": true/false,
  "client_interest": true/false,
  "evasion_detected": true/false
}

Правила:
- НЕ выдумывай. true ставь только если есть явные признаки в тексте.
- Если не уверен — false.
- Отвечай ТОЛЬКО валидным JSON, без текста вокруг.
"""


def _safe_json_loads(s: str) -> dict:
    try:
        return json.loads(s)
    except Exception:
        # try extract first json object
        s = (s or "").strip()
        start = s.find("{")
        if start == -1:
            return {}
        depth = 0
        for i in range(start, len(s)):
            ch = s[i]
            if ch == "{": depth += 1
            if ch == "}": 
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start:i+1])
                    except Exception:
                        return {}
        return {}


async def analyze_live_triggers(window_text: str, timeout_s: float = 45.0) -> Dict[str, bool]:
    window_text = (window_text or "").strip()
    if not window_text:
        return {}

    try:
        obj = await groq_chat_json(
            TRIGGERS_PROMPT_RU,
            f"Транскрипт окна:\n{window_text}\n\nJSON:",
            temperature=0.0,
            timeout_s=timeout_s,
        )
    except Exception:
        return {}
    out: Dict[str, bool] = {}
    for k in ["client_dissatisfaction", "client_doubt", "new_important_task", "client_interest", "evasion_detected"]:
        v = obj.get(k, False)
        out[k] = bool(v) if isinstance(v, (bool, int)) else False
    return out


def merge_and_dedupe_events(existing: List[dict], new_items: List[dict], max_items: int = 80) -> List[dict]:
    """Merge new events into existing list without duplicating same trigger too often."""
    existing = list(existing or [])
    new_items = list(new_items or [])
    if not new_items:
        return existing[-max_items:]

    seen = set()
    for it in existing:
        key = (it.get("type"), it.get("trigger"), it.get("title"), it.get("detail"))
        seen.add(key)

    for it in new_items:
        key = (it.get("type"), it.get("trigger"), it.get("title"), it.get("detail"))
        if key in seen:
            continue
        existing.append(it)
        seen.add(key)

    return existing[-max_items:]
