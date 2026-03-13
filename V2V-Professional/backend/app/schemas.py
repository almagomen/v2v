from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# Project Schemas
class ProjectCreate(BaseModel):
    url: str
    translate_lang: Optional[str] = None
    speaker_id: str = "mrbeast_lmnt"


class ProjectUpdate(BaseModel):
    status: Optional[str] = None
    video_path: Optional[str] = None


class VideoClipBase(BaseModel):
    start_original: float
    end_original: float
    start_timeline: float
    end_timeline: float
    track_index: int = 0
    order: int = 0


class VideoClipCreate(VideoClipBase):
    project_id: str


class VideoClipUpdate(BaseModel):
    start_timeline: Optional[float] = None
    end_timeline: Optional[float] = None
    order: Optional[int] = None


class VideoClipResponse(VideoClipBase):
    id: str
    project_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class AudioSegmentBase(BaseModel):
    text: str
    speaker_id: str = "SPEAKER_00"
    start_timeline: float
    end_timeline: float
    start_original: float
    end_original: float
    track_index: int = 1
    order: int = 0


class AudioSegmentCreate(AudioSegmentBase):
    project_id: str


class AudioSegmentUpdate(BaseModel):
    text: Optional[str] = None
    speaker_id: Optional[str] = None
    start_timeline: Optional[float] = None
    end_timeline: Optional[float] = None
    order: Optional[int] = None
    is_dirty: Optional[bool] = None


class AudioSegmentResponse(AudioSegmentBase):
    id: str
    project_id: str
    audio_path: Optional[str] = None
    audio_url: Optional[str] = None
    is_dirty: bool = False
    is_generated: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class ProjectResponse(BaseModel):
    id: str
    url: str
    output_name: str
    status: str
    video_path: Optional[str] = None
    vocals_path: Optional[str] = None
    no_vocals_path: Optional[str] = None
    source_language: Optional[str] = None
    video_clips: list[VideoClipResponse] = []
    audio_segments: list[AudioSegmentResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Timeline Schemas
class TimelineExportRequest(BaseModel):
    video_clips: list[VideoClipBase]
    audio_segments: list[AudioSegmentBase]


class RenderProgress(BaseModel):
    progress: float
    message: str
    stage: str


class LogMessage(BaseModel):
    message: str
    level: str = "info"
