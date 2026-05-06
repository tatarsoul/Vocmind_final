from app.services.protocol import protocol_from_transcript


def test_protocol_has_all_fields():
    transcript = "Нужно сделать отчёт"

    result = protocol_from_transcript(transcript)

    required_fields = [
        "summary",
        "topics",
        "decisions",
        "action_items",
        "ideas",
        "risks",
        "next_steps",
        "notes",
    ]

    for field in required_fields:
        assert field in result


def test_action_items_structure():
    transcript = "Нужно подготовить презентацию"

    result = protocol_from_transcript(transcript)

    for item in result["action_items"]:
        assert "task" in item
        assert "assignee" in item
        assert "due" in item