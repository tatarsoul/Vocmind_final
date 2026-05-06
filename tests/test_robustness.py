from app.services.protocol import protocol_from_transcript


def test_handles_empty_input():
    result = protocol_from_transcript("")
    assert isinstance(result, dict)


def test_handles_noise_input():
    transcript = "эээ ну типа короче вот как бы значит"
    result = protocol_from_transcript(transcript)

    assert "action_items" in result
    assert "decisions" in result


def test_handles_mixed_language():
    transcript = """
    ME: Нужно сделать report и добавить dashboard.
    THEM: Решили использовать API для integration.
    """

    result = protocol_from_transcript(transcript)

    combined = " ".join(
        [item["task"].lower() for item in result["action_items"]]
        + [item.lower() for item in result["decisions"]]
    )

    assert "report" in combined or "dashboard" in combined
    assert "api" in combined