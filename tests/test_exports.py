"""Тесты для build_export_sections — формирование секций docx/pdf экспорта.

Цель: убедиться, что:
1. Если есть готовый protocol_text — отдельные секции из protocol_json не дублируются
2. Поле topics НЕ подставляется в Идеи (старый баг)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Прямой импорт — модуль чистый, без FastAPI зависимостей
from app.services.exports import build_export_sections


def test_with_protocol_text_no_duplicate_sections():
    """Если есть protocol_text — отдельные блоки Кратко/Темы/Идеи не выводятся."""
    meeting = {
        "title": "Test meeting",
        "status": "done",
        "protocol_text": "🧾 ПРОТОКОЛ ВСТРЕЧИ\n\nКратко:\nТест\n\nТемы:\n- Тестирование\n\nГлавные тезисы:\n- Тезис один тут",
        "protocol_json": {
            "summary": "Тест",
            "topics": ["Тестирование"],
            "key_points": ["Тезис один тут"],
            "ideas": [],
            "decisions": [],
            "action_items": [],
            "risks": [],
            "next_steps": [],
        },
    }
    sections = build_export_sections(meeting)
    section_names = [name for name, _ in sections]

    # Должна быть ровно одна секция «Протокол»
    assert section_names.count("Протокол") == 1
    # И НЕ должно быть отдельных «Кратко», «Темы», «Идеи» (т.к. они уже внутри protocol_text)
    assert "Кратко" not in section_names
    assert "Темы" not in section_names
    assert "Идеи" not in section_names
    assert "Главные тезисы" not in section_names


def test_topics_do_not_leak_into_ideas():
    """Старый баг: если ideas пуст, в раздел Идеи подставлялись topics.
    Теперь так делаться не должно."""
    meeting = {
        "title": "Test meeting",
        "status": "done",
        "protocol_text": "",  # нет готового текста — fallback на JSON-секции
        "protocol_json": {
            "summary": "Обсудили работу",
            "topics": ["Корпоративная культура", "Бонусы и компенсации"],
            "key_points": [],
            "ideas": [],  # пусто!
            "decisions": [],
            "action_items": [],
            "risks": [],
            "next_steps": [],
        },
    }
    sections = build_export_sections(meeting)
    section_names = [name for name, _ in sections]

    # Темы должны выводиться отдельной секцией
    assert "Темы" in section_names
    # Идей не должно быть, потому что в JSON их нет
    assert "Идеи" not in section_names

    # Дополнительная проверка: содержимое Тем — это именно topics
    topics_content = next(content for name, content in sections if name == "Темы")
    assert "Корпоративная культура" in topics_content
    assert "Бонусы и компенсации" in topics_content


def test_fallback_renders_full_protocol_when_no_text():
    """Если protocol_text пуст, должны выводиться все секции из JSON."""
    meeting = {
        "title": "Test",
        "protocol_text": "",
        "protocol_json": {
            "summary": "Обсудили задачи",
            "topics": ["Релиз", "Тестирование"],
            "key_points": ["Команда выросла на трёх человек за квартал"],
            "ideas": ["Попробовать новую систему мониторинга команды"],
            "decisions": ["Решили перенести релиз на следующий понедельник"],
            "action_items": [
                {"task": "Подготовить релизные ноты к пятнице вечером", "assignee": "Аня"}
            ],
            "risks": ["Возможна задержка из-за интеграции с CRM"],
            "next_steps": ["После релиза провести ретроспективу всей команды"],
        },
    }
    sections = build_export_sections(meeting)
    section_names = [name for name, _ in sections]

    assert "Кратко" in section_names
    assert "Темы" in section_names
    assert "Главные тезисы" in section_names
    assert "Решения" in section_names
    assert "Задачи" in section_names
    assert "Идеи" in section_names
    assert "Риски" in section_names
    assert "Следующие шаги" in section_names


def test_no_protocol_text_and_empty_json():
    """Полностью пустой protocol — секции протокола вообще не выводятся."""
    meeting = {
        "title": "Empty meeting",
        "protocol_text": "",
        "protocol_json": {},
    }
    sections = build_export_sections(meeting)
    section_names = [name for name, _ in sections]

    assert "Протокол" not in section_names
    assert "Кратко" not in section_names


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
