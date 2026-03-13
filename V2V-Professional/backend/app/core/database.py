from sqlmodel import SQLModel, create_engine, Session, Field
from typing import Optional
from datetime import datetime
from enum import Enum

from app.core.config import settings


engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=settings.DEBUG,
)


class ProjectStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: Optional[str] = Field(default=None, primary_key=True)
    url: str
    output_name: str
    status: ProjectStatus = ProjectStatus.PENDING
    video_path: Optional[str] = None
    vocals_path: Optional[str] = None
    no_vocals_path: Optional[str] = None
    source_language: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class VideoClip(SQLModel, table=True):
    __tablename__ = "video_clips"

    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="projects.id")

    # Original times (from source video)
    start_original: float
    end_original: float

    # Timeline times (where clip appears in final edit)
    start_timeline: float = 0
    end_timeline: float = 0

    # Track info
    track_index: int = 0
    order: int = 0

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AudioSegment(SQLModel, table=True):
    __tablename__ = "audio_segments"

    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="projects.id")

    # Text content
    text: str
    speaker_id: str = "SPEAKER_00"

    # Timeline times
    start_timeline: float
    end_timeline: float

    # Original times (from transcription)
    start_original: float
    end_original: float

    # Audio file
    audio_path: Optional[str] = None
    audio_url: Optional[str] = None

    # Status
    is_dirty: bool = False
    is_generated: bool = False

    # Track info
    track_index: int = 1
    order: int = 0

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
