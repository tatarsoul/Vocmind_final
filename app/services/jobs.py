import json
import uuid
from sqlalchemy.orm import Session

from ..models import MeetingJob, Platform, JobStatus
from ..platform_parsers import parse_meeting_link


def create_job_from_link(db: Session, url: str, organizer_email: str | None, raw_payload: dict | None = None) -> MeetingJob:
    parsed = parse_meeting_link(url)

    job = MeetingJob(
        id=str(uuid.uuid4()),
        platform=Platform(parsed.platform) if parsed.platform in {"zoom", "teams", "meet"} else Platform.unknown,
        source_url=parsed.normalized_url,
        meeting_id=parsed.meeting_id,
        meeting_uuid=parsed.meeting_uuid,
        organizer_email=organizer_email,
        status=JobStatus.awaiting_artifacts if parsed.platform != "unknown" else JobStatus.created,
        raw_payload=json.dumps(raw_payload, ensure_ascii=False) if raw_payload else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
