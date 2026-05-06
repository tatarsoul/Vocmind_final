from app.services.groq import _extract_first_json_object


def test_extracts_json_from_markdown_block():
    text = '```json\n{"action_items": []}\n```'
    assert _extract_first_json_object(text) == {"action_items": []}


def test_extracts_json_when_model_adds_text_around_it():
    text = 'Ответ: {"summary": "ok", "action_items": [{"task": "тест"}]} конец'
    assert _extract_first_json_object(text) == {
        "summary": "ok",
        "action_items": [{"task": "тест"}],
    }


def test_returns_none_for_non_json_text():
    assert _extract_first_json_object('это не json') is None
