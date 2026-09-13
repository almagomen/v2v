"""
Modelos Pydantic para la API REST de V2V.
Define los esquemas de request/response para todos los endpoints.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    TRANSLATING = "translating"
    CLONING = "cloning"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Request Models ─────────────────────────────────────────────────────

class ProcessRequest(BaseModel):
    """Request para iniciar el pipeline de procesamiento."""
    urls: list[str] = Field(..., min_length=1, description="URLs de YouTube a procesar")
    translate_lang: Optional[str] = Field(None, description="Idioma de traducción (es, en, pt, fr, de, it) o None")
    speaker: str = Field("mrbeast", description="Nombre del speaker/voz a usar")

    model_config = {"json_schema_extra": {
        "example": {
            "urls": ["https://www.youtube.com/watch?v=example"],
            "translate_lang": "es",
            "speaker": "mrbeast",
        }
    }}


# ── Response Models ────────────────────────────────────────────────────

class JobResponse(BaseModel):
    """Respuesta al crear un job de procesamiento."""
    job_id: str
    status: JobStatus
    message: str


class JobStatusResponse(BaseModel):
    """Estado actual de un job."""
    job_id: str
    status: JobStatus
    progress: float = Field(0.0, ge=0.0, le=1.0)
    current_step: str = ""
    logs: list[str] = []
    results: list["ProjectSummary"] = []
    error: Optional[str] = None


class ProjectSummary(BaseModel):
    """Resumen de un proyecto procesado."""
    id: str
    name: str
    url: str
    video_path: Optional[str] = None
    has_video: bool = False
    segment_count: int = 0
    src_lang: Optional[str] = None
    cached: bool = False


class SegmentInfo(BaseModel):
    """Información de un segmento de texto/audio."""
    index: int
    start: float
    end: float
    text: str
    speaker: Optional[str] = None


class ProjectDetail(BaseModel):
    """Detalle completo de un proyecto."""
    id: str
    name: str
    url: str
    segments: list[SegmentInfo] = []
    files: dict[str, str] = Field(default_factory=dict, description="Mapa nombre -> ruta relativa de archivos")
    src_lang: Optional[str] = None


class HealthResponse(BaseModel):
    """Respuesta del health check."""
    status: str = "ok"
    gpu_available: bool = False
    device: str = "cpu"


# Resolver forward refs
JobStatusResponse.model_rebuild()
