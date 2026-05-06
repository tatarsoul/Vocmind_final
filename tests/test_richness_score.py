"""Тесты для логики выбора более содержательного протокола между
live-регенерацией и финальной регенерацией.

Цель: убедиться, что когда финальная регенерация падает (rate limit и т.п.)
и возвращает пустоту, мы оставляем хороший live-state, а не перезаписываем
его пустотой.
"""
import sys
import types

sys.modules["app"] = types.ModuleType("app")

fake_config = types.ModuleType("app.config")
class FS:
    groq_api_key = ""
    groq_model = "llama"
    groq_timeout_seconds = 20.0
    asr_language = "ru"
    asr_window_seconds = 14.0
    asr_min_audio_seconds = 0.9
    audio_sample_rate = 16000
    buffer_max_seconds = 120
    vad_min_silence_ms = 600
    audio_channels = 1
    ffmpeg_path = ""
fake_config.settings = FS()
fake_config.Settings = FS
sys.modules["app.config"] = fake_config
sys.modules["app.services"] = types.ModuleType("app.services")

fake_groq = types.ModuleType("app.services.groq")
async def fgcj(*a, **kw): return {}
fake_groq.groq_chat_json = fgcj
sys.modules["app.services.groq"] = fake_groq

import importlib.util
spec = importlib.util.spec_from_file_location("app.services.protocol", "app/services/protocol.py")
m = importlib.util.module_from_spec(spec)
sys.modules["app.services.protocol"] = m
spec.loader.exec_module(m)

normalize_protocol_state = m.normalize_protocol_state


# Воспроизведём _protocol_richness_score локально (он живёт в main.py с
# зависимостью на FastAPI). Логика идентичная — копируем как есть.
def _protocol_richness_score(state):
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


def test_empty_state_score_is_zero():
    assert _protocol_richness_score(None) == 0
    assert _protocol_richness_score({}) == 0
    assert _protocol_richness_score({"summary": None, "action_items": []}) == 0


def test_summary_only_has_score_3():
    assert _protocol_richness_score({"summary": "Обсудили задачи проекта"}) == 3


def test_key_points_score():
    """key_points стоят 2 очка каждый — это самый важный сигнал
    содержательности на не-рабочих жанрах."""
    state = {
        "key_points": [
            "Команда выросла за полгода с трёх до восьми человек",
            "Запуск перенесли на конец квартала из-за интеграции с CRM",
        ],
    }
    assert _protocol_richness_score(state) == 4  # 2 * 2 очка


def test_real_user_scenario_live_vs_empty_final():
    """Воспроизводим точно что произошло на тесте напарника:
    live вернула 2 key_points + summary, final-regenerate упала на 429
    и вернула пустоту. Live должен победить."""
    live_state = {
        "genre": "work_meeting",
        "summary": "Кандидат рассказал про опыт работы в онлайн-школе и систематизацию процессов.",
        "topics": ["Опыт работы", "Состав команды"],
        "key_points": [
            "Кандидат систематизировал процессы в онлайн-школе с нуля",
            "В 2023 году был достигнут рекорд по выручке и росту продукта",
        ],
        "action_items": [],
        "decisions": [],
    }
    final_empty_state = {
        "genre": "work_meeting",
        "summary": None,
        "topics": [],
        "key_points": [],
        "action_items": [],
        "decisions": [],
    }
    live_score = _protocol_richness_score(live_state)
    final_score = _protocol_richness_score(final_empty_state)

    assert live_score > 0
    assert final_score == 0
    assert live_score > final_score, (
        "Live-state должен быть значительно содержательнее пустого final"
    )
    print(f"  live_score={live_score} final_score={final_score} ← live побеждает")


def test_real_meeting_with_actions_beats_live_with_only_keypoints():
    """Если на финальной регенерации Llama смогла вытащить настоящие
    задачи и решения — final победит даже если live был с key_points."""
    live_state = {
        "genre": "work_meeting",
        "summary": None,
        "key_points": ["Команда обсуждала статус релиза"],
        "action_items": [],
        "decisions": [],
    }
    final_state = {
        "genre": "work_meeting",
        "summary": "Обсудили задачи проекта",
        "topics": ["Релиз", "Тестирование"],
        "key_points": [
            "Релиз перенесён на конец недели",
            "Команда требует дополнительный QA-инженер",
        ],
        "action_items": [
            {"task": "Подготовить релизные ноты к пятнице", "assignee": "Аня"},
            {"task": "Согласовать ТЗ с заказчиком до конца недели"},
        ],
        "decisions": ["Решили использовать FastAPI для бэкенда"],
    }
    live_score = _protocol_richness_score(live_state)
    final_score = _protocol_richness_score(final_state)
    assert final_score > live_score


def test_action_items_with_empty_task_dont_count():
    state = {
        "action_items": [
            {"task": ""},
            {"task": None},
            {"task": "  "},
        ]
    }
    assert _protocol_richness_score(state) == 0


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
