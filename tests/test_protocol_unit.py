from app.services.protocol import (
    _is_noise_line,
    _sentence_cleanup,
    _split_compound_task,
    normalize_protocol_state,
    protocol_from_transcript,
    searchable_protocol_strings,
)


def test_filters_promo_noise():
    assert _is_noise_line("подписывайтесь на наш канал") is True


def test_keeps_real_task():
    assert _is_noise_line("нужно дописать третью главу до пятницы") is False


def test_sentence_cleanup_fixes_common_asr_error():
    result = _sentence_cleanup("не париться антипугиатом")
    assert "антиплагиат" in result.lower()


def test_splits_compound_tasks():
    tasks = _split_compound_task("нужно дописать приложение, подготовить диаграммы")
    assert tasks == ["Дописать приложение", "Подготовить диаграммы"]


def test_protocol_extracts_action_items_and_decisions():
    transcript = """
ME: всем привет, как меня слышно?
THEM: решили использовать Groq для генерации протоколов.
ME: нужно дописать третью главу, подготовить диаграммы.
THEM: после чего проверить текст антиплагиатом.
"""
    result = protocol_from_transcript(transcript)

    task_texts = [x["task"].lower() for x in result["action_items"]]

    assert any("дописать третью главу" in t for t in task_texts)
    assert any("подготовить диаграммы" in t for t in task_texts)
    assert any("groq" in d.lower() for d in result["decisions"])
    assert any("проверить текст" in x.lower() for x in result["next_steps"])


def test_normalize_protocol_removes_noise_and_deduplicates():
    raw = {
        # Жанр явно work_meeting, чтобы новая логика (вычищать задачи на не-work)
        # не съела всё. По-умолчанию тоже work_meeting, но укажем явно.
        "genre": "work_meeting",
        "summary": "подписывайтесь на наш канал",
        "topics": [],
        # decisions теперь требуют ≥ 4 слов; делаем нормальное решение и его дубль
        "decisions": [
            "Решили сделать MVP проекта к декабрю",
            "Решили сделать MVP проекта к декабрю",
        ],
        "action_items": [
            # ≥ 5 слов + глагол в инфинитиве «подготовить»
            {"task": "нужно подготовить презентацию для встречи в пятницу", "assignee": "Иван", "due": "пятница"},
            # промо-шум, должен вылететь по _is_noise_line
            {"task": "подписывайтесь", "assignee": None, "due": None},
            # короткий обрывок — должен отвалиться по _is_valid_action_task (< 5 слов)
            {"task": "сделать макет", "assignee": None, "due": None},
        ],
        "ideas": [],
        "risks": [],
        "next_steps": [],
        "notes": "",
    }

    result = normalize_protocol_state(raw)

    # summary — промо, должен стать None
    assert result["summary"] is None
    # дубль решения должен схлопнуться
    assert len(result["decisions"]) == 1
    assert "MVP" in result["decisions"][0]
    # из 3 кандидатов в action_items выживает только нормальная задача
    assert len(result["action_items"]) == 1
    survived = result["action_items"][0]
    assert "презентац" in survived["task"].lower()
    assert survived["assignee"] == "Иван"
    assert survived["due"] == "пятница"


def test_searchable_protocol_strings_contains_key_items():
    state = {
        # Явный work_meeting, чтобы ничего не вычистилось.
        "genre": "work_meeting",
        "summary": "Обсудили дипломный проект и метрики качества",
        "topics": [],
        # ≥ 4 слов
        "decisions": ["Решили провести тестирование на пользователях нашей группы"],
        # ≥ 5 слов + глагол «собрать» в инфинитиве
        "action_items": [{"task": "Собрать WER таблицу по результатам тестирования", "assignee": None, "due": None}],
        "ideas": [],
        "risks": [],
        "next_steps": [],
        "notes": None,
    }

    strings = searchable_protocol_strings(state)

    assert "диплом" in " ".join(strings).lower()
    assert any("WER" in x or "wer" in x.lower() for x in strings)