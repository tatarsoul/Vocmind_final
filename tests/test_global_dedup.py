"""Тесты для dedupe_global_long_repeats и clean_transcript.

Проверяем на реальном кейсе из теста на 2.5 минут (vocmind_meeting__7_.docx),
где видны "большие" повторы через всю встречу — целые куски стартового
монолога повторяются ближе к концу записи.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.transcript_utils import (
    clean_transcript,
    dedupe_adjacent_repeats,
    dedupe_global_long_repeats,
)


# ==== Тесты dedupe_global_long_repeats ====================================

def test_global_dedup_empty():
    assert dedupe_global_long_repeats("") == ""
    assert dedupe_global_long_repeats(None) == ""


def test_global_dedup_no_duplicates():
    text = (
        "ME: первая длинная фраза которая ничем не повторяется\n"
        "THEM: совершенно другая мысль про что-то ещё\n"
        "ME: третья независимая реплика без повторов"
    )
    result = dedupe_global_long_repeats(text)
    assert result == text


def test_global_dedup_real_case_from_user_recording():
    """Тот самый кейс из vocmind_meeting__7_.docx.

    Целые куски стартового монолога видео-разоблачения повторяются ближе к
    концу записи. Это не соседние повторы — между ними целый диалог.
    """
    text = (
        "THEM: Подозрительными или если вы увидели в записи манипуляции со стороны HR обязательно напишите об этом в комментариях\n"
        "THEM: Да и в целом будет интересно услышать ваше мнение по поводу вопросов который задает здесь рекрутер\n"
        "THEM: Добрый день Виктория Слышно Хорошо меня\n"
        "THEM: Да слышно видно\n"
        "THEM: Да сложно видно Вы не походите если я поставлю нашу беседу на запись\n"
        "THEM: Да пожалуйста хорошо Отлично\n"
        "THEM: Так запись у нас началась\n"
        "THEM: Меня зовут Виктория я репрутер по позиции Project Manager\n"
        "THEM: Тайминг встречи обычно третий-сорок минут Хорошо\n"
        "THEM: Да окей\n"
        # А теперь — большие повторы через всю встречу:
        "THEM: Подозрительными Или если вы увидели в записи манипуляции со стороны HR обязательно напишите об этом в комментариях\n"
        "THEM: Да и в целом будет интересно услышать ваше мнение по поводу вопросов который задает здесь рекрутер\n"
        "THEM: Добрый день Виктория Слышно Хорошо меня\n"
    )
    result = dedupe_global_long_repeats(text)
    lines = result.splitlines()

    # Из 13 строк должно остаться 10 (удалены 3 повтора в конце)
    assert len(lines) == 10, f"Ожидали 10 строк, получили {len(lines)}: {[l[:50] for l in lines]}"

    # Первое упоминание каждой повторяющейся фразы должно остаться
    full = "\n".join(lines)
    assert full.count("Подозрительными") == 1
    assert full.count("Да и в целом будет интересно") == 1
    assert full.count("Добрый день") == 1
    # А короткие — не вычищаются:
    assert "Да окей" in full or "окей" in full


def test_global_dedup_short_lines_not_touched():
    """Короткие реплики ('да', 'окей', 'понятно') могут законно повторяться."""
    text = (
        "ME: да\n"
        "THEM: понятно\n"
        "ME: да\n"
        "THEM: окей\n"
        "ME: да"
    )
    result = dedupe_global_long_repeats(text)
    # все короткие (< 40 символов) пропускаются без проверки
    assert result.count("да") == 3
    assert result.count("окей") == 1


def test_global_dedup_substring_caught():
    """Если одна строка — подстрока другой длинной → дубль."""
    text = (
        "THEM: Это большая сложная мысль про важную тему которую обсуждали участники\n"
        "THEM: Это совершенно другая реплика для разделения\n"
        "THEM: Это большая сложная мысль про важную тему которую обсуждали"
    )
    result = dedupe_global_long_repeats(text)
    lines = result.splitlines()
    # Третья — подстрока первой → должна быть удалена
    assert len(lines) == 2


def test_global_dedup_fuzzy_match_through_whole_text():
    """Лёгкие ASR-различия в одну-две буквы → всё равно дубль."""
    text = (
        "THEM: Меня зовут Виктория, я рекрутер по позиции Project Manager в компанию\n"
        "ME: А какие там основные обязанности на этой позиции в начале работы\n"
        "THEM: Меня зовут Виктория я репрутер по позиции Project Manager в компанию"
    )
    # 'рекрутер' vs 'репрутер' — это типичная ASR-ошибка, фразы должны слиться
    result = dedupe_global_long_repeats(text)
    lines = result.splitlines()
    assert len(lines) == 2, f"Ожидали 2 строки, получили {len(lines)}"


def test_global_dedup_different_topics_not_merged():
    """Разные мысли длинные — не сливаются."""
    text = (
        "THEM: Давайте обсудим план релиза нашего нового продукта в следующем квартале\n"
        "THEM: А теперь поговорим о бюджете маркетинговой кампании на эту осень"
    )
    result = dedupe_global_long_repeats(text)
    assert result == text


# ==== Тесты clean_transcript (полный пайплайн) ============================

def test_clean_transcript_empty():
    assert clean_transcript("") == ""
    assert clean_transcript(None) == ""


def test_clean_transcript_does_both_passes():
    """clean_transcript = adjacent + global. Должен убирать оба типа дублей."""
    text = (
        "THEM: Это первое длинное вступление к встрече ровно для теста чистки\n"
        "THEM: Это первое длинное вступление к встрече ровно для теста чистки\n"  # adjacent dup
        "THEM: Совсем другая мысль для разделения текста\n"
        "ME: Я хочу добавить ещё одну реплику для контекста разговора\n"
        "THEM: Это первое длинное вступление к встрече ровно для теста чистки\n"  # global dup
    )
    result = clean_transcript(text)
    lines = result.splitlines()
    assert len(lines) == 3, f"Ожидали 3, получили {len(lines)}: {lines}"


def test_clean_transcript_preserves_normal_dialogue():
    text = (
        "ME: давай обсудим план релиза\n"
        "THEM: согласен начнём с архитектуры\n"
        "ME: я подготовил черновик документации\n"
        "THEM: посмотрю и пришлю замечания к четвергу\n"
        "ME: спасибо тогда фиксируем эту версию"
    )
    assert clean_transcript(text) == text


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
