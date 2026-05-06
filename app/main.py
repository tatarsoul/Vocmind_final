from __future__ import annotations

import asyncio
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .bootstrap import bootstrap_database
from .config import settings
from .db import SessionLocal
from .models import ExtensionDevice, Meeting, MeetingStatus
from .routers.auth import router as auth_router
from .routers.billing import router as billing_router
from .routers.bot import router as bot_router
from .routers.extension import router as extension_router
from .routers.miniapp import router as miniapp_router
from .services.groq import groq_chat_json
from .services.meeting_analytics import build_meeting_analytics
from .services.protocol import (
    finalize_protocol_via_groq,
    generate_protocol_via_groq,
    generate_protocol_via_groq_chunked,
    normalize_protocol_state,
    protocol_from_transcript,
    regenerate_protocol_via_groq,
    render_protocol_text,
    searchable_protocol_strings,
    update_protocol_state_via_groq,
)
from .services.streaming import registry, pcm16_bytes_to_np
from .services.transcript_utils import clean_transcript
from .services.usage import ensure_recording_allowed, get_user_plan_context, strip_speaker_labels

app = FastAPI(title="VocMind")
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(extension_router)
app.include_router(bot_router)
app.include_router(miniapp_router)


@app.on_event("startup")
def on_startup():
    bootstrap_database()


@app.get("/health")
def health():
    return {"ok": True}


def log(msg: str):
    now = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{now}] {msg}")


