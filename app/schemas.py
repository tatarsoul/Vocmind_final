from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Literal


class IngestLinkRequest(BaseModel):
    url: str = Field(..., description="Ссылка на встречу (Zoom/Teams/Meet)")
    user_id: Optional[str] = Field(None, description="ID пользователя (если есть)")
    organizer_email: Optional[str] = None


class IngestLinkResponse(BaseModel):
    job_id: str
    platform: Literal["zoom", "teams", "meet", "unknown"]
    meeting_id: Optional[str] = None
    meeting_uuid: Optional[str] = None
    status: str


class ZoomRecordingCompletedIn(BaseModel):
    # То, что будет присылать n8n в ваш backend (мы сами зададим контракт)
    job_id: Optional[str] = None
    meeting_uuid: Optional[str] = None
    meeting_id: Optional[str] = None

    # ссылки на артефакты
    transcript_url: Optional[str] = None
    recording_url: Optional[str] = None

    # мета
    topic: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class BasicJobOut(BaseModel):
    job_id: str
    platform: str
    status: str
    transcript_preview: Optional[str] = None
    protocol_preview: Optional[str] = None


class UploadTranscriptVttIn(BaseModel):
    job_id: str
    vtt: str

class GenerateProtocolIn(BaseModel):
    model: str | None = None  # например "vocmind-saiga12b"
