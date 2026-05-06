"""Unit-тесты для новой логики валидации задач и нормализации жанра.

Цель: убедиться что после рефакторинга «обрывочные» задачи из реальных
жалоб пользователя больше не пропускаются в финальный протокол.
"""

from app.services.protocol import (
    _is_valid_action_task,
    _normalize_genre,
    _vote_genre,
    normalize_protocol_state,
    render_protocol_text,
)


# ---- _is_valid_action_task ------------------------------------------------

class TestIsValidActionTask:
    def test_real_garbage_from_user_report_is_rejected(self):
        """Те самые обрывки, что напарник прислал в логе."""
        garbage = [
            "Бонусы, плюшки и так",
            "Если руководители считают",
            "Но если нужно какое-то обучение там позиция такая что если человек пришел",
            "Интересно узнать какие результаты нужно добиться в первые 3-6-12 месяцев",
            "Я думаю что это тогда целесообразно уже с руководителем обсудить",
        ]
        for g in garbage:
            assert not _is_valid_action_task(g), f"должна была отвергнуться: {g!r}"

    def test_short_phrases_rejected(self):
        # < 5 слов
        assert not _is_valid_action_task("Сделать отчёт")
        assert not _is_valid_action_task("")
        assert not _is_valid_action_task("Подготовить")

    def test_questions_rejected(self):
        assert not _is_valid_action_task("Какие будут следующие шаги по проекту?")
        assert not _is_valid_action_task("Как мы будем тестировать новую фичу?")
        assert not _is_valid_action_task("Расскажите о компенсациях для сотрудников")

    def test_personal_opinions_rejected(self):
        assert not _is_valid_action_task("Я думаю надо подготовить отчёт по тестам")
        assert not _is_valid_action_task("Мне кажется надо переписать модуль авторизации")
        assert not _is_valid_action_task("Наверное нужно сделать новую страницу профиля")

    def test_dangling_tails_rejected(self):
        assert not _is_valid_action_task("Подготовить отчёт по тестам если")
        assert not _is_valid_action_task("Сделать новую страницу так чтобы")
        assert not _is_valid_action_task("Нужно подготовить макет и так")

    def test_real_tasks_accepted(self):
        """Эти строки — настоящие задачи, должны проходить."""
        good = [
            "Подготовить макет страницы регистрации к пятнице",
            "Написать раздел 3.4 про методику тестирования",
            "Проверить интеграцию с платёжным шлюзом",
            "Доработать модуль авторизации и протестировать его",
            "Согласовать ТЗ с заказчиком до конца недели",
            "Реализовать фильтрацию задач по статусу",
        ]
        for g in good:
            assert _is_valid_action_task(g), f"должна была пройти: {g!r}"


# ---- _normalize_genre / _vote_genre --------------------------------------

class TestGenreNormalization:
    def test_known_values_pass_through(self):
        assert _normalize_genre("work_meeting") == "work_meeting"
        assert _normalize_genre("interview") == "interview"
        assert _normalize_genre("podcast") == "podcast"
        assert _normalize_genre("lecture") == "lecture"
        assert _normalize_genre("other") == "other"

    def test_synonyms_resolved(self):
        assert _normalize_genre("собеседование") == "interview"
        assert _normalize_genre("Интервью") == "interview"
        assert _normalize_genre("подкаст") == "podcast"
        assert _normalize_genre("Лекция") == "lecture"
        assert _normalize_genre("встреча") == "work_meeting"

    def test_unknown_defaults_to_work_meeting(self):
        assert _normalize_genre(None) == "work_meeting"
        assert _normalize_genre("") == "work_meeting"
        assert _normalize_genre("гыгы") == "work_meeting"

    def test_vote_genre_majority_non_work_wins(self):
        # 3 голоса за interview, 1 за work_meeting → побеждает interview
        result = _vote_genre(["interview", "interview", "interview", "work_meeting"])
        assert result == "interview"

    def test_vote_genre_all_work_meeting(self):
        result = _vote_genre(["work_meeting", "work_meeting", "work_meeting"])
        assert result == "work_meeting"

    def test_vote_genre_empty(self):
        assert _vote_genre([]) == "work_meeting"


