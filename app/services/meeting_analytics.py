from __future__ import annotations

import re
from collections import Counter
from typing import Any


STOP_WORDS = {
    "и", "в", "на", "с", "по", "что", "это", "как", "а", "но", "не", "мы", "я",
    "ты", "он", "она", "они", "у", "к", "из", "за", "до", "от", "или", "же", "ли",
    "для", "по", "так", "вот", "ну", "да", "нет", "еще", "ещё", "уже", "только",
}


def _split_words(text: str) -> list[str]:
    return re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", text or "")



def build_meeting_analytics(transcript_text: str, protocol: dict[str, Any] | None = None) -> dict[str, Any]:
    transcript_text = transcript_text or ""
    protocol = protocol or {}

    lines = [line.strip() for line in transcript_text.splitlines() if line.strip()]
    me_words = 0
    them_words = 0
    turns_me = 0
    turns_them = 0
    plain_lines: list[str] = []

    for line in lines:
        upper = line.upper()
        if upper.startswith("ME:"):
            body = line[3:].strip()
            turns_me += 1
            me_words += len(_split_words(body))
            plain_lines.append(body)
        elif upper.startswith("THEM:"):
            body = line[5:].strip()
            turns_them += 1
            them_words += len(_split_words(body))
            plain_lines.append(body)
        elif line.startswith("==="):
            continue
        else:
            plain_lines.append(line)

    plain_text = " ".join(plain_lines).strip()
    words = _split_words(plain_text)
    questions_count = plain_text.count("?")

    freq = Counter(w.lower() for w in words if len(w) > 3 and w.lower() not in STOP_WORDS)
    top_keywords = [w for w, _ in freq.most_common(8)]

    total_speaker_words = me_words + them_words
    me_share = round((me_words / total_speaker_words) * 100, 1) if total_speaker_words else None
    them_share = round((them_words / total_speaker_words) * 100, 1) if total_speaker_words else None

    action_items = protocol.get("action_items") if isinstance(protocol, dict) else []
    decisions = protocol.get("decisions") if isinstance(protocol, dict) else []
    risks = protocol.get("risks") if isinstance(protocol, dict) else []
    topics = protocol.get("topics") if isinstance(protocol, dict) else []

    return {
        "speakers_detected": int((1 if me_words or turns_me else 0) + (1 if them_words or turns_them else 0)),
        "turns": {
            "me": turns_me,
            "them": turns_them,
        },
        "word_count": len(words),
        "questions_count": questions_count,
        "top_keywords": top_keywords,
        "talk_balance": {
            "me_percent": me_share,
            "them_percent": them_share,
        },
        "topics_count": len([x for x in topics if str(x).strip()]),
        "decisions_count": len([x for x in decisions if str(x).strip()]),
        "action_items_count": len([x for x in action_items if isinstance(x, dict) and str(x.get("task") or "").strip()]),
        "risks_count": len([x for x in risks if str(x).strip()]),
        "topics": topics,
    }
