import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List

from ..config import settings
from .groq import groq_chat_json

NOISE_PATTERNS = [
    r"\b(?:раз\s*,?\s*два\s*,?\s*три|test|тест|проверка звука|как меня слышно|слышно ли|hello[,! ]*vocmind|vocmind[,! ]*как меня слышно)\b",
    r"\b(?:подписывайтесь на наш канал|подписывайтесь|всем пока|всем хорошей недели|продуктивной недели|спасибо за просмотр)\b",
    # Системные сообщения видеоконференций (Zoom/Meet/Telemost).
    r"\b(?:recording in progress|recording stopped|recording started|this meeting is being recorded|запись начата|запись остановлена|запись на облако|встреча записывается)\b",
    # Типовые промо-вставки ведущих публичных видео (YouTube/подкасты).
    r"\b(?:ссылк[аиу]\s+(?:в|вы найд[её]те в)\s+профиле|ссылк[аиу]\s+в\s+описании|переходи(?:те)?\s+по\s+ссылке|по\s+поисков\w+\s+слов\w+|выложил\s+(?:в|на)\s+(?:закреп(?:е|у|\W)?|(?:(?:телеграм|telegram)[\s\-]*)?канал|телеграм|telegram)|по\s+закреп[уле]|позакреп[уе]?|доступен\s+для\s+подписчиков\s+канала|qr[\s\-]*код[ау]?\s+на\s+экране)\b",
    r"^[а-яa-zё]{1,3}\.{2,}$",
]
IDEA_MARKERS = ["идея", "предлагаю", "можно", "давайте", "вариант", "гипотез", "попробовать", "стоит попробовать"]
DECISION_MARKERS = ["решили", "договорились", "согласовали", "согласовано", "принято решение", "утвердили", "будем делать"]
RISK_MARKERS = ["риск", "риски", "проблем", "блокер", "мешает", "непонятно", "неясно", "может сорваться", "может не получиться", "ограничение"]
NEXT_STEP_MARKERS = ["после чего", "далее", "затем", "потом", "next step", "and after that", "after that"]
TASK_MARKERS = [
    "нужно", "надо", "необходимо", "требуется", "следует", "задача", "сделать", "дописать", "написать", "начать",
    "подготовить", "проверить", "доработать", "исправить", "привести", "закончить", "доделать", "переделать",
    "обновить", "добавить", "убрать", "переписать", "оформить", "запустить", "собрать",
]
TASK_VERBS = [
    "дописать", "написать", "начать", "сделать", "подготовить", "проверить", "доработать", "исправить", "привести",
    "закончить", "доделать", "переделать", "обновить", "добавить", "убрать", "переписать", "оформить", "запустить", "собрать",
]
COMPOUND_TASK_RE = re.compile(
    r",\s*(?=(?:сделать|написать|начать|подготовить|проверить|доработать|исправить|привести|закончить|доделать|переделать|обновить|добавить|убрать|переписать|оформить|запустить|собрать)\b)",
    flags=re.I,
)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts = []
        for key in ("task", "text", "title", "detail", "name", "value"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        return " — ".join(parts[:2]).strip()
    return str(value).strip()


def _norm_text(text: str) -> str:
    t = _coerce_text(text).lower().replace("ё", "е")
    t = re.sub(r"^[=:\-\s]+|[=:\-\s]+$", "", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _has_weird_script_mix(text: str) -> bool:
    t = text or ""
    has_cyr = bool(re.search(r"[А-Яа-яЁё]", t))
    has_lat = bool(re.search(r"[A-Za-z]", t))
    return _contains_cjk(t) or (has_cyr and has_lat and "after that" in t.lower() and len(t.split()) <= 10)


def _is_noise_line(text: str) -> bool:
    t = _coerce_text(text)
    if not t:
        return True
    low = t.lower().strip()
    if _has_weird_script_mix(t):
        return True
    if re.fullmatch(r"[\d\s,.:;!?#%+\-/]+", t):
        return True
    if re.fullmatch(r"(.)\1{5,}", low):
        return True
    for pat in NOISE_PATTERNS:
        if re.search(pat, low):
            return True
    words = low.split()
    if len(words) >= 5 and len(set(words)) <= max(1, len(words) // 4):
        return True
    return False


def _sentence_cleanup(text: str) -> str:
    t = _coerce_text(text)
    if not t:
        return ""
    t = re.sub(r"^(?:ME|THEM|SPEAKER)\s*:\s*", "", t, flags=re.I)
    t = re.sub(r"^===.*?===\s*", "", t)
    t = t.replace("—", "-").replace("–", "-")
    t = re.sub(r"^(?:ну и|ну|так|точнее)\s+", "", t, flags=re.I)
    t = re.sub(r"\bантипугиатом\b", "антиплагиатом", t, flags=re.I)
    t = re.sub(r"\bне париться антиплагиатом\b", "привести текст в вид, чтобы антиплагиат не срабатывал", t, flags=re.I)
    t = re.sub(r"\bпроизводим все необходимые диаграммы\b", "сделать все необходимые диаграммы", t, flags=re.I)
    t = re.sub(r"\bзаписать приложение, чтобы оно работало корректно\b", "дописать приложение, чтобы оно работало корректно", t, flags=re.I)
    t = re.sub(r"(?i)(дописать приложение[^,]*),\s*после\s+\1,\s*после\s+чего", r"\1, после чего", t)
    t = re.sub(r"(?i)(начать писать вторую главу[^,]*),\s*после\s+\1", r"\1", t)
    t = re.sub(r"\bstart writing the third chapter\b", "начать писать третью главу", t, flags=re.I)
    t = re.sub(r"\bstart writing the second chapter\b", "начать писать вторую главу", t, flags=re.I)
    t = re.sub(r"\bwrite the third chapter\b", "написать третью главу", t, flags=re.I)
    t = re.sub(r"\bwrite the second chapter\b", "написать вторую главу", t, flags=re.I)
    t = re.sub(r"\bapp\b", "приложение", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" .,-")
    if t:
        t = t[0].upper() + t[1:]
    return t


def _split_sentences(text: str) -> List[str]:
    src = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    units: List[str] = []
    buf = ""
    for line in src.split("\n"):
        line = line.strip()
        if not line or line.startswith("==="):
            continue
        line = re.sub(r"^(?:ME|THEM|SPEAKER)\s*:\s*", "", line, flags=re.I).strip()
        if not line:
            continue
        buf = (buf + " " + line).strip() if buf else line
        if re.search(r"[.!?…]$", line):
            units.append(buf)
            buf = ""
    if buf:
        units.append(buf)

    out: List[str] = []
    for unit in units:
        for part in re.split(r"(?<=[.!?])\s+", unit):
            cleaned = _sentence_cleanup(part)
            if cleaned and not _is_noise_line(cleaned):
                out.append(cleaned)
    return out


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm_text(a), _norm_text(b)).ratio()


def _dedupe_texts(items: Iterable[str], *, strong: bool = False) -> List[str]:
    out: List[str] = []
    for item in items:
        t = _sentence_cleanup(item)
        if not t or _is_noise_line(t):
            continue
        n = _norm_text(t)
        if not n:
            continue
        duplicate = False
        for prev in out[-12:]:
            pn = _norm_text(prev)
            if not pn:
                continue
            ratio = _sim(t, prev)
            if n == pn or n in pn or pn in n or ratio >= (0.84 if strong else 0.90):
                duplicate = True
                break
        if not duplicate:
            out.append(t)
    return out


def _extract_task_text(text: str) -> str:
    t = _sentence_cleanup(text)
    if not t:
        return ""
    low = t.lower()
    for marker in ["после чего", "далее", "затем", "потом", "and after that", "after that", "итак", "задача на неделю", "задачи на неделю", "обсудим задачи на следующей неделе"]:
        if low.startswith(marker):
            t = _sentence_cleanup(t[len(marker):])
            low = t.lower()
    for marker in ["необходимо", "нужно", "надо", "следует", "требуется"]:
        if low.startswith(marker + " "):
            t = _sentence_cleanup(t[len(marker):])
            low = t.lower()
    for verb in TASK_VERBS:
        m = re.search(rf"\b{verb}\b.+", low)
        if m:
            t = _sentence_cleanup(t[m.start():])
            break
    t = re.sub(r"\bв вид,?\s+чтобы\b", "в вид, чтобы", t, flags=re.I)
    t = re.sub(r"^Начать\s+(вторую|третью)\s+главу\s+писать$", r"Начать писать \1 главу", t, flags=re.I)
    t = re.sub(r"^Начать\s+(вторую|третью)\s+главу\s+писать", r"Начать писать \1 главу", t, flags=re.I)
    t = re.sub(r"\bего не видел\b", "не срабатывал", t, flags=re.I)
    t = re.sub(r"(?i)(дописать приложение[^,]*),?\s*после\s+дописать приложение[^,]*", r"\1", t)
    t = re.sub(r"(?i)^(.+?),\s*после\s+\1,", r"\1,", t)
    if re.search(r"(?i)^дописать приложение.*?,\s*после\s+дописать приложение\b", t):
        t = re.split(r"(?i),\s*после\s+дописать приложение\b", t, maxsplit=1)[0]
    t = re.sub(r"\bне парился антиплагиатом\b", "антиплагиат не срабатывал", t, flags=re.I)
    t = re.sub(r",?\s*после$", "", t, flags=re.I)
    return t.strip(" .")


def _split_compound_task(text: str) -> List[str]:
    task = _extract_task_text(text)
    if not task:
        return []
    parts = COMPOUND_TASK_RE.split(task)
    return [_sentence_cleanup(part) for part in parts if _sentence_cleanup(part)]


def _build_summary(tasks: List[str], decisions: List[str], next_steps: List[str]) -> str | None:
    core = _dedupe_texts(decisions[:1] + tasks[:2] + next_steps[:1], strong=True)
    if not core:
        return None
    intro = "Обсудили рабочие задачи и ближайшие шаги."
    tail = "; ".join(x[0].lower() + x[1:] if x else x for x in core[:3])
    return f"{intro} Зафиксировали, что нужно {tail}." if tail else intro


def protocol_from_transcript(transcript_text: str) -> Dict[str, Any]:
    sentences = _split_sentences(transcript_text)
    tasks: List[str] = []
    next_steps: List[str] = []
    decisions: List[str] = []
    ideas: List[str] = []
    risks: List[str] = []
    current_subject = ""

    for sentence in sentences:
        low = sentence.lower()
        if "вторую главу" in low:
            current_subject = "вторую главу"
        elif "третью главу" in low:
            current_subject = "третью главу"

        if _is_noise_line(sentence):
            continue
        if any(m in low for m in IDEA_MARKERS):
            ideas.extend(_split_compound_task(sentence) or [sentence])
            continue
        if any(m in low for m in RISK_MARKERS):
            risks.append(sentence)
            continue
        if any(m in low for m in DECISION_MARKERS):
            decisions.append(sentence)
            continue

        starts_as_next = any(low.startswith(m) for m in NEXT_STEP_MARKERS)
        middle_next = re.search(r"\b(?:после чего|далее|затем|потом|and after that|after that)\b", low)
        is_task = any(m in low for m in TASK_MARKERS) or bool(middle_next)
        if is_task:
            task_groups: List[tuple[str, bool]] = []
            if starts_as_next:
                task_groups.append((sentence, True))
            elif middle_next:
                idx = middle_next.start()
                before = sentence[:idx].strip(' ,')
                after = sentence[idx:].strip(' ,')
                if before:
                    task_groups.append((before, False))
                if after:
                    task_groups.append((after, True))
            else:
                task_groups.append((sentence, False))

            for piece, send_to_next in task_groups:
                task_parts = _split_compound_task(piece)
                fixed_parts: List[str] = []
                for task in task_parts:
                    if current_subject and re.search(r"\bее\b", task.lower()):
                        task = re.sub(r"\bее\b", current_subject, task, flags=re.I)
                    if current_subject and task.lower().startswith("начать писать") and current_subject not in task.lower():
                        task = f"Начать писать {current_subject}"
                    fixed_parts.append(task)
                if send_to_next:
                    next_steps.extend(fixed_parts)
                else:
                    tasks.extend(fixed_parts)

    tasks = _dedupe_texts(tasks, strong=True)
    next_steps = _dedupe_texts(next_steps, strong=True)
    decisions = _dedupe_texts(decisions, strong=True)
    ideas = _dedupe_texts(ideas, strong=True)
    risks = _dedupe_texts(risks, strong=True)

    tasks = [
        task for task in tasks
        if all(_sim(task, other) < 0.84 and _norm_text(task) not in _norm_text(other) and _norm_text(other) not in _norm_text(task)
               for other in next_steps + decisions)
    ]

    action_items = [{"task": task, "assignee": None, "due": None} for task in tasks]
    summary = _build_summary(tasks, decisions, next_steps)
    return {
        "summary": summary,
        "topics": [],
        "decisions": decisions,
        "action_items": action_items,
        "ideas": ideas,
        "risks": risks,
        "next_steps": next_steps,
        "notes": None,
    }


# Жанры разговора (используются в normalize_protocol_state и regenerate_*).
GENRE_VALUES = {"work_meeting", "interview", "podcast", "lecture", "other"}


def _normalize_genre(value: Any) -> str:
    g = _coerce_text(value).lower().strip()
    if g in GENRE_VALUES:
        return g
    # Простые синонимы и опечатки.
    synonyms = {
        "meeting": "work_meeting", "work": "work_meeting",
        "созвон": "work_meeting", "встреча": "work_meeting",
        "интервью": "interview", "собеседование": "interview",
        "подкаст": "podcast",
        "лекция": "lecture",
    }
    for k, v in synonyms.items():
        if k in g:
            return v
    return "work_meeting"  # безопасный дефолт — обработаем как рабочую встречу


def _vote_genre(genre_hints: List[str]) -> str:
    """По чанковым подсказкам выбираем итоговый жанр.

    Если хоть в нескольких чанках встретилось interview/podcast/lecture — это
    скорее не рабочая встреча. Голосуем большинством, но при равенстве и
    наличии не-work_meeting подсказок — выбираем не-рабочий жанр (там промпт
    мягче и не наделает выдуманных задач).
    """
    counts: Dict[str, int] = {}
    for h in genre_hints:
        g = _normalize_genre(h)
        counts[g] = counts.get(g, 0) + 1
    if not counts:
        return "work_meeting"
    work = counts.get("work_meeting", 0)
    non_work = sum(v for k, v in counts.items() if k != "work_meeting")
    if non_work > work:
        non_work_items = sorted(
            [(k, v) for k, v in counts.items() if k != "work_meeting"],
            key=lambda x: -x[1],
        )
        return non_work_items[0][0]
    return "work_meeting"


# Глаголы в инфинитиве, начало настоящих задач. Не «нужно» (это маркер
# контекста, а не сама задача) — а конкретное действие.
ACTION_VERBS = {
    "сделать", "написать", "дописать", "переписать", "подготовить",
    "проверить", "доработать", "исправить", "привести", "закончить",
    "доделать", "переделать", "обновить", "добавить", "убрать", "удалить",
    "оформить", "запустить", "собрать", "разработать", "реализовать",
    "внедрить", "настроить", "развернуть", "протестировать", "задокументировать",
    "согласовать", "уточнить", "выяснить", "отправить", "созвониться",
    "договориться", "обсудить", "запланировать", "спроектировать",
    "оценить", "предоставить", "выложить", "загрузить", "перенести",
    "связаться", "позвонить",
}

# Слова, на которых ОБРЫВАЕТСЯ предложение → невалидная задача (висящие
# подчинительные/условные/относительные).
DANGLING_TAILS_RE = re.compile(
    r"\b(?:что|чтобы|если|хотя|поскольку|потому|который|которая|которое|которые|так|так как|и так|и так далее)$",
    flags=re.I,
)


def _is_valid_action_task(task: str) -> bool:
    """Жёсткая валидация: похожа ли строка на настоящую поставленную задачу.

    Цель — не пускать обрывки фраз вроде «Бонусы, плюшки и так», «Если
    руководители считают», «Интересно узнать какие результаты». Это типичный
    мусор от LLM на собеседованиях/подкастах, когда она тянет всё подряд по
    маркеру «нужно».
    """
    t = (task or "").strip()
    if not t:
        return False

    low = t.lower()

    # 1. Минимум 5 слов.
    words = [w for w in re.split(r"\s+", low) if w]
    if len(words) < 5:
        return False

    # 2. Должен быть хотя бы один глагол в инфинитиве из списка.
    if not any(re.search(rf"\b{re.escape(v)}(?:ся|сь)?\b", low) for v in ACTION_VERBS):
        return False

    # 3. Не должна заканчиваться висящим союзом/относительным («что», «чтобы»,
    # «если», «и так»).
    if DANGLING_TAILS_RE.search(low):
        return False

    # 4. Не вопрос.
    if t.rstrip().endswith("?"):
        return False
    # вопросительная конструкция в начале — почти всегда не задача
    if re.search(r"^\s*(?:как|какие|какой|какая|какое|сколько|почему|зачем|когда|где|кто|расскажите|расскажи)\b", low):
        return False

    # 5. Не должна начинаться с «я» (личное мнение/планы говорящего).
    if re.match(r"^\s*(?:я|мне|мной|мой|моя|моё|меня)\b", low):
        return False

    # 6. Не должна быть конструкцией «интересно/думаю/кажется/наверное» —
    # это мнения, а не задачи.
    if re.match(r"^\s*(?:интересно|думаю|кажется|наверное|возможно|вероятно)\b", low):
        return False

    return True


def normalize_protocol_state(state: Dict[str, Any] | None, transcript_text: str = "") -> Dict[str, Any]:
    src = dict(state or {})
    # Параметр transcript_text оставлен для обратной совместимости с вызовами
    # сторон (main.py), но больше НЕ используется для построения fake-protocol
    # через эвристику. Эвристика на маркерах слов («нужно», «надо», «обсудить»)
    # давала ложные срабатывания на собеседованиях/подкастах и подсовывала
    # фейковые задачи и summary. Теперь нормализатор просто чистит то, что
    # пришло от LLM, и больше ничего не выдумывает.
    _ = transcript_text  # unused, kept for API compatibility

    # Жанр разговора: новое поле, обратно совместимое (если нет в state — work_meeting).
    genre = _normalize_genre(src.get("genre"))

    def clean_list(items: Any, *, min_words: int = 0) -> List[str]:
        result: List[str] = []
        if isinstance(items, list):
            for item in items:
                txt = _sentence_cleanup(_coerce_text(item))
                if not txt or _is_noise_line(txt):
                    continue
                if min_words and len([w for w in txt.split() if w]) < min_words:
                    continue
                # Отсев висящих хвостов («...что», «...если», «...и так»)
                if DANGLING_TAILS_RE.search(txt.lower()):
                    continue
                result.append(txt)
        return _dedupe_texts(result, strong=True)

    def clean_actions(items: Any) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    task = _extract_task_text(_coerce_text(item.get("task")))
                    assignee = _coerce_text(item.get("assignee")) or None
                    due = _coerce_text(item.get("due")) or None
                else:
                    task = _extract_task_text(_coerce_text(item))
                    assignee = None
                    due = None
                if not task:
                    continue
                if _is_noise_line(task):
                    rejected_actions.append({"task": task, "reason": "noise"})
                    continue
                if not _is_valid_action_task(task):
                    rejected_actions.append({"task": task, "reason": "invalid_format"})
                    continue
                result.append({"task": task, "assignee": assignee, "due": due})
        out: List[Dict[str, Any]] = []
        for item in result:
            if any(_sim(item["task"], prev["task"]) >= 0.84 or _norm_text(item["task"]) in _norm_text(prev["task"]) or _norm_text(prev["task"]) in _norm_text(item["task"]) for prev in out):
                rejected_actions.append({"task": item["task"], "reason": "duplicate"})
                continue
            out.append(item)
        return out

    rejected_actions: List[Dict[str, str]] = []

    summary = _sentence_cleanup(_coerce_text(src.get("summary")))
    if _is_noise_line(summary):
        summary = ""

    topics = clean_list(src.get("topics"), min_words=2)
    key_points = clean_list(src.get("key_points"), min_words=5)
    decisions = clean_list(src.get("decisions"), min_words=4)
    action_items = clean_actions(src.get("action_items"))
    ideas = clean_list(src.get("ideas"), min_words=4)
    risks = clean_list(src.get("risks"), min_words=4)
    next_steps = clean_list(src.get("next_steps"), min_words=4)
    notes = _sentence_cleanup(_coerce_text(src.get("notes")))
    if _is_noise_line(notes):
        notes = ""

    # ВАЖНО: эвристический мёрж из protocol_from_transcript БОЛЬШЕ НЕ ПОДМЕШИВАЕМ
    # автоматически. Раньше он подсовывал в action_items строки типа «Бонусы,
    # плюшки и так» только потому, что там есть маркер «и так». Если LLM сама
    # ничего не вернула — это корректный сигнал «нет задач», а не повод
    # натащить мусора эвристикой. Эвристический base теперь используется
    # только для финального summary как fallback (если LLM вернул пустоту).

    # Если жанр НЕ work_meeting — финальная очистка: задачи/решения/...
    # на не-рабочих жанрах не имеют смысла, и если что-то протекло (например,
    # на одном из чанков LLM ошиблась с genre_hint) — выкидываем.
    genre_truncated_counts = {}
    if genre != "work_meeting":
        if action_items:
            genre_truncated_counts["action_items"] = len(action_items)
        if decisions:
            genre_truncated_counts["decisions"] = len(decisions)
        if next_steps:
            genre_truncated_counts["next_steps"] = len(next_steps)
        if ideas:
            genre_truncated_counts["ideas"] = len(ideas)
        if risks:
            genre_truncated_counts["risks"] = len(risks)
        action_items = []
        decisions = []
        next_steps = []
        ideas = []
        risks = []

    # Удаляем next_steps/decisions, дублирующие action_items
    next_steps = [x for x in next_steps if all(_sim(x, a["task"]) < 0.84 for a in action_items)]
    decisions = [x for x in decisions if all(_sim(x, a["task"]) < 0.84 for a in action_items)]

    # ВАЖНО: эвристический base["summary"] (из protocol_from_transcript) больше
    # НЕ подмешиваем в качестве fallback. Это было главной причиной "мусорного"
    # протокола: на короткой встрече или на встрече, где LLM сознательно
    # вернула summary=null (например потому что это интервью), эвристика
    # сочиняла фейковый "Обсудили рабочие задачи и ближайшие шаги. Зафиксировали,
    # что нужно...". Если LLM не дала summary — значит summary нет, и точка.

    # Сохраняем _meta из исходного state (там может быть chunks/genre_votes от
    # regenerate_protocol_via_groq_chunked) и дописываем validation_stats.
    src_meta = src.get("_meta") if isinstance(src.get("_meta"), dict) else {}
    meta = dict(src_meta)
    if rejected_actions:
        meta["rejected_actions"] = rejected_actions[:20]  # ограничиваем размер
    if genre_truncated_counts:
        meta["truncated_by_genre"] = genre_truncated_counts

    out = {
        "summary": summary or None,
        "genre": genre,
        "topics": topics,
        "key_points": key_points,
        "decisions": decisions,
        "action_items": action_items,
        "ideas": ideas,
        "risks": risks,
        "next_steps": next_steps,
        "notes": notes or None,
    }
    if meta:
        out["_meta"] = meta
    return out


def searchable_protocol_strings(state: Dict[str, Any] | None) -> List[str]:
    p = normalize_protocol_state(state)
    out: List[str] = []
    if p.get("summary"):
        out.append(p["summary"])
    out.extend(p.get("topics") or [])
    out.extend(p.get("key_points") or [])
    out.extend(p.get("decisions") or [])
    out.extend(p.get("ideas") or [])
    out.extend(p.get("risks") or [])
    out.extend(p.get("next_steps") or [])
    for item in p.get("action_items") or []:
        if isinstance(item, dict) and item.get("task"):
            out.append(item["task"])
    return _dedupe_texts(out, strong=True)


def build_protocol_prompt(transcript: str) -> str:
    schema = r'''{
  "summary": "string|null",
  "topics": ["string"],
  "decisions": ["string"],
  "action_items": [
    {
      "task": "string",
      "assignee": "string|null",
      "due": "string|null"
    }
  ],
  "ideas": ["string"],
  "risks": ["string"],
  "next_steps": ["string"],
  "notes": "string|null"
}'''
    return f"""
Ты — система, которая возвращает ТОЛЬКО JSON.
НЕЛЬЗЯ: markdown, пояснения, текст до/после JSON, списки, заголовки.

Ответ должен быть валидным JSON и соответствовать схеме (типы допускаются как указано):
{schema}

Правила заполнения:
- Не выдумывай факты. Используй только то, что явно есть в транскрипте.
- Если для какого-то блока данных недостаточно — ставь пустой массив [] или null.
- ОПРЕДЕЛИ ЖАНР РАЗГОВОРА. Эта система предназначена для разбора рабочих созвонов команды, где обсуждаются конкретные продуктовые/проектные задачи. Если транскрипт по структуре больше похож на интервью/собеседование (вопросы рекрутёра + развёрнутые ответы кандидата), на подкаст/публичное интервью гостя, на обучающую лекцию или на любой другой формат, где НЕТ совместного принятия решений и НЕТ постановки рабочих задач между участниками, ты ОБЯЗАН вернуть: action_items=[], decisions=[], next_steps=[], risks=[], ideas=[], topics=[]. Заполни только summary (1-3 предложения о теме разговора) и notes ("Контент не похож на рабочую встречу команды: <короткое уточнение жанра>").
- Если разговор всё-таки рабочий созвон команды:
  - summary: краткое и фактическое резюме, только если материала достаточно. Если созвон пустой/шумный — null.
  - topics: внутренние темы разговора для аналитики.
  - decisions: только явно ПРИНЯТЫЕ КОМАНДОЙ решения/согласования по маркерам «решили/согласовали/договорились». Реплики типа «я принял решение уйти», «я думаю», «я считаю» — это НЕ командные решения.
  - action_items: только конкретные ЗАДАЧИ, поставленные внутри встречи кому-то из участников. due передавай строкой как в речи, assignee — только если явно назван. НЕ КЛАДИ в action_items вопросы интервьюера, описания прошлого опыта, гипотетические рассуждения.
  - ideas: только идеи/гипотезы/предложения, прозвучавшие как «давайте попробуем», «можно сделать», «вариант — ...». Если в чанках нет явных предложений — [].
  - risks: только явно озвученные риски/блокеры/проблемы по проекту.
  - next_steps: только явно проговорённые следующие шаги команды по маркерам «далее/затем/после чего/на следующей неделе». Реплики кандидата о его планах («рассматриваю предложения», «планирую двигаться дальше») — это НЕ next_steps.
- НИКОГДА не включай в decisions/ideas/risks/topics/action_items приветствия, проверку звука, рекламу, подписки на канал, прощания, междометия и шум.
- НИКОГДА не подменяй ideas темами разговора.
- notes: только если нужно коротко отметить ограничение/неопределённость или жанровое несоответствие; иначе null.

Транскрипт:
{transcript}

Верни ТОЛЬКО JSON.
""".strip()


def build_chunk_prompt(chunk_text: str, chunk_index: int, total_chunks: int) -> str:
    schema = r'''{
  "chunk_index": "integer",
  "chunk_summary": "string",
  "topics": ["string"],
  "decisions": ["string"],
  "action_items": [
    {
      "task": "string",
      "assignee": "string|null",
      "due": "string|null"
    }
  ],
  "ideas": ["string"],
  "risks": ["string"],
  "next_steps": ["string"],
  "key_facts": ["string"]
}'''
    return f"""
Ты — система, которая возвращает ТОЛЬКО JSON (без markdown и без текста вокруг).
Верни валидный JSON по схеме:
{schema}

Уточнения:
- chunk_index: поставь {chunk_index}
- chunk_summary: 2–6 предложений, только если в чанке достаточно фактов; иначе null.
- Не выдумывай факты. Если для блока нет данных — [].
- ВАЖНО ПРО ЖАНР. Эта система разбирает рабочие созвоны команды. Если этот чанк по структуре похож на интервью/собеседование, на подкаст с гостем, на обучающую лекцию (то есть на формат, где нет совместного принятия решений и постановки рабочих задач), ты ОБЯЗАН вернуть пустые списки во всех полях кроме chunk_summary и key_facts: action_items=[], decisions=[], next_steps=[], risks=[], ideas=[], topics=[]. Это касается и фрагментов, где интервьюер задаёт вопросы кандидату, а кандидат описывает свой прошлый опыт.
- topics: только реальные внутренние темы рабочего обсуждения, не темы интервью.
- decisions: только явно ПРИНЯТЫЕ КОМАНДОЙ решения. Личные решения говорящего («я принял решение уйти», «я думаю») — НЕ кладём.
- action_items: только конкретные задачи, поставленные кому-то из участников встречи. Не кладём вопросы интервьюера, описания прошлого опыта, ответы кандидата.
- ideas: только идеи/гипотезы/предложения по проекту.
- risks: только явные риски/блокеры по проекту.
- next_steps: только явно проговорённые следующие шаги команды. Не кладём планы говорящего о собственной карьере.
- Никогда не клади в ideas обычные темы, приветствия, проверку звука, рекламу, подписи и прощания.
- key_facts: короткие факты/цифры/даты/имена из чанка.

Чанк {chunk_index}/{total_chunks}:
{chunk_text}

Верни ТОЛЬКО JSON.
""".strip()


async def _groq_generate_json(prompt: str, model_name: str, timeout_s: float, *, temperature: float = 0.1) -> Dict[str, Any]:
    system_prompt = "Ты — система, которая возвращает ТОЛЬКО JSON."
    return await groq_chat_json(system_prompt, prompt, model=model_name, temperature=temperature, timeout_s=timeout_s)


def _smart_split_text(text: str, target_chars: int = 8000, overlap_chars: int = 600) -> List[str]:
    t = (text or "").strip()
    if not t:
        return []
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    chunks: List[str] = []
    i = 0
    n = len(t)
    while i < n:
        end = min(i + target_chars, n)
        cut = end
        window_start = max(i, end - 1200)
        window = t[window_start:end]
        best = None
        for sep in ["\n", ". ", "? ", "! "]:
            pos = window.rfind(sep)
            if pos != -1:
                best = window_start + pos + (1 if sep == "\n" else 2)
                break
        if best and best > i + int(target_chars * 0.6):
            cut = best
        chunk = t[i:cut].strip()
        if chunk:
            chunks.append(chunk)
        if cut >= n:
            break
        i = max(cut - overlap_chars, 0)
    return chunks


async def generate_protocol_via_groq(transcript: str, model: str | None = None, ollama_base_url: str | None = None, timeout_s: float = 600.0) -> Dict[str, Any]:
    model_name = model or settings.groq_model
    t = (transcript or "").strip()
    # Если транскрипт длиннее ~10 000 символов, не пытаемся уложиться в одну
    # генерацию: при подаче целиком модель часто схлопывает структуру в свалку
    # тем в summary, а при truncate теряется середина встречи. Передаём
    # управление chunked-варианту, который собирает протокол по чанкам с
    # программным мёржем списков.
    if len(t) > 10000:
        return await generate_protocol_via_groq_chunked(
            transcript,
            model=model_name,
            ollama_base_url=ollama_base_url,
            timeout_s=max(timeout_s, 240.0),
        )
    prompt = build_protocol_prompt(t)
    try:
        return normalize_protocol_state(await _groq_generate_json(prompt, model_name, timeout_s, temperature=0.1), transcript)
    except Exception as exc:
        return normalize_protocol_state({
            "summary": None,
            "topics": [],
            "decisions": [],
            "action_items": [],
            "ideas": [],
            "risks": [],
            "next_steps": [],
            "notes": f"PROTOCOL_ERROR: {exc}",
        }, transcript)


def _merge_chunk_lists(chunk_results: List[Dict[str, Any]], key: str) -> List[Any]:
    out: List[Any] = []
    seen_norms: List[str] = []
    for cr in chunk_results:
        for item in cr.get(key) or []:
            if isinstance(item, dict):
                text_for_norm = _coerce_text(item.get("task")) or _coerce_text(item)
            else:
                text_for_norm = _coerce_text(item)
            if not text_for_norm:
                continue
            n = _norm_text(text_for_norm)
            if not n:
                continue
            duplicate = False
            for prev in seen_norms[-32:]:
                if n == prev or n in prev or prev in n:
                    duplicate = True
                    break
                if SequenceMatcher(None, n, prev).ratio() >= 0.84:
                    duplicate = True
                    break
            if not duplicate:
                out.append(item)
                seen_norms.append(n)
    return out


async def generate_protocol_via_groq_chunked(transcript: str, model: str | None = None, ollama_base_url: str | None = None, timeout_s: float = 600.0, *, chunk_target_chars: int = 8000, chunk_overlap_chars: int = 600) -> Dict[str, Any]:
    model_name = model or settings.groq_model
    chunks = _smart_split_text(transcript, target_chars=chunk_target_chars, overlap_chars=chunk_overlap_chars)
    if not chunks:
        return normalize_protocol_state({
            "summary": None,
            "topics": [],
            "decisions": [],
            "action_items": [],
            "ideas": [],
            "risks": [],
            "next_steps": [],
            "notes": "EMPTY_TRANSCRIPT",
        }, transcript)

    total = len(chunks)
    chunk_results: List[Dict[str, Any]] = []
    errors: List[str] = []
    for idx, ch in enumerate(chunks, start=1):
        prompt = build_chunk_prompt(ch, idx, total)
        try:
            obj = await _groq_generate_json(prompt, model_name, timeout_s, temperature=0.1)
            obj["chunk_index"] = idx
            chunk_results.append(obj)
        except Exception as exc:
            errors.append(f"chunk {idx}: {exc}")
            chunk_results.append({
                "chunk_index": idx,
                "chunk_summary": "",
                "topics": [],
                "decisions": [],
                "action_items": [],
                "ideas": [],
                "risks": [],
                "next_steps": [],
                "key_facts": [],
                "error": str(exc),
            })

    # Программный мёрж списков: берём то, что Llama уже разнесла по правильным
    # ключам внутри каждого чанка, склеиваем с дедупликацией. Это спасает от
    # известного режима отказа: на длинном агрегированном входе модель в
    # reduce-промпте схлопывает все ключи в один доминирующий (обычно summary),
    # что и давало «свалку существительных» вместо протокола.
    merged_topics = [_coerce_text(x) for x in _merge_chunk_lists(chunk_results, "topics") if _coerce_text(x)]
    merged_decisions = [_coerce_text(x) for x in _merge_chunk_lists(chunk_results, "decisions") if _coerce_text(x)]
    merged_actions = _merge_chunk_lists(chunk_results, "action_items")
    merged_ideas = [_coerce_text(x) for x in _merge_chunk_lists(chunk_results, "ideas") if _coerce_text(x)]
    merged_risks = [_coerce_text(x) for x in _merge_chunk_lists(chunk_results, "risks") if _coerce_text(x)]
    merged_next = [_coerce_text(x) for x in _merge_chunk_lists(chunk_results, "next_steps") if _coerce_text(x)]

    # Финальный summary просим у LLM, но только из коротких per-chunk сводок —
    # это короткий вход (десятки строк, а не килобайты JSON), на котором модель
    # ведёт себя стабильно.
    chunk_summaries_only = [
        {"chunk_index": cs.get("chunk_index"), "chunk_summary": _coerce_text(cs.get("chunk_summary"))}
        for cs in chunk_results if _coerce_text(cs.get("chunk_summary"))
    ]
    summary: str | None = None
    if chunk_summaries_only:
        summary_prompt = (
            "Ты — система, которая возвращает ТОЛЬКО JSON (без markdown и без текста вокруг).\n\n"
            "Ниже дан список кратких сводок по частям одного длинного созвона.\n"
            "Составь связное итоговое резюме всего созвона на 3–6 предложений в одном поле \"summary\".\n"
            "Не выдумывай факты. Используй только то, что есть в этих сводках. Если материала мало — верни null.\n\n"
            "Верни строго JSON по схеме:\n"
            "{\"summary\": \"string|null\"}\n\n"
            "Сводки чанков (JSON):\n"
            + json.dumps(chunk_summaries_only, ensure_ascii=False)
            + "\n\nВерни ТОЛЬКО JSON."
        )
        try:
            summary_obj = await _groq_generate_json(summary_prompt, model_name, min(timeout_s, 90.0), temperature=0.1)
            raw_summary = _coerce_text(summary_obj.get("summary"))
            summary = raw_summary or None
        except Exception as exc:
            errors.append(f"final summary: {exc}")
            summary = None

    notes = None
    if errors:
        notes = "Часть чанков обработалась с ошибками: " + "; ".join(errors[:3])

    return normalize_protocol_state({
        "summary": summary,
        "topics": merged_topics,
        "decisions": merged_decisions,
        "action_items": merged_actions,
        "ideas": merged_ideas,
        "risks": merged_risks,
        "next_steps": merged_next,
        "notes": notes,
        "_meta": {"chunks": total},
    }, transcript)



def build_state_update_prompt(current_state_json: str, new_text: str) -> str:
    schema = r'''{
  "summary": "string|null",
  "topics": ["string"],
  "decisions": ["string"],
  "action_items": [
    {
      "task": "string",
      "assignee": "string|null",
      "due": "string|null"
    }
  ],
  "ideas": ["string"],
  "risks": ["string"],
  "next_steps": ["string"],
  "notes": "string|null"
}'''
    return f"""
Ты — система, которая возвращает ТОЛЬКО JSON (никакого markdown и текста вокруг).

Твоя задача: обновить JSON-состояние протокола на основе нового фрагмента транскрипта.
Верни валидный JSON строго по схеме:
{schema}

Правила:
- Используй current_state как базу и ДОБАВЬ/ОБНОВИ данные из new_text.
- Не выдумывай факты, которых нет в new_text.
- ВАЖНО ПРО ЖАНР. Эта система предназначена для разбора рабочих созвонов команды. Если new_text по структуре больше похож на интервью/собеседование (вопросы рекрутёра + развёрнутые ответы кандидата), на подкаст с гостем, на обучающую лекцию или на любой формат, где НЕТ совместного принятия решений и постановки рабочих задач между участниками, ты ОБЯЗАН не добавлять ничего в action_items/decisions/next_steps/risks/ideas/topics. Можешь только обновить summary 1-3 предложениями про текущую тему разговора и оставить notes ("Контент не похож на рабочую встречу команды").
- decisions: только явно ПРИНЯТЫЕ КОМАНДОЙ решения по маркерам «решили/согласовали/договорились». «Я принял решение уйти», «я думаю» — НЕ командные решения.
- action_items: только конкретные ЗАДАЧИ, поставленные кому-то из участников встречи. Не клади ответы кандидата, описания прошлого опыта, гипотетические рассуждения.
- next_steps: только явно проговорённые следующие шаги команды. Реплики о собственных карьерных планах говорящего — НЕ next_steps.
- ideas: только идеи/гипотезы/предложения по проекту, не «темы разговора».
- topics/decisions/risks/action_items/ideas/next_steps: добавляй новые элементы, не дублируй уже имеющиеся по смыслу.
- summary: поддерживай как краткую живую сводку всего разговора до текущего момента только по подтверждённым фактам; если фактов мало — можно оставить null.
- Не включай приветствия, рекламу, шум, проверку звука, прощания, рекламные вставки ведущих публичных видео ни в один блок.
- Если что-то непонятно — не добавляй.

current_state (JSON):
{current_state_json}

new_text:
{new_text}

Верни ТОЛЬКО JSON.
""".strip()


async def update_protocol_state_via_groq(current_state: dict, new_text: str, model: str | None = None, ollama_base_url: str | None = None, timeout_s: float = 180.0) -> dict:
    model_name = model or settings.groq_model
    nt = (new_text or "").strip()
    if not nt:
        return normalize_protocol_state(current_state)
    current_json = json.dumps(current_state or {}, ensure_ascii=False)
    prompt = build_state_update_prompt(current_json, nt)
    try:
        return normalize_protocol_state(await _groq_generate_json(prompt, model_name, timeout_s, temperature=0.1), nt)
    except Exception as exc:
        s = dict(current_state or {})
        notes = s.get("notes")
        msg = f"STATE_UPDATE_ERROR: {exc}"
        s["notes"] = ((str(notes) + "\n") if notes else "") + msg
        return normalize_protocol_state(s, nt)


def build_finalize_prompt(state_json: str) -> str:
    schema = r'''{
  "summary": "string|null",
  "topics": ["string"],
  "decisions": ["string"],
  "action_items": [
    {
      "task": "string",
      "assignee": "string|null",
      "due": "string|null"
    }
  ],
  "ideas": ["string"],
  "risks": ["string"],
  "next_steps": ["string"],
  "notes": "string|null"
}'''
    return f"""
Ты — система, которая возвращает ТОЛЬКО JSON.

Ниже дано итоговое состояние протокола (черновик), накопленное по кускам.
Твоя задача: привести к финальному виду:
- убрать дубли по смыслу
- уточнить формулировки без выдумывания фактов
- summary сделать связным резюме всего созвона только если фактов достаточно
- сохранить единый формат данных
- не подменять ideas темами разговора
- не включать шум, рекламу, проверку звука, приветствия и прощания
- если черновик содержит признаки того, что разговор был интервью/собеседованием/подкастом/лекцией (notes об этом, либо action_items/decisions/next_steps выглядят как обрывки реплик из вопросов и ответов, а не как реальные рабочие задачи и решения), очисти все списки от таких обрывков; оставь только summary и notes о жанровом несоответствии

Верни валидный JSON строго по схеме:
{schema}

draft_state:
{state_json}

Верни ТОЛЬКО JSON.
""".strip()


async def finalize_protocol_via_groq(state: dict, model: str | None = None, ollama_base_url: str | None = None, timeout_s: float = 180.0) -> dict:
    model_name = model or settings.groq_model
    state_json = json.dumps(state or {}, ensure_ascii=False)
    prompt = build_finalize_prompt(state_json)
    try:
        return normalize_protocol_state(await _groq_generate_json(prompt, model_name, timeout_s, temperature=0.1))
    except Exception as exc:
        s = dict(state or {})
        notes = s.get("notes")
        msg = f"FINALIZE_ERROR: {exc}"
        s["notes"] = ((str(notes) + "\n") if notes else "") + msg
        return normalize_protocol_state(s)


# ============================================================================
# Genre-aware regenerate-from-scratch (Шаг 1 рефакторинга)
# ----------------------------------------------------------------------------
# Идея: вместо инкрементального update_state каждые 90 сек, который копил
# ошибки и не имел контекста жанра, мы каждый раз генерим протокол С НУЛЯ из
# всего накопленного транскрипта. Llama сама определяет жанр и адаптирует
# содержимое: для рабочих встреч — задачи/решения, для собеседований/подкастов
# — только тезисы по сути, без выдумывания фейковых задач.
#
# GENRE_VALUES, _normalize_genre, _vote_genre объявлены выше, рядом с
# normalize_protocol_state — там они нужны раньше.
# ============================================================================


def build_genre_aware_protocol_prompt(transcript: str) -> str:
    schema = r'''{
  "genre": "work_meeting|interview|podcast|lecture|other",
  "summary": "string|null",
  "topics": ["string"],
  "key_points": ["string"],
  "decisions": ["string"],
  "action_items": [
    {
      "task": "string",
      "assignee": "string|null",
      "due": "string|null"
    }
  ],
  "ideas": ["string"],
  "risks": ["string"],
  "next_steps": ["string"],
  "notes": "string|null"
}'''
    return f"""
Ты — система, которая возвращает ТОЛЬКО JSON. Никакого markdown, пояснений и текста до/после JSON.

КРИТИЧЕСКОЕ ПРАВИЛО: ВСЁ содержимое полей summary, topics, key_points, decisions, action_items, ideas, risks, next_steps, notes ОБЯЗАНО строиться ИСКЛЮЧИТЕЛЬНО на фактах из ТРАНСКРИПТА В КОНЦЕ ЭТОЙ ИНСТРУКЦИИ. Никаких других источников. Если в инструкции встречаются примеры в кавычках (как пояснение формата) — это НЕ контент для копирования, это лишь подсказка о форме. Категорически запрещено вставлять текст этих примеров в свой ответ. Если транскрипт пустой или нерелевантный — верни пустые поля и summary=null.

Ответ должен быть валидным JSON и соответствовать схеме:
{schema}

============================================================
ШАГ 1. ОПРЕДЕЛИ ЖАНР РАЗГОВОРА
============================================================
Поле "genre" — обязательное. Выбери одно значение из:

- "work_meeting" — РАБОЧАЯ ВСТРЕЧА КОМАНДЫ. Несколько участников совместно обсуждают конкретный продукт/проект, ставят друг другу задачи, принимают решения вместе ("решили", "договорились"), назначают ответственных. Маркеры: общий проект, общая ответственность, постановка задач команде.
- "interview" — СОБЕСЕДОВАНИЕ или ИНТЕРВЬЮ. Один задаёт вопросы, другой отвечает. Может быть про работу (рекрутер + кандидат), про опыт, про продукт. Признаки: формат "вопрос — развёрнутый ответ", обсуждение условий найма/опыта/компании, фразы "расскажите о себе", "какой у вас опыт", "какие бонусы", "испытательный срок", обсуждение зарплаты/команды/процессов работы со стороны.
- "podcast" — ПУБЛИЧНОЕ ИНТЕРВЬЮ или ПОДКАСТ с гостем. Ведущий задаёт вопросы эксперту, гость рассказывает истории, делится мнениями. Часто есть промо-вставки.
- "lecture" — ОБУЧАЮЩАЯ ЛЕКЦИЯ или МОНОЛОГ. Один говорящий объясняет тему, может быть с примерами.
- "other" — что-то ещё, не подходит под категории выше.

ЕСЛИ СОМНЕВАЕШЬСЯ между work_meeting и interview — выбирай interview. Признаки именно work_meeting должны быть ЯВНЫМИ: конкретный проект, общие задачи команде, явное "мы решили" / "договорились".

============================================================
ШАГ 2. ЗАПОЛНИ ПОЛЯ В ЗАВИСИМОСТИ ОТ ЖАНРА
============================================================

ЕСЛИ genre == "work_meeting":
  - summary: 1–4 предложения о теме встречи и итогах. Только факты из транскрипта.
  - topics: 2–6 коротких тем разговора (для аналитики).
  - key_points: 3–8 ГЛАВНЫХ ТЕЗИСОВ из встречи. Каждый — законченное предложение ≥ 6 слов, по существу обсуждения. Это НЕ задачи и НЕ решения, это просто то важное, о чём говорили (контекст, факты, цифры, наблюдения, оценки ситуации). Каждый тезис строится ТОЛЬКО на фактах из транскрипта (с конкретикой реального разговора — числами, именами, продуктами, событиями, которые там реально звучали). НЕ копируй формулировки из этой инструкции и НЕ добавляй вымышленные примеры. key_points могут быть на встрече ВСЕГДА, даже если задач и решений нет — это спасает короткие или обзорные встречи от пустого протокола.
  - decisions: ТОЛЬКО явно ПРИНЯТЫЕ КОМАНДОЙ решения по маркерам "решили/согласовали/договорились/утвердили/будем делать". Реплики "я думаю", "я считаю", "наверное" — НЕ решения.
  - action_items: ТОЛЬКО конкретные задачи, поставленные внутри встречи кому-то из участников. Каждая задача:
      * начинается с глагола в инфинитиве (сделать, написать, подготовить, проверить, отправить, собрать, обновить...)
      * ≥ 5 слов, законченная по смыслу
      * не вопрос, не описание прошлого опыта, не гипотеза
      * assignee: только если явно назван по имени или роли в речи. Иначе null. НЕ ВЫДУМЫВАЙ ответственного.
      * due: только если явно назван срок. Иначе null.
  - ideas: только идеи/гипотезы по проекту с маркерами "давайте попробуем", "можно сделать", "вариант — ...".
  - risks: только явно озвученные риски/блокеры по проекту.
  - next_steps: только явные следующие шаги команды по маркерам "далее", "затем", "после чего", "на следующей неделе", "к пятнице".
  - notes: null или короткое замечание.

ЕСЛИ genre == "interview":
  - summary: 2–4 предложения. О чём беседа. Шаблон формы (НЕ копируй текст шаблона, только структуру): "<кто с кем>. Обсуждали <темы из транскрипта через запятую>." Конкретное содержание ОБЯЗАТЕЛЬНО берётся ИЗ ТРАНСКРИПТА, а НЕ из этой инструкции.
  - topics: 3–8 коротких тем РАЗГОВОРА — извлекай из реального содержания транскрипта (например, если в транскрипте речь о продаже квартиры — темы про цену/осмотр/сроки; если речь про работу — темы про обязанности/команду/условия). НЕ копируй темы из этой инструкции.
  - key_points: 3–10 САМЫХ ВАЖНЫХ ТЕЗИСОВ из разговора. Каждый — законченное предложение, ≥ 6 слов, по существу. ВСЕ тезисы строятся ТОЛЬКО на фактах из транскрипта. НЕ обрывки фраз. НЕ вопросы. НЕ копируй формулировки из этой инструкции.
  - decisions: [] — у собеседования нет командных решений.
  - action_items: [] — НЕ ВЫДУМЫВАЙ ЗАДАЧИ. Если рекрутёр сказал "вернусь с обратной связью" — это НЕ задача в протоколе.
  - ideas: [] — обычно пусто.
  - risks: [] — обычно пусто. Только если явно обсуждали риски/проблемы должности.
  - next_steps: пусто [], кроме случаев когда явно проговорены следующие этапы найма ("следующее интервью с тимлидом во вторник").
  - notes: "Тип разговора: собеседование/интервью. Задачи и решения не формируются."

ЕСЛИ genre == "podcast" или "lecture":
  - summary: 2–4 предложения о теме.
  - topics: 3–8 тем.
  - key_points: 3–10 главных тезисов гостя/лектора.
  - decisions/action_items/ideas/risks/next_steps: всё [].
  - notes: "Тип разговора: подкаст/лекция. Задачи и решения не формируются." или аналогично.

ЕСЛИ genre == "other":
  - summary: что смогли понять.
  - topics, key_points: что смогли вытащить.
  - decisions, action_items, ideas, risks, next_steps: [] (по умолчанию).
  - notes: "Не удалось определить рабочий формат разговора."

============================================================
ОБЩИЕ ПРАВИЛА (ВАЖНО)
============================================================
1. НЕ ВЫДУМЫВАЙ ФАКТЫ. Используй только то, что ЯВНО есть в транскрипте.
2. Если для блока данных недостаточно — ставь пустой массив [] или null.
3. НИКОГДА не клади в любые списки: приветствия, проверку звука ("раз-два-три", "слышно ли"), рекламу, "подписывайтесь", прощания, междометия, проверочные реплики "тест-тест".
4. Каждый элемент списка должен быть ЗАКОНЧЕННОЙ мыслью на ≥ 5 слов. Обрывки типа "Бонусы, плюшки и так", "Если руководители считают", "Но если нужно какое-то обучение" — ВЫБРАСЫВАЙ.
5. Не дублируй один и тот же смысл в разных полях.
6. Не подменяй ideas темами разговора.

============================================================
ПРИМЕРЫ ТОГО, ЧТО НЕ НАДО КЛАСТЬ В action_items
============================================================
- "Бонусы, плюшки и так" — обрывок, не задача
- "Если руководители считают что обучение нужно" — условное предложение, не задача
- "Интересно узнать какие результаты в первые 3-6-12 месяцев" — это вопрос соискателя, не задача
- "Я думаю это целесообразно обсудить с руководителем" — мнение, не поставленная задача
- "Расскажите о бонусах" — вопрос интервьюера
- "Я планирую развиваться в этом направлении" — личный план говорящего

ПРИМЕРЫ ХОРОШИХ action_items (только для work_meeting):
- "Подготовить макет страницы регистрации к пятнице" (assignee: "Аня", due: "пятница")
- "Написать раздел 3.4 про методику тестирования"
- "Проверить интеграцию с платёжным шлюзом и зафиксировать результат"

============================================================
ТРАНСКРИПТ
============================================================
{transcript}

Верни ТОЛЬКО JSON.
""".strip()


def build_genre_aware_chunk_prompt(chunk_text: str, chunk_index: int, total_chunks: int) -> str:
    schema = r'''{
  "chunk_index": "integer",
  "genre_hint": "work_meeting|interview|podcast|lecture|other",
  "chunk_summary": "string|null",
  "topics": ["string"],
  "key_points": ["string"],
  "decisions": ["string"],
  "action_items": [
    {
      "task": "string",
      "assignee": "string|null",
      "due": "string|null"
    }
  ],
  "ideas": ["string"],
  "risks": ["string"],
  "next_steps": ["string"]
}'''
    return f"""
Ты — система, которая возвращает ТОЛЬКО JSON. Никакого markdown.

Верни валидный JSON по схеме:
{schema}

Это ЧАНК {chunk_index} из {total_chunks} большого транскрипта.

ПРАВИЛА:
- chunk_index: поставь {chunk_index}.
- genre_hint: твоё предположение о жанре по этому чанку (work_meeting / interview / podcast / lecture / other). Подсказка: если в чанке формат "вопрос-ответ про работу/опыт/условия" — это interview. Если ведущий + гость — podcast. Если совместное обсуждение проекта/задач командой — work_meeting.
- chunk_summary: 1–3 предложения о содержании чанка. Если в чанке только шум/малосодержательная речь — null.
- key_points: 1–5 ГЛАВНЫХ ТЕЗИСОВ из этого чанка для ЛЮБОГО жанра. Каждый ≥ 6 слов, законченная мысль по существу. Если ничего важного — []. Это самое полезное поле для коротких или обзорных встреч, где нет явных задач и решений.
- topics: короткие темы, которые обсудили в этом чанке.

ЕСЛИ genre_hint указывает на НЕ work_meeting (interview / podcast / lecture / other):
  - decisions: []
  - action_items: []
  - ideas: []
  - risks: []
  - next_steps: []
  Это ОБЯЗАТЕЛЬНО. Не клади туда обрывки реплик из вопросов и ответов.

ЕСЛИ genre_hint == "work_meeting":
  - decisions: только явные командные решения ("решили", "договорились").
  - action_items: только конкретные задачи (глагол в инфинитиве, ≥ 5 слов, без выдумок).
  - ideas / risks / next_steps: только явные.

ОБЩИЕ ЗАПРЕТЫ:
- НЕ выдумывай. НЕ переформулируй вопросы как задачи.
- Каждый элемент любого списка — ≥ 5 слов, законченная мысль. Обрывки выбрасывай.
- Не клади приветствия, рекламу, проверку звука, прощания.

ЧАНК {chunk_index}/{total_chunks}:
{chunk_text}

Верни ТОЛЬКО JSON.
""".strip()


async def regenerate_protocol_via_groq(
    transcript: str,
    model: str | None = None,
    timeout_s: float = 180.0,
) -> Dict[str, Any]:
    """Сгенерировать протокол с нуля из всего накопленного транскрипта.

    Это замена update_protocol_state_via_groq для live-режима. Не накапливает
    ошибки, потому что не зависит от предыдущего стейта. На длинном транскрипте
    автоматически уходит в chunked-режим.
    """
    model_name = model or settings.groq_model
    t = (transcript or "").strip()
    if not t:
        return normalize_protocol_state({
            "summary": None,
            "genre": "work_meeting",
            "topics": [],
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "ideas": [],
            "risks": [],
            "next_steps": [],
            "notes": None,
        }, transcript)

    if len(t) > 10000:
        return await regenerate_protocol_via_groq_chunked(
            transcript,
            model=model_name,
            timeout_s=max(timeout_s, 240.0),
        )

    prompt = build_genre_aware_protocol_prompt(t)
    try:
        raw = await _groq_generate_json(prompt, model_name, timeout_s, temperature=0.1)
        return normalize_protocol_state(raw, transcript)
    except Exception as exc:
        return normalize_protocol_state({
            "summary": None,
            "genre": "work_meeting",
            "topics": [],
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "ideas": [],
            "risks": [],
            "next_steps": [],
            "notes": f"PROTOCOL_ERROR: {exc}",
        }, transcript)


async def regenerate_protocol_via_groq_chunked(
    transcript: str,
    model: str | None = None,
    timeout_s: float = 600.0,
    *,
    chunk_target_chars: int = 8000,
    chunk_overlap_chars: int = 600,
) -> Dict[str, Any]:
    """Chunked-версия регенерации с голосованием по жанру.

    Делим транскрипт, на каждом чанке Llama даёт genre_hint + локальные данные.
    Потом голосованием решаем итоговый жанр и собираем финальный протокол.
    Если жанр == work_meeting — оставляем мёрж задач/решений как раньше.
    Если жанр НЕ work_meeting — оставляем только summary, topics, key_points,
    а action_items/decisions/next_steps/risks/ideas вычищаем (Llama по чанкам
    могла что-то насочинять — final-stage откатывает это назад).
    """
    model_name = model or settings.groq_model
    chunks = _smart_split_text(transcript, target_chars=chunk_target_chars, overlap_chars=chunk_overlap_chars)
    if not chunks:
        return normalize_protocol_state({
            "summary": None,
            "genre": "work_meeting",
            "topics": [],
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "ideas": [],
            "risks": [],
            "next_steps": [],
            "notes": "EMPTY_TRANSCRIPT",
        }, transcript)

    total = len(chunks)
    chunk_results: List[Dict[str, Any]] = []
    errors: List[str] = []
    for idx, ch in enumerate(chunks, start=1):
        prompt = build_genre_aware_chunk_prompt(ch, idx, total)
        try:
            obj = await _groq_generate_json(prompt, model_name, timeout_s, temperature=0.1)
            obj["chunk_index"] = idx
            chunk_results.append(obj)
        except Exception as exc:
            errors.append(f"chunk {idx}: {exc}")
            chunk_results.append({
                "chunk_index": idx,
                "genre_hint": "work_meeting",
                "chunk_summary": "",
                "topics": [],
                "key_points": [],
                "decisions": [],
                "action_items": [],
                "ideas": [],
                "risks": [],
                "next_steps": [],
                "error": str(exc),
            })

    # Голосование по жанру
    genre_hints = [str(cr.get("genre_hint") or "") for cr in chunk_results]
    final_genre = _vote_genre(genre_hints)

    # Мёрж списков из чанков
    merged_topics = [_coerce_text(x) for x in _merge_chunk_lists(chunk_results, "topics") if _coerce_text(x)]
    merged_key_points = [_coerce_text(x) for x in _merge_chunk_lists(chunk_results, "key_points") if _coerce_text(x)]

    if final_genre == "work_meeting":
        merged_decisions = [_coerce_text(x) for x in _merge_chunk_lists(chunk_results, "decisions") if _coerce_text(x)]
        merged_actions = _merge_chunk_lists(chunk_results, "action_items")
        merged_ideas = [_coerce_text(x) for x in _merge_chunk_lists(chunk_results, "ideas") if _coerce_text(x)]
        merged_risks = [_coerce_text(x) for x in _merge_chunk_lists(chunk_results, "risks") if _coerce_text(x)]
        merged_next = [_coerce_text(x) for x in _merge_chunk_lists(chunk_results, "next_steps") if _coerce_text(x)]
    else:
        # Не рабочая встреча: НЕ мёржим задачи/решения, чтобы не натащить выдумок
        merged_decisions = []
        merged_actions = []
        merged_ideas = []
        merged_risks = []
        merged_next = []

    # Финальный summary из чанковых сводок
    chunk_summaries_only = [
        {"chunk_index": cs.get("chunk_index"), "chunk_summary": _coerce_text(cs.get("chunk_summary"))}
        for cs in chunk_results if _coerce_text(cs.get("chunk_summary"))
    ]
    summary: str | None = None
    if chunk_summaries_only:
        summary_prompt = (
            "Ты — система, которая возвращает ТОЛЬКО JSON (без markdown).\n\n"
            f"Жанр разговора: {final_genre}.\n"
            "Ниже дан список кратких сводок по частям одного длинного разговора.\n"
            "Составь связное итоговое резюме всего разговора на 3–6 предложений в одном поле \"summary\".\n"
            "Не выдумывай факты. Используй только то, что есть в этих сводках. Если материала мало — верни null.\n\n"
            "Верни строго JSON по схеме:\n"
            "{\"summary\": \"string|null\"}\n\n"
            "Сводки чанков (JSON):\n"
            + json.dumps(chunk_summaries_only, ensure_ascii=False)
            + "\n\nВерни ТОЛЬКО JSON."
        )
        try:
            summary_obj = await _groq_generate_json(summary_prompt, model_name, min(timeout_s, 90.0), temperature=0.1)
            raw_summary = _coerce_text(summary_obj.get("summary"))
            summary = raw_summary or None
        except Exception as exc:
            errors.append(f"final summary: {exc}")
            summary = None

    notes = None
    if final_genre == "interview":
        notes = "Тип разговора: собеседование/интервью. Задачи и решения не формируются."
    elif final_genre == "podcast":
        notes = "Тип разговора: подкаст. Задачи и решения не формируются."
    elif final_genre == "lecture":
        notes = "Тип разговора: лекция/монолог. Задачи и решения не формируются."
    elif final_genre == "other":
        notes = "Не удалось определить рабочий формат разговора."

    if errors:
        err_str = "Часть чанков обработалась с ошибками: " + "; ".join(errors[:3])
        notes = (notes + "\n" + err_str) if notes else err_str

    return normalize_protocol_state({
        "summary": summary,
        "genre": final_genre,
        "topics": merged_topics,
        "key_points": merged_key_points,
        "decisions": merged_decisions,
        "action_items": merged_actions,
        "ideas": merged_ideas,
        "risks": merged_risks,
        "next_steps": merged_next,
        "notes": notes,
        "_meta": {"chunks": total, "genre_votes": genre_hints},
    }, transcript)


GENRE_HEADER_RU = {
    "work_meeting": "🧾 ПРОТОКОЛ ВСТРЕЧИ",
    "interview": "🧾 ПРОТОКОЛ РАЗГОВОРА (собеседование/интервью)",
    "podcast": "🧾 ПРОТОКОЛ РАЗГОВОРА (подкаст/публичное интервью)",
    "lecture": "🧾 ПРОТОКОЛ РАЗГОВОРА (лекция/монолог)",
    "other": "🧾 ПРОТОКОЛ РАЗГОВОРА",
}


def render_protocol_text(p: dict | None) -> str:
    p = normalize_protocol_state(p)
    if not p or not isinstance(p, dict):
        return "🧾 ПРОТОКОЛ ВСТРЕЧИ\n\n(Пока нет данных для сводки.)"

    def clean(s: Any) -> str:
        return s.strip() if isinstance(s, str) else ""

    genre = _normalize_genre(p.get("genre"))
    summary = clean(p.get("summary"))
    topics = _dedupe_texts(p.get("topics") or [], strong=True)
    key_points = _dedupe_texts(p.get("key_points") or [], strong=True)
    decisions = _dedupe_texts(p.get("decisions") or [], strong=True)
    ideas = _dedupe_texts(p.get("ideas") or [], strong=True)
    risks = _dedupe_texts(p.get("risks") or [], strong=True)
    next_steps = _dedupe_texts(p.get("next_steps") or [], strong=True)

    action_lines = []
    for item in p.get("action_items") or []:
        if not isinstance(item, dict):
            continue
        task = clean(item.get("task"))
        assignee = clean(item.get("assignee"))
        due = clean(item.get("due"))
        if not task:
            continue
        line = f"- {task}"
        meta = []
        if assignee:
            meta.append(f"ответственный: {assignee}")
        if due:
            meta.append(f"срок: {due}")
        if meta:
            line += f" ({', '.join(meta)})"
        action_lines.append(line)

    header = GENRE_HEADER_RU.get(genre, "🧾 ПРОТОКОЛ ВСТРЕЧИ")
    out = [header, ""]

    # Плашка жанра только для не-рабочих форматов
    if genre != "work_meeting":
        genre_hint_ru = {
            "interview": "Это собеседование или интервью — задачи и решения не формируются. Ниже — главные тезисы и темы.",
            "podcast": "Это подкаст или публичное интервью с гостем — задачи и решения не формируются. Ниже — главные тезисы и темы.",
            "lecture": "Это лекция или монолог — задачи и решения не формируются. Ниже — главные тезисы.",
            "other": "Не удалось определить рабочий формат разговора. Ниже — то, что удалось вытащить.",
        }
        out.extend([genre_hint_ru.get(genre, ""), ""])

    if summary:
        out.extend(["Кратко:", summary, ""])

    # Темы показываем для любого жанра — это полезный обзор о чём шла речь
    if topics:
        out.extend(["Темы:", "\n".join(f"- {x}" for x in topics), ""])

    # Главные тезисы — основное полезное содержимое для всех жанров: для интервью
    # и подкастов это вообще главное, для work_meeting спасает протокол от
    # пустоты, когда задач и решений нет (короткие встречи, обзорные созвоны)
    if key_points:
        out.extend(["Главные тезисы:", "\n".join(f"- {x}" for x in key_points), ""])

    # Эти разделы — только для work_meeting (на других нормализатор уже их вычистил)
    if decisions:
        out.extend(["Решения:", "\n".join(f"- {x}" for x in decisions), ""])
    if action_lines:
        out.extend(["Задачи:", "\n".join(action_lines), ""])
    if ideas:
        out.extend(["Идеи:", "\n".join(f"- {x}" for x in ideas), ""])
    if risks:
        out.extend(["Риски:", "\n".join(f"- {x}" for x in risks), ""])
    if next_steps:
        out.extend(["Следующие шаги:", "\n".join(f"- {x}" for x in next_steps), ""])

    text = "\n".join(out).strip()
    if text == header:
        return f"{header}\n\n(Пока нет данных для сводки.)"
    return text
