import json
import asyncio
from typing import Any, Dict, Optional

import httpx

from ..config import settings


def _extract_first_json_object(text: str) -> Optional[dict]:
    """
    Пытаемся вытащить первый JSON-объект { ... } из строки.
    Работает, если модель обернула ответ в текст/```json``` и т.п.
    """
    if not text:
        return None

    s = text.strip()

    # Частый случай: ```json ... ```
    if "```" in s:
        # вырежем все ```...``` и попробуем распарсить содержимое
        parts = s.split("```")
        # обычно JSON внутри второго блока
        for p in parts:
            p2 = p.strip()
            if p2.lower().startswith("json"):
                p2 = p2[4:].strip()
            # попробуем прямой json.loads
            try:
                obj = json.loads(p2)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

    # Прямой JSON
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Поиск первого {...} с балансом скобок
    start = s.find("{")
    if start == -1:
        return None

    depth = 0
    for i in range(start, len(s)):
        ch = s[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                chunk = s[start : i + 1]
                try:
                    obj = json.loads(chunk)
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    return None
    return None


async def groq_chat_json(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str | None = None,
    temperature: float = 0.3,
    timeout_s: float | None = None,
) -> Dict[str, Any]:
    api_key = (settings.groq_api_key or "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")

    model_name = model or settings.groq_model
    timeout_val = float(timeout_s) if timeout_s is not None else float(settings.groq_timeout_seconds)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "VocMind/1.0",
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": float(temperature),
        "response_format": {"type": "json_object"},
    }

    # retry policy
    # ВАЖНО: rate limit (429) на Groq обычно длится 5-30 секунд, поэтому для
    # него стратегия более агрессивная: больше попыток и большой backoff.
    # Для остальных временных ошибок (5xx) хватает короткой стратегии.
    max_attempts_default = 3
    max_attempts_429 = 5  # 5 попыток с возрастающим backoff
    base_backoff = 0.6  # seconds
    base_backoff_429 = 4.0  # seconds — стартуем с 4 сек на rate limit

    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout_val) as client:
        attempt = 0
        max_attempts = max_attempts_default  # будем динамически увеличивать на 429
        while True:
            attempt += 1
            try:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )

                # Rate limit — пробуем дольше и слушаем Retry-After
                if r.status_code == 429:
                    max_attempts = max(max_attempts, max_attempts_429)
                    if attempt < max_attempts:
                        # Groq возвращает Retry-After в секундах; используем его если есть
                        retry_after_hdr = r.headers.get("retry-after") or r.headers.get("Retry-After")
                        try:
                            retry_after = float(retry_after_hdr) if retry_after_hdr else None
                        except (TypeError, ValueError):
                            retry_after = None
                        wait_s = retry_after if retry_after else base_backoff_429 * (2 ** (attempt - 1))
                        # ограничиваем сверху чтобы не висеть бесконечно
                        wait_s = min(wait_s, 30.0)
                        await asyncio.sleep(wait_s)
                        continue

                # Прочие временные — короткий backoff
                if r.status_code in (500, 502, 503, 504):
                    if attempt < max_attempts:
                        await asyncio.sleep(base_backoff * (2 ** (attempt - 1)))
                        continue

                r.raise_for_status()
                data = r.json()

                content = (
                    (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""
                )

                obj = _extract_first_json_object(content)
                if obj is None:
                    preview = (content or "")[:400].replace("\n", "\\n")
                    raise RuntimeError(f"Groq returned non-JSON content (preview): {preview}")

                return obj

            except Exception as e:
                last_err = e
                if attempt < max_attempts:
                    await asyncio.sleep(base_backoff * (2 ** (attempt - 1)))
                    continue
                break

    raise RuntimeError(f"Groq request failed after retries: {last_err}") from last_err