# NVIDIA DLL fix for Windows
try:
    for p in sys.path:
        nvidia_dir = os.path.join(p, "nvidia")
        if os.path.exists(nvidia_dir):
            for module in os.listdir(nvidia_dir):
                bin_dir = os.path.join(nvidia_dir, module, "bin")
                if os.path.exists(bin_dir):
                    os.add_dll_directory(bin_dir)
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
except Exception as e:
    log(f"Warning: Could not add NVIDIA DLL directories: {e}")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_cache_for_frontend(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/lk"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


MINIAPP_DIR = Path(__file__).resolve().parent.parent / "vocmind-miniapp"
if MINIAPP_DIR.exists():
    app.mount("/lk", StaticFiles(directory=str(MINIAPP_DIR), html=True), name="miniapp_lk")


gpu_lock = asyncio.Lock()
ENABLE_LIVE_TRIGGERS = True

# Флаги pipeline теперь управляются через .env (см. app/config.py).
# По умолчанию live-протокол ОТКЛЮЧЁН — он много дёргает Groq, ловит 429
# и тормозит запись, а финальная регенерация всё равно перезаписывает
# результат. Если кому-то нужен live — поставит в .env ENABLE_LIVE_PROTOCOL=true.
ENABLE_LIVE_PROTOCOL = bool(getattr(settings, "enable_live_protocol", False))
ENABLE_TRANSCRIPT_POLISH = bool(getattr(settings, "enable_transcript_polish", True))
ENABLE_FINAL_RETRANSCRIBE = bool(getattr(settings, "enable_final_retranscribe", False))

TRIGGERS_UPDATE_EVERY_CHUNKS = settings.triggers_update_every_chunks
PROTOCOL_UPDATE_EVERY_CHUNKS = settings.protocol_update_every_chunks
PROTOCOL_UPDATE_EVERY_SECONDS = settings.protocol_update_every_seconds

# Если live-протокол выключен — не имеет смысла ждать фоновую регенерацию
# на финише: её и нет. Если включен — даём короткое окно, но не 30 сек.
PROTOCOL_BG_JOIN_TIMEOUT_S = 5.0 if ENABLE_LIVE_PROTOCOL else 0.0


def _new_empty_protocol_state() -> dict:
    return normalize_protocol_state(None)


def _compose_state(protocol_state: dict, insights: list, *, triggers: dict | None = None) -> dict:
    st = dict(protocol_state or _new_empty_protocol_state())
    st["insights"] = list(insights or [])
    st["triggers"] = dict(triggers or {})
    return st


def _clean_hallucinations(text: str) -> str:
    if not text:
        return ""

    bad_phrases = [
        # Whisper-галлюцинации (имена/субтитры/прочий веб-аудио мусор).
        "редактор субтитров", "а.синецкая", "синецкая", "а.егорова",
        "динамичная музыка", "позитивная музыка", "продолжение следует",
        "субтитры создавал", "субтитры субтитры", "субтитры", "музыка",
        "спасибо за просмотр", "подписывайтесь на наш канал", "подписывайтесь",
        # Системные сообщения видеоконференций (Zoom/Meet/Telemost).
        "recording in progress", "recording stopped", "recording started",
        "this meeting is being recorded",
        "запись начата", "запись остановлена", "запись на облако",
        "встреча записывается",
        # Типовые промо-вставки публичных видео.
        "ссылка в профиле", "ссылку вы найдете в профиле", "ссылка в описании",
        "переходите по ссылке", "по поисковому слову", "по поисковым словам",
        "по поисковым слову", "по закрепу", "позакреп", "позакрепу",
        "выложил в канал", "выложил в telegram", "выложил в телеграм",
        "доступен для подписчиков канала", "qr-код на экране", "qr код на экране",
    ]

    # Термины, которые могут быть в initial_prompt для whisper (или были там
    # раньше). Whisper иногда «проговаривает» свой промпт — особенно на
    # тишине. Если в одной короткой строке встречаются 3+ таких термина —
    # это почти наверняка leak промпта, а не реальная речь спикера.
    prompt_leak_terms = {
        "vocmind", "groq", "deepseek", "chatgpt", "openai",
        "api", "kpi", "roi", "backend", "frontend",
        "startup", "deadline", "feedback",
    }

    cleaned_lines = []
    for raw_line in str(text).splitlines():
        line = (raw_line or "").strip()
        if not line:
            continue

        body = re.sub(r"^(ME|THEM):\s*", "", line, flags=re.IGNORECASE).strip()
        t_low = body.lower()

        if any(bp in t_low for bp in bad_phrases) and len(t_low.split()) <= 10:
            continue
        if re.fullmatch(r"[\d\s,.:;!?#%+\-/]+", body or "") and len(body) <= 24:
            continue
        letters = re.findall(r"[A-Za-zА-Яа-яЁё]", body)
        digits = re.findall(r"\d", body)
        if not letters and digits and len(body) <= 24:
            continue
        words = t_low.split()
        if len(words) > 6:
            unique_words = len(set(words))
            if unique_words / len(words) < 0.3:
                continue

        # Защита от whisper-leak initial_prompt: например "Термины, Groq,
        # DeepSeek, ChatGPT, OpenAI, API, KPI, ROI, backend, startup,
        # deadline, feedback" — это явный пересказ списка терминов из
        # подсказки, а не реальная речь.
        # Триггеры:
        #   - 3+ термина из списка В одной строке
        #   - и одно из:
        #       * строка начинается со слова "термины"
        #       * или строка состоит из ≥ 50% этих терминов (мало обычной речи)
        normalized_words = set(re.findall(r"[a-zа-яё]+", t_low))
        leak_matches = normalized_words & prompt_leak_terms
        if len(leak_matches) >= 3:
            starts_with_terminy = re.match(r"^\s*термины\b", t_low) is not None
            total_words_count = len([w for w in re.findall(r"[a-zа-яё]+", t_low) if len(w) >= 2])
            if total_words_count > 0:
                leak_ratio = len(leak_matches) / total_words_count
            else:
                leak_ratio = 0.0
            if starts_with_terminy or leak_ratio >= 0.5:
                continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def _fix_it_terms(text: str) -> str:
    if not text:
        return ""
    replacements = {
        r"\b(?:грок|грог|грук)\b": "Groq",
        r"\b(?:вукмайн|вокмайн|walkmind|voguemind)\b": "VocMind",
        r"\b(?:апи|эпиай|айпиай)\b": "API",
        r"\b(?:дипсик|дип сик|deep seek)\b": "DeepSeek",
        r"\b(?:джипити|чатджипити|чат жпт|чат джпт)\b": "ChatGPT",
        r"\b(?:опен эй ай|опэн эй ай)\b": "OpenAI",
        r"\b(?:промпт|промт|промпты|промты)\b": "prompt",
        r"\b(?:эл эл эм|ллм)\b": "LLM",
    }
    for pattern, correct_word in replacements.items():
        text = re.sub(pattern, correct_word, text, flags=re.IGNORECASE)
    return text


def _norm_line(text: str) -> str:
    return re.sub(r"[^\w\s]", "", (text or "").lower()).replace("ё", "е").strip()


def _is_duplicate_or_similar(new_text: str, last_texts: list) -> bool:
    # Эта дедупликация работает поверх streaming._merge_line_list. Раньше для
    # длинных строк порог был 0.86, что приводило к тихому отбрасыванию НОВЫХ
    # реплик, похожих по словарю на предыдущие (типичная ситуация: «расскажите
    # про...» / «скажите про...»). Поднимаем порог; substring-проверка остаётся
    # как страховка от прямых дублей.
    if not new_text or not last_texts:
        return False
    n_new = _norm_line(new_text)
    if not n_new:
        return False
    for old_t in last_texts[-8:]:
        n_old = _norm_line(old_t)
        if not n_old:
            continue
        if n_new == n_old:
            return True
        # Только полное вложение нормализованных тел длиной >= 5 слов считаем
        # дублем. Это исключает случай, когда «понятно» оказывается подстрокой
        # «понятно отлично спасибо» и тихо съедает новую реплику.
        if len(n_new.split()) >= 5 and len(n_old.split()) >= 5:
            if n_new in n_old or n_old in n_new:
                return True
        ratio = SequenceMatcher(None, n_new, n_old).ratio()
        if len(n_new) <= 20:
            if ratio >= 0.94:
                return True
        else:
            if ratio >= 0.92:
                return True
    return False


def _protocol_has_meaningful_content(state: dict | None) -> bool:
    state = normalize_protocol_state(state)
    if not state or not isinstance(state, dict):
        return False
    if (state.get("summary") or "").strip():
        return True
    # ВАЖНО: key_points обязательно учитывать. Без них на собеседованиях/
    # подкастах (где задач и решений нет) функция всегда возвращала False
    # и финальная регенерация перезаписывала хороший live-state пустотой.
    for key in ("topics", "key_points", "decisions", "ideas", "risks", "next_steps"):
        value = state.get(key)
        if isinstance(value, list) and any(str(x).strip() for x in value):
            return True
    for item in state.get("action_items") or []:
        if isinstance(item, dict) and (item.get("task") or "").strip():
            return True
    if (state.get("notes") or "").strip():
        return True
    return False


def _protocol_richness_score(state: dict | None) -> int:
    """Грубая оценка «насколько содержательный» протокол. Используется чтобы
    выбрать лучший из двух кандидатов (например live vs final-regenerate).

    Чем больше очков — тем больше пользы пользователю. Считаем:
      summary: +3 если есть
      каждый key_point: +2 (тезисы — самое ценное на не-рабочих жанрах)
      каждая action_item: +2
      каждое decision: +2
      каждый next_step: +1
      каждая idea/risk: +1
      каждый topic: +1 (важно меньше чем тезисы)
    """
    state = normalize_protocol_state(state)
    if not state or not isinstance(state, dict):
        return 0
    score = 0
    if (state.get("summary") or "").strip():
        score += 3
    score += 2 * sum(1 for x in (state.get("key_points") or []) if str(x).strip())
    score += 2 * sum(
        1 for it in (state.get("action_items") or [])
        if isinstance(it, dict) and (it.get("task") or "").strip()
    )
    score += 2 * sum(1 for x in (state.get("decisions") or []) if str(x).strip())
    score += 1 * sum(1 for x in (state.get("next_steps") or []) if str(x).strip())
    score += 1 * sum(1 for x in (state.get("ideas") or []) if str(x).strip())
    score += 1 * sum(1 for x in (state.get("risks") or []) if str(x).strip())
    score += 1 * sum(1 for x in (state.get("topics") or []) if str(x).strip())
    return score


def _fallback_protocol_from_transcript(transcript_text: str) -> dict:
    return normalize_protocol_state(protocol_from_transcript(transcript_text), transcript_text)


def _ffmpeg_to_wav(input_path: str, output_path: str) -> None:
    ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError("ffmpeg not found")
    cmd = [
        ffmpeg_path, "-y", "-i", input_path,
        "-ac", str(settings.audio_channels),
        "-ar", str(settings.audio_sample_rate),
        "-f", "wav", output_path,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr}")


def _wav_to_pcm16_bytes(wav_path: str) -> bytes:
    with wave.open(wav_path, "rb") as wf:
        if wf.getnchannels() != 1:
            raise RuntimeError("Only mono wav supported")
        if wf.getsampwidth() != 2:
            raise RuntimeError("Only 16-bit PCM wav supported")
        if wf.getframerate() != settings.audio_sample_rate:
            raise RuntimeError("Unexpected sample rate")
        return wf.readframes(wf.getnframes())


def _render_protocol_text(p: dict | None) -> str:
    return render_protocol_text(normalize_protocol_state(p))


def _apply_plan_gates(raw_transcript: str, protocol_state: dict, features: dict) -> tuple[str, dict | None, str, dict | None]:
    transcript_for_user = raw_transcript if (features.get("speaker_diarization") or {}).get("is_enabled") else strip_speaker_labels(raw_transcript)

    if not (features.get("ai_protocol") or {}).get("is_enabled"):
        return (
            transcript_for_user,
            None,
            "🧾 ПРОТОКОЛ ВСТРЕЧИ\n\nAI-протокол доступен начиная с тарифа «Базовый». Сейчас сохранён только транскрипт.",
            None,
        )

    protocol_clean = normalize_protocol_state(protocol_state, transcript_for_user)
    if not (features.get("tasks_and_decisions") or {}).get("is_enabled"):
        protocol_clean["decisions"] = []
        protocol_clean["action_items"] = []

    protocol_text = _render_protocol_text(protocol_clean)
    analytics_json = None
    if (features.get("meeting_analytics") or {}).get("is_enabled"):
        analytics_json = build_meeting_analytics(raw_transcript, protocol_clean)
    return transcript_for_user, protocol_clean, protocol_text, analytics_json


async def _polish_transcript_ru(transcript_text: str) -> str:
    text = (transcript_text or "").strip()
    if not text:
        return ""
    if len(text) < 20:
        return text

    # Перед LLM-полировкой убираем самоповторы соседних и дальних реплик
    # (типичные ошибки whisper на длинных встречах с перекрывающимися окнами
    # и при двойной обработке mic/tab). См. transcript_utils.clean_transcript.
    text = clean_transcript(text)

    sys_prompt = (
        "Ты редактор русскоязычных транскриптов рабочих встреч.\n"
        "Твоя задача: аккуратно исправить только языковые ошибки в тексте:\n"
        "- падежи\n"
        "- согласование слов\n"
        "- склонения\n"
        "- пунктуацию\n"
        "- явные речевые огрехи ASR\n\n"
        "Строгие правила:\n"
        "1. НЕ меняй смысл.\n"
        "2. НЕ добавляй новую информацию.\n"
        "3. НЕ сокращай текст.\n"
        "4. Сохраняй speaker labels: ME: и THEM:.\n"
        "5. Сохраняй числа, списки, имена, названия продуктов, API, бренды, термины.\n"
        "6. Если фраза звучит странно, исправляй только настолько, насколько это очевидно из контекста.\n"
        "7. Если не уверен — оставь как есть.\n"
        '8. Верни строго JSON вида: {"transcript":"..."}\n'
    )

    async def _polish_one(piece: str) -> str:
        if not piece.strip():
            return piece
        try:
            res = await asyncio.wait_for(
                groq_chat_json(
                    sys_prompt,
                    f"Исправь текст:\n\n{piece}",
                    temperature=0.1,
                    timeout_s=90.0,
                ),
                timeout=95.0,
            )
            fixed = ""
            if isinstance(res, dict):
                fixed = str(res.get("transcript") or "").strip()
            if not fixed:
                return piece
            orig_lines = [x.strip() for x in piece.splitlines() if x.strip()]
            fixed_lines = [x.strip() for x in fixed.splitlines() if x.strip()]
            # Валидация: модель не должна была усечь больше чем на 20% строк
            # и не должна была сократить текст вдвое.
            if len(fixed_lines) < max(1, int(len(orig_lines) * 0.8)):
                return piece
            if len(fixed) < int(len(piece) * 0.6):
                return piece
            return fixed
        except Exception as e:
            log(f"[TRANSCRIPT POLISH ERROR]: {e}")
            return piece

    # Длинный транскрипт делим на куски по строкам с целевым размером ~6000
    # символов. На длинном входе одна Groq-генерация часто упирается в таймаут
    # или возвращает усечённый текст; chunked-polish делает каждый кусок
    # обозримым, и при ошибке/таймауте мы теряем только один кусок, а не весь
    # транскрипт.
    POLISH_CHUNK_CHARS = 6000
    if len(text) <= POLISH_CHUNK_CHARS:
        return await _polish_one(text)

    lines = text.splitlines()
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for line in lines:
        ln = len(line) + 1
        if buf and buf_len + ln > POLISH_CHUNK_CHARS:
            chunks.append("\n".join(buf))
            buf = []
            buf_len = 0
        buf.append(line)
        buf_len += ln
    if buf:
        chunks.append("\n".join(buf))

    polished_chunks = await asyncio.gather(*[_polish_one(c) for c in chunks], return_exceptions=False)
    return "\n".join(c for c in polished_chunks if c).strip()


# ---- Background: triggers & protocol ----

async def _schedule_triggers_update(s) -> None:
    lock: asyncio.Lock = s.__dict__.get("triggers_lock")
    if lock is None or not s.__dict__.get("live_hints_enabled", False):
        return

    async def runner():
        async with lock:
            try:
                text = (s.combined_window() or "").strip()
                if not text:
                    return
                sys_prompt = (
                    'Ты ИИ-ассистент на созвоне. Даны два канала: ME (микрофон) и THEM (звук вкладки). '
                    'Выдели 1-2 главных инсайта (риск, задача, важное обсуждение). '
                    'Верни СТРОГИЙ JSON: {"insights":[{"title":"...","detail":"...","type":"risk","confidence":0.9}]}'
                )
                user_prompt = f"Контекст:\n{text}"
                res = await asyncio.wait_for(
                    groq_chat_json(sys_prompt, user_prompt, temperature=0.2),
                    timeout=float(settings.groq_timeout_seconds) + 5.0,
                )
                if res and "insights" in res:
                    s.insights = res["insights"]
            except Exception as e:
                log(f"[TRIGGERS ERROR]: {e}")

    prev = s.__dict__.get("triggers_task")
    if prev and hasattr(prev, "done") and not prev.done():
        return
    s.__dict__["triggers_task"] = asyncio.create_task(runner())


async def _schedule_protocol_regenerate(s, *, timeout_s: float) -> None:
    """Live-обновление протокола: регенерация С НУЛЯ из всего накопленного транскрипта.

    Заменяет старую _schedule_protocol_update, которая инкрементально мутировала
    стейт через update_protocol_state_via_groq. Та архитектура копила ошибки:
    если LLM ошибалась на первых 90 сек (например, тащила в action_items
    обрывки реплик с собеседования), эта ошибка оставалась в стейте навсегда,
    а каждые следующие 90 сек к ней добавлялись новые. И финальный finalize
    уже не мог это починить.

    Новая логика: каждый раз берём ВЕСЬ накопленный транскрипт и делаем свежую
    генерацию. Никакой зависимости от предыдущего стейта. Llama сама определяет
    жанр (рабочая встреча / собеседование / подкаст / лекция) и адаптирует
    содержимое. На длинных транскриптах автоматически уходит в chunked-режим
    с голосованием по жанру.

    Защита от перегруза: если регенерация ещё в процессе — новый запуск
    пропускается (как и раньше для protocol_task).
    """
    lock: asyncio.Lock = s.__dict__.get("protocol_lock")
    if lock is None or not s.__dict__.get("protocol_enabled", False):
        return

    async def runner():
        async with lock:
            # Берём весь накопленный транскрипт. Если ещё пусто — ничего не делаем.
            full_text = (s.combined_full_transcript() or "").strip()
            if not full_text:
                return
            # Чистим самоповторы (соседние и через всю встречу) ДО отправки в
            # LLM. На live-регенерации это особенно важно: на длинных встречах
            # whisper копит дубли, и без чистки LLM видит "Я думаю..." дважды
            # и может посчитать это разными мыслями.
            full_text = clean_transcript(full_text)

            # Помечаем «регенерация в процессе» — на случай если придёт ещё
            # один _schedule_protocol_regenerate, чтобы он не дёргал параллельно.
            s.__dict__["protocol_regenerating"] = True
            try:
                t0 = time.time()
                new_state = await asyncio.wait_for(
                    regenerate_protocol_via_groq(
                        full_text,
                        model=settings.groq_model,
                        timeout_s=float(timeout_s),
                    ),
                    timeout=float(timeout_s) + 30.0,
                )
                if new_state:
                    s.protocol = new_state
                    elapsed = time.time() - t0
                    genre = new_state.get("genre", "?")
                    n_actions = len(new_state.get("action_items") or [])
                    n_keypoints = len(new_state.get("key_points") or [])
                    has_summary = bool(new_state.get("summary"))
                    log(
                        f"[PROTOCOL REGENERATE OK] elapsed={elapsed:.1f}s "
                        f"genre={genre} actions={n_actions} key_points={n_keypoints} "
                        f"summary={'yes' if has_summary else 'NO'} "
                        f"transcript_len={len(full_text)}"
                    )
            except Exception as e:
                log(f"[PROTOCOL REGENERATE ERROR]: {e}")
            finally:
                s.__dict__["protocol_regenerating"] = False
                # pending_parts больше не используется в новой архитектуре,
                # но оставим чистым на случай старого кода.
                s.__dict__["pending_parts"] = []

    prev = s.__dict__.get("protocol_task")
    if prev and hasattr(prev, "done") and not prev.done():
        return
    s.__dict__["protocol_task"] = asyncio.create_task(runner())


async def _schedule_protocol_update(s, *, timeout_s: float) -> None:
    lock: asyncio.Lock = s.__dict__.get("protocol_lock")
    if lock is None or not s.__dict__.get("protocol_enabled", False):
        return

    async def runner():
        async with lock:
            if s.__dict__.get("protocol_inflight_text"):
                return
            pending_list = list(s.__dict__.get("pending_parts") or [])
            batch_text = "\n".join(pending_list).strip()
            if not batch_text:
                return
            s.__dict__["protocol_inflight_text"] = batch_text
            s.__dict__["pending_parts"] = []
            try:
                # Используем единую точку входа из protocol.py — там корректный
                # build_state_update_prompt со схемой и нашими правилами про жанр
                # и шум, и результат прогоняется через normalize_protocol_state.
                state = s.protocol or _new_empty_protocol_state()
                new_state = await asyncio.wait_for(
                    update_protocol_state_via_groq(
                        state,
                        batch_text,
                        model=settings.groq_model,
                        timeout_s=float(timeout_s),
                    ),
                    timeout=float(timeout_s) + 5.0,
                )
                if new_state:
                    s.protocol = new_state
                s.__dict__["protocol_inflight_text"] = ""
            except Exception as e:
                log(f"[PROTOCOL UPDATE ERROR]: {e}")
                inflight = (s.__dict__.get("protocol_inflight_text") or "").strip()
                s.__dict__["protocol_inflight_text"] = ""
                if inflight:
                    cur = list(s.__dict__.get("pending_parts") or [])
                    s.__dict__["pending_parts"] = [inflight] + cur

    prev = s.__dict__.get("protocol_task")
    if prev and hasattr(prev, "done") and not prev.done():
        return
    s.__dict__["protocol_task"] = asyncio.create_task(runner())


# ---- STREAM ----

@app.post("/stream/start")
async def stream_start(
    device_token: str | None = Form(None),
    capture_mode: str | None = Form(None),
    title: str | None = Form(None),
):
    registry.cleanup()
    sid = str(os.urandom(16).hex())
    s = registry.create(sid)

    s.protocol = _new_empty_protocol_state()
    s.insights = []
    s.trigger_state = {}
    s.last_trigger_fired_ts = {}
    s.last_ts = time.time()

    s.__dict__["pending_parts"] = []
    s.__dict__["protocol_inflight_text"] = ""
    s.__dict__["last_sent_texts"] = []
    s.__dict__["chunks"] = 0
    s.__dict__["protocol_lock"] = asyncio.Lock()
    s.__dict__["protocol_task"] = None
    s.__dict__["triggers_lock"] = asyncio.Lock()
    s.__dict__["triggers_task"] = None
    s.__dict__["last_protocol_update_ts"] = 0.0
    s.__dict__["recording_started_real_ts"] = time.time()
    s.__dict__["capture_mode"] = capture_mode or "mic"
    s.__dict__["meeting_title"] = title or None
    s.__dict__["device_token"] = device_token or ""
    s.__dict__["protocol_enabled"] = False
    s.__dict__["live_hints_enabled"] = False
    s.__dict__["plan_features"] = {}
    s.__dict__["remaining_seconds_limit"] = None
    s.__dict__["meeting_id"] = None
    s.__dict__["user_id"] = None
    s.__dict__["plan"] = None

    log(f"[START] session={sid} capture_mode={capture_mode or 'mic'} title={title!r}")

    if device_token:
        db: Session = SessionLocal()
        try:
            device = db.query(ExtensionDevice).filter(
                ExtensionDevice.device_token == device_token,
                ExtensionDevice.is_active == True
            ).first()

            if not device:
                raise HTTPException(status_code=401, detail="Устройство не найдено")

            allowed = ensure_recording_allowed(db, device.user_id)
            if not allowed.get("ok"):
                raise HTTPException(status_code=403, detail=allowed.get("detail") or "Запись недоступна")

            plan = allowed["plan"]
            features = allowed["features"]
            usage = allowed["usage"]

            now = datetime.datetime.utcnow()
            meeting = Meeting(
                user_id=device.user_id,
                extension_device_id=device.id,
                title=title or f"Встреча {now.strftime('%d.%m.%Y %H:%M')}",
                source_type="extension",
                capture_mode=capture_mode or "mic",
                status=MeetingStatus.recording,
                started_at=now,
                language_code=settings.asr_language,
            )
            db.add(meeting)
            db.commit()
            db.refresh(meeting)

            s.__dict__["meeting_id"] = str(meeting.id)
            s.__dict__["user_id"] = str(device.user_id)
            s.__dict__["plan"] = {
                "code": plan.code,
                "title": plan.title,
                "description": plan.description,
            }
            s.__dict__["plan_features"] = features
            s.__dict__["protocol_enabled"] = bool((features.get("ai_protocol") or {}).get("is_enabled"))
            s.__dict__["live_hints_enabled"] = bool((features.get("live_hints") or {}).get("is_enabled"))

            if usage.get("remaining_minutes") is not None:
                s.__dict__["remaining_seconds_limit"] = int(usage["remaining_minutes"] * 60)

            log(
                f"[START] meeting_id={meeting.id} user_id={device.user_id} "
                f"protocol_enabled={s.__dict__['protocol_enabled']} "
                f"live_hints_enabled={s.__dict__['live_hints_enabled']}"
            )
        finally:
            db.close()

    return {
        "session_id": sid,
        "meeting_id": s.__dict__.get("meeting_id"),
        "user_id": s.__dict__.get("user_id"),
        "plan": s.__dict__.get("plan"),
    }


@app.post("/stream/chunk")
async def stream_chunk(
    session_id: str = Form(...),
    source: str = Form("mic"),
    file: UploadFile = File(...),
):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Unknown session_id")

    source = "mic" if (source or "").lower() == "mic" else "tab"
    s.__dict__["chunks"] = int(s.__dict__.get("chunks", 0)) + 1
    chunk_index = s.__dict__["chunks"]
    features = s.__dict__.get("plan_features") or {}
    speaker_enabled = bool((features.get("speaker_diarization") or {}).get("is_enabled")) or not features

    log(
        f"[CHUNK] session={session_id} idx={chunk_index} source={source} "
        f"filename={getattr(file, 'filename', None)!r} "
        f"content_type={getattr(file, 'content_type', None)!r}"
    )

    try:
        data = await file.read()
        if not data:
            log(f"[CHUNK] empty data session={session_id} idx={chunk_index}")
            raise HTTPException(status_code=400, detail="Empty chunk")

        log(f"[CHUNK] raw_bytes={len(data)} session={session_id} idx={chunk_index}")

        ct = (file.content_type or "").lower()
        name = (file.filename or "").lower()

        if ("pcm" in ct) or name.endswith(".pcm") or name.endswith(".raw"):
            pcm16 = pcm16_bytes_to_np(data)
            log(f"[CHUNK] interpreted as PCM16 samples={len(pcm16)}")

        elif ("wav" in ct) or name.endswith(".wav"):
            with wave.open(io.BytesIO(data), "rb") as wf:
                frames = wf.getnframes()
                fr = wf.getframerate()
                ch = wf.getnchannels()
                sw = wf.getsampwidth()
                log(f"[CHUNK] wav meta frames={frames} rate={fr} channels={ch} sampwidth={sw}")
                pcm16 = pcm16_bytes_to_np(wf.readframes(frames))
            log(f"[CHUNK] interpreted as WAV samples={len(pcm16)}")

        else:
            suffix = Path(file.filename or "chunk.webm").suffix or ".webm"
            tmp_in, tmp_wav = None, None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(data)
                    tmp_in = tmp.name

                tmp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
                log(f"[CHUNK] ffmpeg convert {tmp_in} -> {tmp_wav}")

                await asyncio.to_thread(_ffmpeg_to_wav, tmp_in, tmp_wav)
                pcm_bytes = await asyncio.to_thread(_wav_to_pcm16_bytes, tmp_wav)
                pcm16 = pcm16_bytes_to_np(pcm_bytes)

                log(f"[CHUNK] ffmpeg converted samples={len(pcm16)}")
            finally:
                for pth in [tmp_in, tmp_wav]:
                    if pth:
                        try:
                            Path(pth).unlink(missing_ok=True)
                        except Exception:
                            pass

        if len(pcm16) == 0:
            log(f"[CHUNK] pcm16 empty after decode session={session_id} idx={chunk_index}")

        transcribe_lock = s.__dict__.setdefault("transcribe_lock", asyncio.Lock())

        async with gpu_lock:
            async with transcribe_lock:
                s.append_audio(source, pcm16)
                delta_text, _window_text_single = await asyncio.to_thread(s.transcribe_window, source)

        s.last_ts = time.time()
        # Метим timestamp ПЕРВОГО реально пришедшего аудиочанка. Это нужно для
        # корректного подсчёта длительности встречи: между /stream/start и
        # первым chunk может пройти секунда-другая (инициализация mic в
        # расширении, разрешения), а в долгих случаях — ещё больше. Если
        # пользователь нажал Start, отвлёкся, и реальная запись пошла с
        # задержкой — без этого мы насчитаем ему лишнее время в duration.
        if "first_chunk_ts" not in s.__dict__:
            s.__dict__["first_chunk_ts"] = s.last_ts
        s.__dict__["last_chunk_ts"] = s.last_ts
        window_text = s.combined_window()

        log(f"[CHUNK] delta_text raw={str(delta_text)[:200]!r}")
        log(f"[CHUNK] window_text raw={str(window_text)[:200]!r}")

        if delta_text:
            cleaned_text = _clean_hallucinations(delta_text)
            log(f"[CHUNK] cleaned_text={cleaned_text[:200]!r}")

            if cleaned_text:
                cleaned_text = _fix_it_terms(cleaned_text)
                last_texts = s.__dict__.setdefault("last_sent_texts", [])

                if not _is_duplicate_or_similar(cleaned_text, last_texts):
                    s.__dict__.setdefault("pending_parts", []).append(cleaned_text)
                    last_texts.append(cleaned_text)
                    delta_text = cleaned_text
                    log(f"[CHUNK] accepted_text={delta_text[:200]!r}")
                else:
                    log(f"[CHUNK] dropped duplicate/similar={cleaned_text[:200]!r}")
                    delta_text = ""
            else:
                log("[CHUNK] cleaned_text empty after hallucination filter")
                delta_text = ""

        if ENABLE_LIVE_TRIGGERS and s.__dict__.get("live_hints_enabled") and chunk_index % TRIGGERS_UPDATE_EVERY_CHUNKS == 0:
            await _schedule_triggers_update(s)

        now_ts = time.time()
        last_upd = float(s.__dict__.get("last_protocol_update_ts") or 0.0)
        should_update_by_chunks = (chunk_index % PROTOCOL_UPDATE_EVERY_CHUNKS == 0)
        should_update_by_time = ((now_ts - last_upd) >= PROTOCOL_UPDATE_EVERY_SECONDS)

        if ENABLE_LIVE_PROTOCOL and s.__dict__.get("protocol_enabled") and (should_update_by_chunks or should_update_by_time):
            # Регенерация триггерится только если в накопленном транскрипте
            # реально что-то есть. Раньше триггером был pending_parts (входящие
            # реплики, ещё не отправленные в LLM), но в новой архитектуре
            # regenerate работает по полному транскрипту, а не по дельте.
            full_so_far = (s.combined_full_transcript() or "").strip()
            if len(full_so_far) >= 80:
                s.__dict__["last_protocol_update_ts"] = now_ts
                await _schedule_protocol_regenerate(s, timeout_s=120.0)

        display_protocol_state = normalize_protocol_state(
            s.protocol if s.__dict__.get("protocol_enabled") else _new_empty_protocol_state(),
            s.combined_full_transcript() or window_text,
        )

        state_payload = _compose_state(
            display_protocol_state if s.__dict__.get("protocol_enabled") else _new_empty_protocol_state(),
            s.insights if s.__dict__.get("live_hints_enabled") else [],
            triggers=s.trigger_state if s.__dict__.get("live_hints_enabled") else {},
        )

        visible_delta = delta_text if speaker_enabled else strip_speaker_labels(delta_text)
        visible_window = window_text if speaker_enabled else strip_speaker_labels(window_text)

        should_stop = False
        stop_reason = None
        limit_seconds = s.__dict__.get("remaining_seconds_limit")

        if limit_seconds is not None:
            elapsed = int(time.time() - float(s.__dict__.get("recording_started_real_ts") or time.time()))
            if elapsed >= int(limit_seconds):
                should_stop = True
                stop_reason = "Минуты по тарифу закончились, запись остановлена автоматически"

        log(
            f"[CHUNK] response idx={chunk_index} visible_delta={visible_delta[:160]!r} "
            f"window_len={len(visible_window or '')} should_stop={should_stop}"
        )

        return {
            "session_id": session_id,
            "chunk_index": chunk_index,
            "partial_transcript": visible_delta,
            "window_transcript": visible_window,
            "state": state_payload,
            "should_stop": should_stop,
            "stop_reason": stop_reason,
            "error": None,
        }

    except Exception as e:
        log(f"[CHUNK ERROR] session={session_id} idx={chunk_index} error={e}")
        return {
            "session_id": session_id,
            "partial_transcript": "",
            "state": _compose_state(_new_empty_protocol_state(), [], triggers={}),
            "should_stop": False,
            "stop_reason": None,
            "error": str(e),
        }


@app.post("/stream/finish")
async def stream_finish(session_id: str = Form(...)):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Unknown session_id")

    log(f"[FINISH] session={session_id} begin")
    log(
        f"[FINISH] flags live_protocol={ENABLE_LIVE_PROTOCOL} "
        f"polish={ENABLE_TRANSCRIPT_POLISH} retranscribe={ENABLE_FINAL_RETRANSCRIBE}"
    )

    protocol_state = s.protocol or _new_empty_protocol_state()

    # Если в фоне всё ещё крутится регенерация — даём ей короткое окно
    # завершиться, чтобы не выкинуть только что сгенерированный стейт.
    if s.__dict__.get("protocol_enabled"):
        t_pr = s.__dict__.get("protocol_task")
        if t_pr and hasattr(t_pr, "done") and not t_pr.done():
            try:
                await asyncio.wait_for(t_pr, timeout=PROTOCOL_BG_JOIN_TIMEOUT_S)
            except Exception:
                pass

    try:
        transcribe_lock = s.__dict__.setdefault("transcribe_lock", asyncio.Lock())
        async with gpu_lock:
            async with transcribe_lock:
                for src in ("mic", "tab"):
                    try:
                        await asyncio.to_thread(s.transcribe_window, src)
                    except Exception:
                        pass
    except Exception as e:
        log(f"[FINAL FLUSH ERROR]: {e}")

    # Получение финального транскрипта.
    # Раньше тут безусловно делался combined_full_retranscribed — повторная
    # пере-транскрипция всех PCM-буферов через whisper. На длинных встречах
    # это занимало 30-90 секунд и было главным источником медленного финиша.
    # Теперь:
    # - по умолчанию (ENABLE_FINAL_RETRANSCRIBE=False) берём готовый транскрипт,
    #   который уже сложился во время streaming-обработки чанков. Это мгновенно.
    # - если хочется максимального качества — выставляешь в .env флаг
    #   ENABLE_FINAL_RETRANSCRIBE=true, и оно пойдёт по старому пути.
    # - в любом случае, если базовый транскрипт пустой (ничего не накопилось),
    #   делаем fallback на retranscribe — лучше медленно чем никак.
    base_transcript = (s.combined_full_transcript() or "").strip()
    if ENABLE_FINAL_RETRANSCRIBE or not base_transcript:
        try:
            t0 = time.time()
            transcribe_lock = s.__dict__.setdefault("transcribe_lock", asyncio.Lock())
            async with gpu_lock:
                async with transcribe_lock:
                    transcript_text = await asyncio.to_thread(s.combined_full_retranscribed)
            log(f"[FINISH] retranscribe done in {time.time()-t0:.1f}s")
        except Exception as e:
            log(f"[FINAL RETRANSCRIBE ERROR]: {e}")
            transcript_text = base_transcript
    else:
        transcript_text = base_transcript
        log(f"[FINISH] using accumulated transcript (skipped retranscribe), len={len(transcript_text)}")

    window_text = (s.combined_window() or "").strip()

    # LLM-полировка транскрипта. Опционально через флаг — если квота Groq
    # выбита или хочется минимального финиша, ставим
    # ENABLE_TRANSCRIPT_POLISH=false в .env. Без polish транскрипт всё равно
    # читаемый, просто без идеальной пунктуации.
    polished_transcript_text = transcript_text
    if transcript_text and ENABLE_TRANSCRIPT_POLISH:
        try:
            t0 = time.time()
            polished_transcript_text = await _polish_transcript_ru(transcript_text)
            log(f"[FINISH] polish done in {time.time()-t0:.1f}s")
        except Exception as e:
            log(f"[TRANSCRIPT POLISH ERROR]: {e}")
            polished_transcript_text = transcript_text

    # КРИТИЧНО: после polish обязательно прогоняем clean_transcript ещё раз.
    # Polish работает по чанкам, в нём может проскочить глобальный дубль
    # (когда whisper в начале и в конце записи дал один и тот же кусок). Эта
    # чистка — единственный шанс убрать такие повторы перед сохранением.
    if polished_transcript_text:
        polished_transcript_text = clean_transcript(polished_transcript_text)

    log(f"[FINISH] transcript_len={len(polished_transcript_text)} window_len={len(window_text)}")
    log(f"[FINISH] transcript_preview={polished_transcript_text[:300]!r}")

    # ВАЖНО: финальная генерация ВСЕГДА идёт через regenerate-from-scratch
    # из причёсанного транскрипта. Раньше тут было сложное ветвление
    # (update_state -> rebuild -> finalize), которое было нужно из-за
    # инкрементальной архитектуры. Теперь — один чистый проход.
    #
    # ВАЖНО ПРО protocol_enabled: даже если фича отключена в тарифе, если
    # транскрипт есть, мы всё равно пытаемся сгенерировать протокол. Иначе
    # пользователь получит фейковую сводку из эвристики (
    # "Обсудили рабочие задачи и ближайшие шаги..."), что хуже, чем пустой
    # протокол. Если потом тариф запретит показ — gate сработает на уровне
    # _apply_plan_gates.
    should_generate_protocol = bool(polished_transcript_text)
    log(
        f"[FINISH] protocol_check enabled={s.__dict__.get('protocol_enabled')} "
        f"should_generate={should_generate_protocol} "
        f"existing_protocol_has_content={_protocol_has_meaningful_content(protocol_state)}"
    )
    if should_generate_protocol:
        # Сохраняем кандидат от live-регенерации, чтобы было с чем сравнить
        # после финальной регенерации. Если финальная вернёт пустоту (например,
        # из-за rate limit на Groq), мы откатимся к live-state, а не выкинем
        # пользователю «(Пока нет данных)».
        live_state_snapshot = dict(protocol_state) if isinstance(protocol_state, dict) else None
        live_score = _protocol_richness_score(live_state_snapshot)
        try:
            t0 = time.time()
            final_state = await asyncio.wait_for(
                regenerate_protocol_via_groq(
                    polished_transcript_text,
                    model=settings.groq_model,
                    timeout_s=240.0,
                ),
                timeout=260.0,
            )
            if final_state:
                final_score = _protocol_richness_score(final_state)
                elapsed = time.time() - t0
                genre = final_state.get("genre", "?")
                n_actions = len(final_state.get("action_items") or [])
                n_keypoints = len(final_state.get("key_points") or [])
                has_summary = bool(final_state.get("summary"))
                log(
                    f"[PROTOCOL FINAL REGENERATE OK] elapsed={elapsed:.1f}s "
                    f"genre={genre} actions={n_actions} key_points={n_keypoints} "
                    f"summary={'yes' if has_summary else 'NO'} "
                    f"transcript_len={len(polished_transcript_text)} "
                    f"final_score={final_score} live_score={live_score}"
                )
                # Берём более содержательный результат. Если финал хуже live —
                # значит на финальной регенерации Groq вернул пустоту (rate
                # limit, таймаут на ретраях, кривой JSON и т.п.), и нам лучше
                # оставить то что уже посчитала live-регенерация в течение
                # встречи, чем переписать его пустым набором.
                if final_score >= live_score:
                    protocol_state = final_state
                else:
                    log(
                        f"[PROTOCOL FINAL REGENERATE] keeping live snapshot "
                        f"(live_score={live_score} > final_score={final_score})"
                    )
                    protocol_state = live_state_snapshot or final_state
        except Exception as e:
            log(f"[PROTOCOL FINAL REGENERATE ERROR]: {e}")
            # Если регенерация упала — оставляем то что есть от live-регенерации.
            # Эвристический fallback НЕ используем, чтобы не получить мусорное
            # "Обсудили рабочие задачи и ближайшие шаги..." на собеседовании.
            # Live-снэпшот уже в protocol_state, ничего делать не нужно.

    protocol_state = normalize_protocol_state(protocol_state, polished_transcript_text)
    features = s.__dict__.get("plan_features") or {}

    transcript_for_user, protocol_json, protocol_text, analytics_json = _apply_plan_gates(
        polished_transcript_text,
        protocol_state,
        features,
    )

    final_proto = _compose_state(
        protocol_json or _new_empty_protocol_state(),
        s.insights if s.__dict__.get("live_hints_enabled") else [],
        triggers=s.trigger_state if s.__dict__.get("live_hints_enabled") else {},
    )

    meeting_id = s.__dict__.get("meeting_id")
    if meeting_id:
        db = SessionLocal()
        try:
            row = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            if row:
                now = datetime.datetime.utcnow()
                row.finished_at = now
                row.status = MeetingStatus.done

                # Длительность считаем по реальному окну записи: от первого
                # пришедшего аудиочанка до последнего. Это намного точнее, чем
                # finished - started, потому что между /stream/start и первым
                # chunk может пройти время на инициализацию mic, а в проблемных
                # случаях (расширение долго не закрылось / повисло) этот
                # промежуток мог измеряться минутами и завышал длительность.
                first_chunk = s.__dict__.get("first_chunk_ts")
                last_chunk = s.__dict__.get("last_chunk_ts")
                if first_chunk and last_chunk and last_chunk >= first_chunk:
                    real_duration = max(1, int(last_chunk - first_chunk))
                    row.duration_seconds = real_duration
                    log(f"[FINISH] duration from chunks: {real_duration}s")
                elif row.started_at:
                    # Fallback: если по какой-то причине chunks не пришли (ошибка
                    # на стороне расширения), используем старый расчёт.
                    row.duration_seconds = max(1, int((now - row.started_at).total_seconds()))
                    log(f"[FINISH] duration from started_at fallback: {row.duration_seconds}s")
                else:
                    row.duration_seconds = max(
                        1,
                        int(time.time() - float(s.__dict__.get("recording_started_real_ts") or time.time()))
                    )
                    log(f"[FINISH] duration from recording_started_real_ts fallback: {row.duration_seconds}s")

                row.capture_mode = s.__dict__.get("capture_mode") or row.capture_mode
                row.transcript_text = transcript_for_user
                row.protocol_text = protocol_text
                row.protocol_json = protocol_json
                row.analytics_json = analytics_json
                row.live_hints_json = {"insights": s.insights or []} if s.__dict__.get("live_hints_enabled") else None
                row.searchable_text = "\n".join([
                    row.title or "",
                    transcript_for_user or "",
                    protocol_text or "",
                    " ".join(searchable_protocol_strings(protocol_json)),
                ]).strip()

                db.commit()
        finally:
            db.close()

    registry.pop(session_id)

    log(
        f"[FINISH] done session={session_id} meeting_id={meeting_id} "
        f"transcript_len={len(transcript_for_user or '')} "
        f"protocol_len={len(protocol_text or '')}"
    )

    return {
        "session_id": session_id,
        "meeting_id": meeting_id,
        "transcript": transcript_for_user,
        "window_transcript": (
            window_text
            if (features.get("speaker_diarization") or {}).get("is_enabled") or not features
            else strip_speaker_labels(window_text)
        ),
        "protocol": final_proto,
        "protocol_text": protocol_text,
        "analytics": analytics_json,
        "protocol_error": None,
    }