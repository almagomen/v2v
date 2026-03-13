import io
import time
from pathlib import Path
from typing import Optional
import requests
import torch
import torchaudio
from app.core.config import settings


SPEAKER_OPTIONS = {
    "mrbeast_lmnt": "d47094be-9814-4323-9000-e735e04d8732",
    "Dionisio Schuyler": "Dionisio Schuyler",
    "en-US-AndrewMultilingualNeural": "en-US-AndrewMultilingualNeural",
    "Chatterbox": "Chatterbox",
}

LMNT_URL = "https://api.lmnt.com/v1/ai/speech/bytes"


class TTSService:
    """Servicio de síntesis de voz con LMNT."""

    @staticmethod
    def get_cookies():
        """Obtiene las cookies necesarias para LMNT."""
        return {
            "lmnt-auth0": settings.LMNT_AUTH0_COOKIE or "",
            "mp_576dc537cb2781fc026e98b5c5527486_mixpanel": settings.MIXPANEL_COOKIE
            or "",
        }

    @classmethod
    def synthesize(
        cls,
        text: str,
        language: str,
        voice_id: str,
        output_path: Optional[Path] = None,
        format: str = "wav",
        temperature: float = 1.2,
        top_p: float = 0.85,
        sample_rate: int = 24000,
    ) -> tuple[Optional[Path], int]:
        """
        Sintetiza texto a audio usando LMNT.
        Returns: (audio_path, sample_rate)
        """
        api_key = settings.LMNT_API_KEY
        if not api_key:
            raise ValueError("LMNT_API_KEY no configurada")

        headers = {
            "accept": "*/*",
            "accept-language": "es,es-ES;q=0.9,en;q=0.8",
            "origin": "https://app.lmnt.com",
            "priority": "u=1, i",
            "referer": "https://app.lmnt.com/",
            "x-api-key": api_key,
        }

        files = {
            "text": (None, text),
            "voice": (None, voice_id),
            "format": (None, format),
            "language": (None, language),
            "model": (None, "blizzard"),
            "sample_rate": (None, str(sample_rate)),
            "temperature": (None, str(temperature)),
            "top_p": (None, str(top_p)),
        }

        response = requests.post(
            LMNT_URL, headers=headers, files=files, cookies=cls.get_cookies()
        )
        time.sleep(2)
        response.raise_for_status()

        waveform, sr = torchaudio.load(io.BytesIO(response.content))

        if output_path:
            torchaudio.save(str(output_path), waveform, sr)
            return output_path, sr

        return None, sr

    @classmethod
    async def regenerate_segment(
        cls,
        segment_id: str,
        project_dir: Path,
        ws_manager,
        project_id: str,
    ) -> tuple[Optional[Path], bool]:
        """Regenera un segmento de audio específico."""
        from app.core.database import Session, AudioSegment

        with Session() as session:
            segment = session.get(AudioSegment, segment_id)
            if not segment:
                return None, False

            voice_id = SPEAKER_OPTIONS.get(segment.speaker_id, segment.speaker_id)
            lang = segment.speaker_id  # Simplificado

            await ws_manager.send_log(
                project_id, f"Regenerando segmento: {segment.text[:30]}..."
            )

            output_path = project_dir / "Seqs_trg" / f"segment_{segment.id}.wav"
            output_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                audio_path, sr = cls.synthesize(
                    text=segment.text,
                    language=lang,
                    voice_id=voice_id,
                    output_path=output_path,
                )

                segment.audio_path = str(audio_path)
                segment.is_dirty = False
                segment.is_generated = True
                session.commit()

                await ws_manager.send_log(
                    project_id, f"Segmento regenerado: {audio_path.name}"
                )
                return audio_path, True

            except Exception as e:
                await ws_manager.send_error(project_id, f"Error al regenerar: {str(e)}")
                return None, False

    @classmethod
    async def generate_all_segments(
        cls,
        segments: list,
        project_dir: Path,
        language: str,
        speaker_id: str,
        ws_manager,
        project_id: str,
    ) -> list[Path]:
        """Genera audio para todos los segmentos."""
        voice_id = SPEAKER_OPTIONS.get(speaker_id, speaker_id)
        output_dir = project_dir / "Seqs_trg"
        output_dir.mkdir(parents=True, exist_ok=True)

        generated_paths = []
        total = len(segments)

        for idx, segment in enumerate(segments):
            await ws_manager.send_progress(
                project_id,
                0.7 + (0.2 * idx / total),
                f"Generando audio {idx + 1}/{total}...",
                "processing",
            )
            await ws_manager.send_log(
                project_id, f"Synthesizing: {segment.text[:50]}..."
            )

            output_path = output_dir / f"segment_{segment.id}.wav"

            try:
                audio_path, sr = cls.synthesize(
                    text=segment.text,
                    language=language,
                    voice_id=voice_id,
                    output_path=output_path,
                )
                generated_paths.append(audio_path)
            except Exception as e:
                await ws_manager.send_log(project_id, f"Error: {str(e)}", "error")
                generated_paths.append(None)

        return generated_paths
