import time

from app.services.protocol import protocol_from_transcript


def test_full_pipeline_simple_transcript():
    transcript = """
    ME: Сегодня обсуждаем дипломный проект VocMind.
    THEM: Решили использовать Whisper для распознавания речи.
    ME: Нужно подготовить таблицу тестирования и написать раздел 3.4.
    THEM: Также нужно проверить текст на антиплагиат.
    """

    result = protocol_from_transcript(transcript)

    assert "action_items" in result
    assert "decisions" in result
    assert "next_steps" in result

    combined_text = " ".join(
        [item["task"].lower() for item in result["action_items"]]
        + [item.lower() for item in result["decisions"]]
        + [item.lower() for item in result["next_steps"]]
    )

    assert "раздел 3.4" in combined_text
    assert "антиплагиат" in combined_text
    assert "whisper" in combined_text

def test_protocol_quality_extracts_expected_items():
    transcript = """
    ME: Нужно реализовать страницу со списком встреч.
    THEM: Решили хранить протоколы в базе данных.
    ME: Нужно добавить поиск по задачам и решениям.
    THEM: Основной риск — ошибки распознавания речи.
    """

    result = protocol_from_transcript(transcript)

    tasks = " ".join(item["task"].lower() for item in result["action_items"])
    decisions = " ".join(item.lower() for item in result["decisions"])
    risks = " ".join(item.lower() for item in result["risks"])

    assert "страницу" in tasks
    assert "поиск" in tasks
    assert "базе данных" in decisions
    assert "распознавания речи" in risks


def test_protocol_processing_performance():
    transcript = """
    ME: Нужно подготовить отчёт по тестированию.
    THEM: Решили использовать автоматическую генерацию протоколов.
    ME: Нужно оформить таблицы и результаты.
    """ * 200

    start = time.time()
    result = protocol_from_transcript(transcript)
    duration = time.time() - start

    assert "action_items" in result
    assert duration < 3