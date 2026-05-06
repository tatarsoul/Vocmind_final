"""Утилиты для постобработки транскрипта без зависимостей от LLM.

Эти функции работают синхронно и быстро — их безопасно вызывать в любом
месте pipeline (live-регенерация, финальный polish, экспорт).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher


_SPEAKER_RE = re.compile(r"^\s*(ME|THEM)\s*:\s*(.*)$")
_PUNCT_RE = re.compile(r"[^\w\s]+", flags=re.UNICODE)
_SPACES_RE = re.compile(r"\s+")


def _strip_speaker(line: str) -> tuple[str, str]:
    """Возвращает (speaker_label, content). speaker_label = '' если не нашли."""
    m = _SPEAKER_RE.match(line)
    if m:
        return m.group(1), m.group(2).strip()
    return "", line.strip()


def _normalize(s: str) -> str:
    s = s.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACES_RE.sub(" ", s).strip()
    return s


def dedupe_adjacent_repeats(transcript_text: str, *, similarity: float = 0.85) -> str:
    """Убирает дубли соседних реплик одного и того же спикера.

    Реальная боль из жалобы напарника: на длинных встречах whisper иногда
    возвращает одну и ту же фразу подряд два-три раза (например, "Я думаю,
    что это тогда целесообразно уже с руководителем обсудить" → встречается
    дважды подряд). Это случается из-за того, что transcribe_window
    обрабатывает скользящее окно, и в зоне перекрытия одни и те же слова
    транскрибируются повторно.

    Логика:
    - идём по строкам сверху вниз
    - если текущая строка того же спикера, что и предыдущая принятая, и
      её нормализованный текст совпадает по подстроке или ≥ similarity —
      оставляем более длинную (более информативную) версию
    - между разными спикерами не сравниваем (разные люди могут случайно
      сказать одно и то же)
    - окно сравнения = 1 (только последняя принятая строка). Это самое
      безопасное поведение: убираем явные дубли подряд, но не трогаем
      повторы по делу через несколько реплик.

    Args:
        transcript_text: исходный транскрипт (строки в формате "ME: ...",
                         "THEM: ...", или произвольные).
        similarity: порог нечёткого сходства (0.0..1.0). 0.85 хорошо ловит
                    почти-дубли с одной-двумя разными словами и не задевает
                    разные мысли.

    Returns:
        Очищенный транскрипт. Если на входе пусто — пустая строка.
    """
    if not transcript_text:
        return ""

    lines = [ln for ln in transcript_text.splitlines() if ln.strip()]
    if not lines:
        return ""

    out: list[tuple[str, str, str]] = []  # (raw_line, speaker, normalized_content)
    for line in lines:
        sp, content = _strip_speaker(line)
        if not content:
            continue
        norm = _normalize(content)
        if not norm:
            out.append((line, sp, ""))
            continue

        if out:
            prev_line, prev_sp, prev_norm = out[-1]
            if sp and prev_sp and sp == prev_sp and prev_norm:
                # точное совпадение или вхождение
                if norm == prev_norm or norm in prev_norm or prev_norm in norm:
                    if len(norm) > len(prev_norm):
                        out[-1] = (line, sp, norm)
                    continue
                # нечёткое сходство (только для достаточно длинных реплик —
                # на коротких 0.85 даёт ложные срабатывания)
                if len(norm) >= 20 and len(prev_norm) >= 20:
                    ratio = SequenceMatcher(None, norm, prev_norm).ratio()
                    if ratio >= similarity:
                        if len(norm) > len(prev_norm):
                            out[-1] = (line, sp, norm)
                        continue
        out.append((line, sp, norm))

    return "\n".join(item[0] for item in out)


def dedupe_global_long_repeats(transcript_text: str, *, similarity: float = 0.88, min_chars: int = 30) -> str:
    """Убирает дубли длинных реплик ЧЕРЕЗ ВЕСЬ ТРАНСКРИПТ (не только соседние).

    Реальная проблема из теста на 2.5 минут: whisper при определённых условиях
    (видимо когда mic+tab дорожки не вычищаются друг от друга, либо когда
    запись обрабатывается двумя проходами) выдаёт целые куски разговора
    повторно. Например, в начале записи и в конце:

        Начало:                                Конец:
        THEM: Подозрительными или если вы...   THEM: Подозрительными. Или если...
        THEM: Да и в целом будет интересно...  THEM: Да и в целом будет интересно...
        THEM: Добрый день, Виктория!           THEM: Добрый день, Виктория!

    Эта функция:
    - идёт по строкам и для каждой длинной (>= min_chars) реплики проверяет,
      не было ли уже принято что-то очень похожее
    - если было — пропускает текущую (как дубль)
    - короткие реплики (< min_chars) пропускает без проверки, потому что
      «да», «окей», «понятно» могут законно повторяться много раз

    Применяется ПОСЛЕ adjacent dedup. Не трогает короткие реплики, чтобы не
    схлопывать живой диалог.
    """
    if not transcript_text:
        return ""

    lines = [ln for ln in transcript_text.splitlines() if ln.strip()]
    if not lines:
        return ""

    out_raw: list[str] = []
    accepted_norms: list[str] = []  # все принятые длинные нормализованные тексты

    for line in lines:
        sp, content = _strip_speaker(line)
        if not content:
            continue
        norm = _normalize(content)
        # Короткие — пропускаем без проверки уникальности
        if len(norm) < min_chars:
            out_raw.append(line)
            continue

        # Проверяем, не дублирует ли эта строка какую-то ранее принятую
        is_dup = False
        for prev_norm in accepted_norms:
            if norm == prev_norm or norm in prev_norm or prev_norm in norm:
                is_dup = True
                break
            # Нечёткое сходство только если длины сопоставимы (иначе короткая
            # фраза может «совпасть» с куском длинной)
            if 0.7 <= len(norm) / max(len(prev_norm), 1) <= 1.3:
                ratio = SequenceMatcher(None, norm, prev_norm).ratio()
                if ratio >= similarity:
                    is_dup = True
                    break
        if is_dup:
            continue

        out_raw.append(line)
        accepted_norms.append(norm)

    return "\n".join(out_raw)


def clean_transcript(transcript_text: str) -> str:
    """Полная двухступенчатая чистка транскрипта от ASR-шумов.

    1. dedupe_adjacent_repeats — убирает соседние повторы одного спикера
       (типичная whisper-ошибка от перекрывающихся окон).
    2. dedupe_global_long_repeats — убирает большие повторы через всю встречу
       (когда mic+tab дают одну и ту же запись, или когда whisper второй раз
       проходит по уже обработанному звуку).

    Безопасно для всех типов разговоров: короткие реплики не трогаются,
    разные спикеры не путаются.
    """
    text = transcript_text or ""
    if not text.strip():
        return ""
    text = dedupe_adjacent_repeats(text)
    text = dedupe_global_long_repeats(text)
    return text