# ---- normalize_protocol_state for non-work genres ------------------------

class TestNormalizeForNonWorkGenre:
    def test_interview_clears_action_items(self):
        """На интервью даже если LLM по ошибке вернул задачи — мы их вычистим."""
        raw = {
            "genre": "interview",
            "summary": "Собеседование на позицию backend-разработчика.",
            "topics": ["Бонусы и компенсации", "Обучение сотрудников"],
            "key_points": [
                "Компания компенсирует обучение если оно полезно для команды",
                "Корпоративная культура включает поздравления и подарки",
            ],
            "action_items": [
                # эти все попали по ошибке — должны пропасть
                {"task": "Обсудить с руководителем результаты в первые 3-6-12 месяцев", "assignee": "Руководитель"},
                {"task": "Подготовить план развития сотрудника на год вперёд"},
            ],
            "decisions": ["Решили взять кандидата на испытательный срок"],
            "next_steps": ["После собеседования провести техническое интервью"],
            "ideas": [],
            "risks": [],
        }
        result = normalize_protocol_state(raw)
        assert result["genre"] == "interview"
        # для не-work_meeting задачи/решения/next_steps вычищаются
        assert result["action_items"] == []
        assert result["decisions"] == []
        assert result["next_steps"] == []
        # но summary/topics/key_points остаются
        assert result["summary"]
        assert len(result["topics"]) >= 1
        assert len(result["key_points"]) >= 1

    def test_work_meeting_keeps_valid_actions(self):
        raw = {
            "genre": "work_meeting",
            "summary": "Обсудили задачи по проекту",
            "action_items": [
                {"task": "Подготовить макет страницы регистрации к пятнице", "assignee": "Аня"},
                {"task": "Написать раздел 3.4 про методику тестирования"},
                # это должно отвалиться (мнение)
                {"task": "Я думаю надо переписать модуль"},
                # это тоже (обрывок)
                {"task": "Бонусы, плюшки и так"},
            ],
            "decisions": ["Решили использовать FastAPI для бэкенда"],
        }
        result = normalize_protocol_state(raw)
        assert result["genre"] == "work_meeting"
        assert len(result["action_items"]) == 2
        tasks = [a["task"] for a in result["action_items"]]
        assert any("макет" in t.lower() for t in tasks)
        assert any("раздел 3.4" in t.lower() for t in tasks)
        assert all("бонус" not in t.lower() for t in tasks)
        assert all("я думаю" not in t.lower() for t in tasks)

    def test_no_genre_defaults_to_work_meeting(self):
        """Обратная совместимость: если в state нет поля genre — work_meeting."""
        raw = {
            "summary": "Обсудили задачи",
            "action_items": [
                {"task": "Подготовить макет страницы регистрации к пятнице"},
            ],
        }
        result = normalize_protocol_state(raw)
        assert result["genre"] == "work_meeting"
        assert len(result["action_items"]) == 1

    def test_work_meeting_keeps_key_points(self):
        """Главный фикс: на work_meeting key_points сохраняются (не вычищаются).

        Это спасает короткие или обзорные встречи от пустого протокола: если
        задач и решений нет, но обсудили что-то полезное — пользователь
        получит хотя бы тезисы вместо «(Пока нет данных для сводки)».
        """
        raw = {
            "genre": "work_meeting",
            "summary": "Обзорная встреча по статусу проекта",
            "topics": ["Прогресс по релизу", "Состав команды"],
            "key_points": [
                "Команда выросла за полгода с трёх до восьми человек",
                "Запуск перенесли на конец квартала из-за интеграции с CRM",
                "Конверсия лендинга упала на 12 процентов после редизайна",
            ],
            "action_items": [],  # на обзорной встрече задач нет
            "decisions": [],
        }
        result = normalize_protocol_state(raw)
        assert result["genre"] == "work_meeting"
        # Главное: key_points сохранены, а не выброшены
        assert len(result["key_points"]) == 3
        assert any("команда" in kp.lower() for kp in result["key_points"])
        assert any("запуск" in kp.lower() for kp in result["key_points"])
        # Темы тоже на месте (≥ 2 слов каждая)
        assert len(result["topics"]) == 2

    def test_work_meeting_with_only_key_points_renders_correctly(self):
        """На обзорной встрече (только тезисы, без задач) — рендер должен
        быть содержательным, а не «нет данных для сводки»."""
        state = {
            "genre": "work_meeting",
            "summary": "Обзорная встреча по статусу проекта.",
            "topics": ["Релиз v1.0", "Команда"],
            "key_points": [
                "Команда выросла за полгода с трёх до восьми человек",
                "Запуск перенесли на конец квартала из-за интеграции с CRM",
            ],
            "action_items": [],
            "decisions": [],
        }
        text = render_protocol_text(state)
        assert "ПРОТОКОЛ ВСТРЕЧИ" in text
        # Главные тезисы должны отрисоваться
        assert "Главные тезисы" in text
        assert "Команда выросла" in text
        # Темы тоже
        assert "Темы" in text
        assert "Релиз v1.0" in text
        # И НЕ должно быть «нет данных»
        assert "Пока нет данных" not in text


