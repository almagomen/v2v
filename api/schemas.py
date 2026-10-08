"""Pydantic schemas for v2v API."""

from pydantic import BaseModel, Field, model_validator
from typing import Optional, Any, Literal


class ProcessUrlsRequest(BaseModel):
    urls: list[str] = Field(..., description="URLs de YouTube (una o más)")
    translate_lang: Optional[str] = Field(
        None, description="Idioma de traducción: es, pt, en, fr, de, it, o null"
    )
    speaker: str = Field("mrbeast", description="Nombre de voz/speaker")
    emotion: Optional[str] = Field(
        None, description="Emoción inicial opcional para anteponer a los segmentos (ej: [excited])"
    )
    force_reprocess: Optional[bool] = Field(
        False, description="Forzar re-inferencia sin usar caché existente creando nueva versión de proyecto"
    )


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
    video_only_path: str = ""
    instrumental_path: str = ""
    original_audio_path: str = ""
    vocals_path: str = ""
    segments: list[SegmentSchema]
    url: str


class JobResultResponse(BaseModel):
    job_id: str
    status: str = "done"
    videos: list[VideoResult]
    log: Optional[str] = None


class RegenerateSegmentRequest(BaseModel):
    job_id: Optional[str] = Field(
        None, description="ID del job (si se usa con video_index)"
    )
    video_index: int = Field(0, description="Índice del video en el job")
    video_path: Optional[str] = Field(
        None, description="Path del video (alternativa a job_id)"
    )
    seg_idx: int = Field(..., ge=1)
    text: str
    start: float
    end: float
    translate_lang: Optional[str] = None
    speaker: str = "mrbeast"
    speed: float = Field(1.0, description="Factor de velocidad (0.5 a 2.0)")
    target_duration: Optional[float] = Field(
        None, description="Duración objetivo en segundos para modo 's'"
    )
    temperature: float = Field(0.7, ge=0.1, le=1.0, description="Fish Audio expresividad")
    top_p: float = Field(0.7, ge=0.1, le=1.0, description="Fish Audio diversidad sampling")
    repetition_penalty: float = Field(1.2, ge=1.0, le=2.0, description="Fish Audio control de repetición")
    volume: float = Field(0.0, ge=-10.0, le=10.0, description="Fish Audio ajuste volumen en dB")


class RegenerateVideoRequest(BaseModel):
    job_id: str = Field(..., description="ID del job")
    video_index: int = Field(0, description="Índice del video en el job")
    segments: list[SegmentSchema]
    translate_lang: Optional[str] = None
    speaker: str = "mrbeast"


class ApplySpeedRequest(BaseModel):
    job_id: Optional[str] = Field(None, description="ID del job")
    video_index: int = Field(0, description="Índice del video en el job")
    seg_idx: int = Field(..., ge=1)
    speed: Optional[float] = Field(None, description="Factor de velocidad")
    target_duration: Optional[float] = Field(None, description="Duración objetivo en segundos")


class GenerateAudioSegmentRequest(BaseModel):
    job_id: Optional[str] = Field(None, description="ID del job")
    video_index: int = Field(0, description="Índice del video en el job")
    video_path: Optional[str] = Field(None, description="Ruta directa al video (alternativa a job_id)")
    text: str = Field(..., description="Texto a sintetizar")
    speaker: str = Field("mrbeast", description="Clave o ID del hablante")
    start: Optional[float] = Field(0.0, description="Timestamp de inicio sugerido en segundos")
    speed: Optional[float] = Field(1.0, ge=0.2, le=3.0, description="Factor de velocidad")
    temperature: float = Field(0.7, ge=0.1, le=1.0, description="Fish Audio expresividad")
    top_p: float = Field(0.7, ge=0.1, le=1.0, description="Fish Audio diversidad sampling")
    repetition_penalty: float = Field(1.2, ge=1.0, le=2.0, description="Fish Audio control de repetición")
    volume: float = Field(0.0, ge=-10.0, le=10.0, description="Fish Audio ajuste volumen en dB")


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


class SegmentEditorRow(BaseModel):
    seg: int
    start: float
    end: float
    slot_duration: float
    original_text: str
    tts_text: str
    speaker: Optional[str] = None
    filename: Optional[str] = None


class SegmentsEditorResponse(BaseModel):
    job_id: str
    video_index: int
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    segments: list[SegmentEditorRow]


class RetranslateSegmentsRequest(BaseModel):
    job_id: str
    video_index: int = 0
    seg_indices: list[int] = Field(..., min_length=1)
    target_lang: Optional[str] = None
    custom_texts: Optional[dict[str, str]] = None


class RetranslateSegmentItem(BaseModel):
    seg: int
    text: str


class RetranslateSegmentsResponse(BaseModel):
    segments: list[RetranslateSegmentItem]


class TokenSettingsRequest(BaseModel):
    fish_api_key: Optional[str] = Field(None, description="Nuevo valor para FISH_API_KEY")
    google_api_key: Optional[str] = Field(None, description="Nuevo valor para GOOGLE_API_KEY")
    title_model: Optional[str] = Field(None, description="Modelo de Gemini por defecto para títulos virales")
    translation_model: Optional[str] = Field(None, description="Modelo de Gemini por defecto para traducción")


class TokenSettingsResponse(BaseModel):
    fish_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    title_model: Optional[str] = None
    translation_model: Optional[str] = None
    available_models: list[str] = Field(default_factory=list)
    message: str = "Configuración actualizada exitosamente"


class RegenerateTitleRequest(BaseModel):
    job_id: Optional[str] = None
    video_index: int = 0
    folder_name: Optional[str] = None
    model_name: Optional[str] = None
    custom_title: Optional[str] = None
    target_lang: Optional[str] = "es"


class RegenerateTitleResponse(BaseModel):
    status: str
    output_name: str
    model_used: Optional[str] = None
    message: Optional[str] = None


class GeminiModelsResponse(BaseModel):
    default_model: str
    models: list[str]


class SetDefaultGeminiModelRequest(BaseModel):
    model_name: str

