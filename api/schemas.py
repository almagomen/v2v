"""Pydantic schemas for v2v API."""
from pydantic import BaseModel, Field, model_validator
from typing import Optional, Any


class ProcessUrlsRequest(BaseModel):
    urls: list[str] = Field(..., description="URLs de YouTube (una o más)")
    translate_lang: Optional[str] = Field(None, description="Idioma de traducción: es, pt, en, fr, de, it, o null")
    speaker: str = Field("mrbeast_lmnt", description="Nombre de voz/speaker")


class ProcessUrlsResponse(BaseModel):
    job_id: str
    message: str = "Procesamiento iniciado"


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # pending, downloading, transcribing, tts, rendering, done, error
    message: Optional[str] = None
    progress: float = 0.0


class SegmentSchema(BaseModel):
    seg: int
    start: float
    end: float
    text: str
    speaker: Optional[str] = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def normalize_columns(cls, v: Any) -> Any:
        if isinstance(v, dict):
            seg = v.get("seg") or v.get("Seg")
            start = v.get("start") or v.get("Inicio")
            end = v.get("end") or v.get("Final")
            text = v.get("text") or v.get("Texto")
            return {
                "seg": int(seg) if seg is not None else 0,
                "start": float(start) if start is not None else 0.0,
                "end": float(end) if end is not None else 0.0,
                "text": str(text) if text is not None else "",
                "speaker": v.get("speaker"),
            }
        return v


class VideoResult(BaseModel):
    index: int
    output_name: str
    video_path: str
    video_only_path: Optional[str] = None
    output_video_path: str
    output_filename: str = ""  # e.g. "output_name.mp4" for file serving
    segments: list[SegmentSchema]
    url: str


class JobResultResponse(BaseModel):
    job_id: str
    status: str = "done"
    videos: list[VideoResult]
    log: Optional[str] = None


class RegenerateSegmentRequest(BaseModel):
    job_id: Optional[str] = Field(None, description="ID del job (si se usa con video_index)")
    video_index: int = Field(0, description="Índice del video en el job")
    video_path: Optional[str] = Field(None, description="Path del video (alternativa a job_id)")
    seg_idx: int = Field(..., ge=1)
    text: str
    start: float
    end: float
    translate_lang: Optional[str] = None
    speaker: str = "mrbeast_lmnt"


class RegenerateVideoRequest(BaseModel):
    job_id: str = Field(..., description="ID del job")
    video_index: int = Field(0, description="Índice del video en el job")
    segments: list[SegmentSchema]
    translate_lang: Optional[str] = None
    speaker: str = "mrbeast_lmnt"


class SpeakerOption(BaseModel):
    label: str
    value: str


class TranscribeSegmentSchema(BaseModel):
    start: float
    end: float
    text: str
    speaker: Optional[str] = None


class TranscribeAudioResponse(BaseModel):
    segments: list[TranscribeSegmentSchema]
    language: Optional[str] = None


class JobPollResponse(BaseModel):
    job_id: str
    status: JobStatusResponse
    log: str = ""
    items: list[dict] = []
    result: Optional[JobResultResponse] = None