# ---- render_protocol_text для всех жанров --------------------------------

class TestRenderProtocolText:
    def test_interview_shows_genre_hint_and_key_points(self):
        state = {
            "genre": "interview",
            "summary": "Собеседование на backend-разработчика.",
            "topics": ["Бонусы и компенсации", "Обучение сотрудников"],
            "key_points": [
                "Компания компенсирует обучение если руководитель посчитает его полезным",
                "Команда новая и ещё не сформирована полностью",
            ],
            "action_items": [],
            "decisions": [],
        }
        text = render_protocol_text(state)
        assert "ПРОТОКОЛ РАЗГОВОРА" in text
        assert "собеседование" in text.lower()
        assert "Главные тезисы" in text
        assert "Темы" in text
        assert "Задачи" not in text  # их нет на интервью
        assert "Решения" not in text

    def test_work_meeting_shows_actions(self):
        state = {
            "genre": "work_meeting",
            "summary": "Обсудили задачи проекта",
            "action_items": [
                {"task": "Подготовить макет страницы регистрации к пятнице", "assignee": "Аня", "due": "пятница"},
            ],
            "decisions": ["Решили использовать FastAPI для бэкенда"],
        }
        text = render_protocol_text(state)
        assert "ПРОТОКОЛ ВСТРЕЧИ" in text
        assert "Задачи:" in text
        assert "Решения:" in text
        assert "Аня" in text
        assert "пятница" in text

    def test_empty_state_returns_placeholder(self):
        text = render_protocol_text(None)
        assert "Пока нет данных" in text or "ПРОТОКОЛ" in text


if __name__ == "__main__":
    # Запуск без pytest — через простой обход классов
    import sys
    classes = [TestIsValidActionTask, TestGenreNormalization,
               TestNormalizeForNonWorkGenre, TestRenderProtocolText]
    failed = 0
    passed = 0
    for cls in classes:
        instance = cls()
        for name in dir(instance):
            if name.startswith("test_"):
                try:
                    getattr(instance, name)()
                    print(f"  ✅ {cls.__name__}.{name}")
                    passed += 1
                except AssertionError as e:
                    print(f"  ❌ {cls.__name__}.{name}: {e}")
                    failed += 1
                except Exception as e:
                    print(f"  💥 {cls.__name__}.{name}: {type(e).__name__}: {e}")
                    failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
