import re
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs


@dataclass
class ParsedMeetingLink:
    platform: str            # zoom/teams/meet/unknown
    meeting_id: str | None
    meeting_uuid: str | None
    normalized_url: str


_ZOOM_HOST_RE = re.compile(r"(^|\.)zoom\.us$", re.IGNORECASE)
_TEAMS_HOST_RE = re.compile(r"(^|\.)microsoft\.com$", re.IGNORECASE)
_MEET_HOST_RE = re.compile(r"(^|\.)google\.com$", re.IGNORECASE)


def parse_meeting_link(url: str) -> ParsedMeetingLink:
    url = url.strip()
    p = urlparse(url)
    host = (p.hostname or "").lower()
    path = p.path or ""
    qs = parse_qs(p.query)

    # --- Zoom ---
    # примеры:
    # https://us02web.zoom.us/j/123456789?pwd=...
    # https://zoom.us/j/123456789
    if _ZOOM_HOST_RE.search(host):
        # ищем /j/{digits}
        m = re.search(r"/j/(\d+)", path)
        meeting_id = m.group(1) if m else None
        return ParsedMeetingLink(platform="zoom", meeting_id=meeting_id, meeting_uuid=None, normalized_url=url)

    # --- Google Meet ---
    # пример:
    # https://meet.google.com/abc-defg-hij
    if host == "meet.google.com" or (_MEET_HOST_RE.search(host) and "meet.google.com" in host):
        m = re.search(r"/([a-z]{3}-[a-z]{4}-[a-z]{3})", path, re.IGNORECASE)
        meeting_id = m.group(1).lower() if m else None
        return ParsedMeetingLink(platform="meet", meeting_id=meeting_id, meeting_uuid=None, normalized_url=url)

    # --- Microsoft Teams ---
    # пример:
    # https://teams.microsoft.com/l/meetup-join/19%3ameeting_.../0?context=...
    # meeting_id может быть частью path или параметров
    if "teams.microsoft.com" in host:
        # попробуем вытащить "meetup-join/..." как meeting_id
        m = re.search(r"/l/meetup-join/([^/]+)", path, re.IGNORECASE)
        meeting_id = m.group(1) if m else None
        return ParsedMeetingLink(platform="teams", meeting_id=meeting_id, meeting_uuid=None, normalized_url=url)

    return ParsedMeetingLink(platform="unknown", meeting_id=None, meeting_uuid=None, normalized_url=url)
