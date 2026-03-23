"""Transcribe audio with Whisper + diarization and return segments."""

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.schemas import TranscribeAudioResponse, TranscribeSegmentSchema
from src.stt import transcribe_and_process

router = APIRouter(prefix="/api", tags=["transcribe-audio"])


@router.post("/transcribe-audio", response_model=TranscribeAudioResponse)
async def transcribe_audio(
    audio: UploadFile = File(...),
    language: Optional[str] = Form(None),
    max_gap: float = Form(1.5),
    max_duration: int = Form(7),
):
    """
    Transcribe audio and assign speakers using Whisper + diarization.

    Returns segments in the shape:
      [{ start, end, text, speaker }]

    Note: el parámetro `language` se acepta por compatibilidad, pero el
    pipeline actual de `src/stt.py` no lo utiliza explícitamente (Whisper
    detecta idioma automáticamente).
    """

    try:
        suffix = Path(audio.filename or "audio.wav").suffix or ".wav"
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td) / f"audio{suffix}"
            data = await audio.read()
            tmp_path.write_bytes(data)

            segments, whisper_result, _diarization = transcribe_and_process(
                media_path=tmp_path,
                gap=max_gap,
                duration=max_duration,
            )

            detected_language = getattr(whisper_result, "language", None)

            normalized_segments: list[TranscribeSegmentSchema] = []
            for s in segments or []:
                normalized_segments.append(
                    TranscribeSegmentSchema(
                        start=float(s.get("start", 0.0)),
                        end=float(s.get("end", 0.0)),
                        text=str(s.get("text", "") or ""),
                        speaker=s.get("speaker"),
                    )
                )

            return TranscribeAudioResponse(
                segments=normalized_segments,
                language=detected_language,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

