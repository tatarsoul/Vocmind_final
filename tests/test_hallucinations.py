"""Тесты для детектора whisper-leak initial_prompt в _clean_hallucinations.

Цель: убедиться что строки типа
"ME: Термины, Groq, DeepSeek, ChatGPT, OpenAI, API, KPI, ROI, backend..."
которые whisper иногда «проговаривает» из своего initial_prompt — не
попадают в финальный транскрипт.

Функция _clean_hallucinations живёт в main.py с FastAPI зависимостями,
поэтому копируем её сюда (в реальном тесте просто импортировать нельзя).
"""
import sys
import re


# Точная копия из app/main.py — изменения тут нельзя без синхронизации с main!
def _clean_hallucinations(text: str) -> str:
    if not text:
        return ""

    bad_phrases = [
        "редактор субтитров", "а.синецкая", "синецкая", "а.егорова",
        "динамичная музыка", "позитивная музыка", "продолжение следует",
        "субтитры создавал", "субтитры субтитры", "субтитры", "музыка",
        "спасибо за просмотр", "подписывайтесь на наш канал", "подписывайтесь",
        "recording in progress", "recording stopped", "recording started",
        "this meeting is being recorded",
        "запись начата", "запись остановлена", "запись на облако",
        "встреча записывается",
        "ссылка в профиле", "ссылку вы найдете в профиле", "ссылка в описании",
        "переходите по ссылке", "по поисковому слову", "по поисковым словам",
        "по поисковым слову", "по закрепу", "позакреп", "позакрепу",
        "выложил в канал", "выложил в telegram", "выложил в телеграм",
        "доступен для подписчиков канала", "qr-код на экране", "qr код на экране",
    ]

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


# ---- Тесты на реальный кейс пользователя -----------------------------------

def test_real_leak_from_user_log():
    """Точный текст что мы видели в docx пользователя."""
    text = "ME: Термины, Groq, DeepSeek, ChatGPT, OpenAI, API, KPI, ROI, backend, startup, deadline, feedback."
    result = _clean_hallucinations(text)
    assert result == "", f"Должна была отфильтроваться, получили: {result!r}"


def test_real_leak_with_them_prefix():
    text = "THEM: Термины: VocMind, Groq, DeepSeek, ChatGPT, OpenAI, API, KPI, ROI."
    result = _clean_hallucinations(text)
    assert result == ""


def test_leak_without_terminy_word():
    """Если строка не начинается с 'Термины', но почти все слова — термины из
    leak-set, тоже отвергаем (50%+ ratio)."""
    text = "ME: Groq DeepSeek ChatGPT OpenAI API"
    result = _clean_hallucinations(text)
    assert result == ""


def test_three_terms_in_normal_speech_kept():
    """Если 3+ термина, но это нормальная речь (есть много обычных слов),
    оставляем — это реальное обсуждение технологий."""
    text = (
        "ME: Мы вчера обсуждали интеграцию через API между нашим backend "
        "и сервисом ChatGPT, и с deadline укладываемся нормально"
    )
    result = _clean_hallucinations(text)
    assert "ChatGPT" in result or "chatgpt" in result.lower()
    assert "API" in result or "api" in result.lower()


def test_one_term_kept():
    """Если в строке только один технический термин — это точно нормально."""
    text = "ME: Подскажите, как работает Groq в вашем стеке?"
    result = _clean_hallucinations(text)
    assert "Groq" in result


def test_two_terms_kept():
    """Два термина в нормальной фразе — тоже норм."""
    text = "ME: Мы используем Groq для backend-части нашего сервиса"
    result = _clean_hallucinations(text)
    assert "Groq" in result
    assert "backend" in result


def test_normal_meeting_text_passes():
    text = "ME: Привет всем, начинаем встречу обсуждать план релиза"
    assert _clean_hallucinations(text) == text


def test_empty_input():
    assert _clean_hallucinations("") == ""
    assert _clean_hallucinations(None) == ""


def test_mixed_normal_and_leak_lines():
    """Если в тексте есть и нормальные строки и leak-строка — leak убираем,
    нормальные оставляем."""
    text = (
        "ME: Расскажите о вашей команде\n"
        "ME: Термины, Groq, DeepSeek, ChatGPT, OpenAI, API, KPI, ROI\n"
        "THEM: У нас сейчас в команде шесть человек"
    )
    result = _clean_hallucinations(text)
    lines = result.splitlines()
    assert len(lines) == 2
    assert "Расскажите" in lines[0]
    assert "Термины" not in result
    assert "DeepSeek" not in result


if __name__ == "__main__":
    import inspect
    tests = [(name, fn) for name, fn in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
             if name.startswith("test_")]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  💥 {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
