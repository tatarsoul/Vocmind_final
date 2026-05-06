"""Тесты для dedupe_adjacent_repeats: чистка самоповторов соседних реплик."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Прямой импорт без шима — модуль самодостаточный
from app.services.transcript_utils import dedupe_adjacent_repeats


def test_empty_input():
    assert dedupe_adjacent_repeats("") == ""
    assert dedupe_adjacent_repeats(None) == ""


def test_no_duplicates_passes_through():
    text = "ME: привет всем\nTHEM: добрый день"
    assert dedupe_adjacent_repeats(text) == text


def test_real_case_from_user_log():
    """Тот самый случай из лога напарника."""
    text = (
        "THEM: Дай глубокие вопросы именно про процессы. Интересно узнать какие результаты нужно добиться в первые 3-6-12 месяцев. Я думаю, что это тогда целесообразно уже с руководителем обсудить.\n"
        "THEM: Я думаю, что это тогда целесообразно уже с руководителем обсудить.\n"
        "THEM: Да, разумеется, он вам ответит более точной и кратко, чем я."
    )
    result = dedupe_adjacent_repeats(text)
    lines = result.splitlines()
    # Из 3 строк должно остаться 2: дублирующая «Я думаю...» съедается, потому
    # что предыдущая её содержит.
    assert len(lines) == 2, f"Ожидали 2 строки, получили {len(lines)}: {lines}"
    assert "разумеется" in lines[1]


def test_exact_duplicate_removed():
    text = (
        "ME: одна и та же фраза подряд\n"
        "ME: одна и та же фраза подряд"
    )
    result = dedupe_adjacent_repeats(text)
    assert result.count("одна и та же фраза подряд") == 1


def test_substring_repeat_keeps_longer():
    """Если одна реплика — подстрока другой, оставляем более длинную."""
    text = (
        "ME: Я думаю это правильное решение\n"
        "ME: Я думаю это правильное решение по нашему проекту"
    )
    result = dedupe_adjacent_repeats(text)
    lines = result.splitlines()
    assert len(lines) == 1
    assert "по нашему проекту" in lines[0]


def test_substring_repeat_keeps_longer_reverse():
    """Тот же кейс, но более длинная идёт первой."""
    text = (
        "ME: Я думаю это правильное решение по нашему проекту\n"
        "ME: Я думаю это правильное решение"
    )
    result = dedupe_adjacent_repeats(text)
    lines = result.splitlines()
    assert len(lines) == 1
    assert "по нашему проекту" in lines[0]


def test_fuzzy_repeat_with_minor_diff():
    """Различие в одно-два слова → всё равно дубль."""
    text = (
        "THEM: Если руководители считают что это обучение действительно нужно человеку\n"
        "THEM: Если руководители считают что это обучение действительно нужно сотруднику"
    )
    result = dedupe_adjacent_repeats(text)
    lines = result.splitlines()
    assert len(lines) == 1


def test_different_speakers_not_merged():
    """Разные спикеры — даже идентичные фразы не сливаются."""
    text = (
        "ME: согласен полностью с этим решением\n"
        "THEM: согласен полностью с этим решением"
    )
    result = dedupe_adjacent_repeats(text)
    lines = result.splitlines()
    assert len(lines) == 2


def test_short_lines_not_fuzzy_matched():
    """На коротких репликах нечёткое сходство не применяется (риск ложных срабатываний)."""
    text = (
        "ME: да хорошо\n"
        "ME: да понятно"
    )
    result = dedupe_adjacent_repeats(text)
    # обе короче 20 символов → fuzzy не работает, но они не подстрока друг друга → обе остаются
    lines = result.splitlines()
    assert len(lines) == 2


def test_repeats_with_other_lines_between_kept():
    """Повтор через другую реплику — не считается дублем (окно = 1)."""
    text = (
        "ME: одна и та же мысль через две реплики\n"
        "THEM: вставная реплика\n"
        "ME: одна и та же мысль через две реплики"
    )
    result = dedupe_adjacent_repeats(text)
    lines = result.splitlines()
    # Намеренно: окно = 1, через другого спикера дубли не убираем
    assert len(lines) == 3


def test_punctuation_ignored_in_comparison():
    """Различия только в пунктуации не делают строки разными."""
    text = (
        "ME: Привет всем участникам встречи!\n"
        "ME: Привет всем участникам встречи."
    )
    result = dedupe_adjacent_repeats(text)
    lines = result.splitlines()
    assert len(lines) == 1


def test_case_insensitive():
    text = (
        "ME: Это решение мы приняли вместе\n"
        "ME: это решение мы приняли вместе"
    )
    result = dedupe_adjacent_repeats(text)
    lines = result.splitlines()
    assert len(lines) == 1


def test_lines_without_speaker_handled():
    """Строки без ME:/THEM: тоже должны обрабатываться (но не сливаться по спикеру)."""
    text = (
        "обычная строка без спикера\n"
        "обычная строка без спикера"
    )
    result = dedupe_adjacent_repeats(text)
    # Без явного спикера условие sp == prev_sp выполняется (оба ""), но
    # поскольку prev_sp == "" — реально мы НЕ сравниваем (в коде проверка
    # `if sp and prev_sp ...`). То есть обе строки останутся.
    lines = result.splitlines()
    assert len(lines) == 2


def test_long_real_dialogue_preserved():
    """Длинный нормальный диалог без дублей — должен пройти неизменным."""
    text = (
        "ME: давай обсудим план релиза\n"
        "THEM: согласен начнём с архитектуры\n"
        "ME: я подготовил черновик документации\n"
        "THEM: посмотрю и пришлю замечания к четвергу\n"
        "ME: спасибо тогда фиксируем эту версию"
    )
    result = dedupe_adjacent_repeats(text)
    assert result == text


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
