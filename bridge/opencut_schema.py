"""
Definición de modelos de datos del proyecto OpenCut para exportación/importación.
Compatibles con la estructura interna de OpenCut (Zustand store / IndexedDB).
"""
from typing import Any, Optional
from pydantic import BaseModel, Field


class OpenCutCanvasSize(BaseModel):
    width: int = 1920
    height: int = 1080


class OpenCutBackground(BaseModel):
    type: str = "color"
    color: str = "#000000"


class OpenCutProjectSettings(BaseModel):
    fps: int = 30
    canvasSize: OpenCutCanvasSize = Field(default_factory=OpenCutCanvasSize)
    canvasSizeMode: str = "preset"
    background: OpenCutBackground = Field(default_factory=OpenCutBackground)


class OpenCutMetadata(BaseModel):
    id: str
    name: str
    duration: float = 0.0
    createdAt: str
    updatedAt: str
    thumbnail: Optional[str] = None


class OpenCutMediaAsset(BaseModel):
    id: str
    name: str
    type: str  # "video" | "audio" | "image"
    url: str
    duration: float = 0.0
    width: Optional[int] = None
    height: Optional[int] = None


class OpenCutTimelineElement(BaseModel):
    id: str
    mediaId: Optional[str] = None
    name: str
    type: str  # "video" | "audio" | "text"
    startTime: float  # Tiempo en el timeline (segundos)
    duration: float   # Duración en segundos
    trimStart: float = 0.0
    trimEnd: float = 0.0
    volume: float = 1.0
    muted: bool = False
    text: Optional[str] = None  # Para elementos de tipo text / subtítulos
    properties: dict[str, Any] = Field(default_factory=dict)


class OpenCutTrack(BaseModel):
    id: str
    name: str
    type: str  # "video" | "audio" | "text"
    muted: bool = False
    locked: bool = False
    visible: bool = True
    elements: list[OpenCutTimelineElement] = Field(default_factory=list)


class OpenCutScene(BaseModel):
    id: str
    name: str = "Main scene"
    isMain: bool = True
    tracks: list[OpenCutTrack] = Field(default_factory=list)


class OpenCutProject(BaseModel):
    version: int = 1
    metadata: OpenCutMetadata
    settings: OpenCutProjectSettings = Field(default_factory=OpenCutProjectSettings)
    scenes: list[OpenCutScene] = Field(default_factory=list)
    mediaAssets: list[OpenCutMediaAsset] = Field(default_factory=list)
