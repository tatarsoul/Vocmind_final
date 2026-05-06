import re

_TS_LINE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s-->\s\d{2}:\d{2}:\d{2}\.\d{3}")
_TAGS = re.compile(r"<[^>]+>")  # простая чистка <c>...</c> и т.п.


def vtt_to_text(vtt: str) -> str:
    """
    Очень простой VTT -> plain text:
    - убираем WEBVTT, индексы, таймкоды
    - убираем html-теги
    - склеиваем строки
    """
    lines = []
    for raw in vtt.splitlines():
        line = raw.strip()

        if not line:
            continue
        if line.upper().startswith("WEBVTT"):
            continue
        if _TS_LINE.match(line):
            continue
        if line.isdigit():  # cue index
            continue

        line = _TAGS.sub("", line).strip()
        if line:
            lines.append(line)

    text = " ".join(lines)
    # чуть нормализуем пробелы
    text = re.sub(r"\s+", " ", text).strip()
    return text
