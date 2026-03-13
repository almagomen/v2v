import io
import contextlib
import os
from pathlib import Path
from typing import Optional
import stable_whisper
import torch
import torchaudio


class STTService:
    """Servicio de transcripción y diarización."""

    _whisper_model = None
    _diarization_model = None

    @classmethod
    def get_whisper_model(cls, device: str = "cuda"):
        """Obtiene el modelo de Whisper (cacheado)."""
        if cls._whisper_model is None:
            cls._whisper_model = stable_whisper.load_model("turbo", device=device)
        return cls._whisper_model

    @classmethod
    def get_diarization_model(cls):
        """Obtiene el modelo de diarización (cacheado)."""
        if cls._diarization_model is None:
            from pyannote.audio import Pipeline

            cls._diarization_model = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1", use_auth_token=os.getenv("HF_TOKEN")
            )
        return cls._diarization_model

    @classmethod
    async def transcribe(cls, audio_path: Path, ws_manager, project_id: str):
        """Transcribe el audio y retorna segmentos."""
        await ws_manager.send_progress(
            project_id, 0.6, "Transcribiendo audio...", "processing"
        )
        await ws_manager.send_log(project_id, "Iniciando transcripción con Whisper")

        whisper_model = cls.get_whisper_model()
        segments = whisper_model.transcribe(str(audio_path))

        await ws_manager.send_progress(
            project_id, 0.7, "Realizando diarización...", "processing"
        )
        await ws_manager.send_log(project_id, "Diarización de altavoces")

        diarization_model = cls.get_diarization_model()
        diarize_segments = diarization_model(str(audio_path))

        result = cls._process_audio(segments, diarize_segments)

        await ws_manager.send_log(
            project_id, f"✅ Transcripción completada: {len(result)} segmentos"
        )

        return result, segments.language

    @staticmethod
    def _process_audio(
        segments, diarize_segments, group_segments=True, max_duration=7, max_gap=1
    ):
        """Procesa y agrupa segmentos."""
        # Import from original v2v project
        from src.diarization import process_audio

        return process_audio(
            segments, diarize_segments, group_segments, max_duration, max_gap
        )
