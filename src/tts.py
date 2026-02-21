"""
TTS vía API LMNT. Usa LMNT_API_KEY desde config (env o Colab Secrets).
"""
import io
import time

import requests
import torchaudio

from src.config import get_lmnt_api_key

LMNT_URL = "https://api.lmnt.com/v1/ai/speech/bytes"


def lmnt_tts(
    text: str,
    language: str,
    voice_id: str,
    format: str = "wav",
    temperature: float = 1.2,
    top_p: float = 0.85,
    sample_rate: int = 24000,
) -> tuple[torch.Tensor | None, int | None]:
    """
    Genera audio con LMNT. voice_id puede ser UUID de voz o path a .wav (referencia).
    Returns: (waveform, sample_rate) o (None, None) en error.
    """
    api_key = get_lmnt_api_key()
    if not api_key:
        print("Error: LMNT_API_KEY no configurada. Configura en Colab Secrets o .env")
        return None, None

    headers = {
        "accept": "*/*",
        "x-api-key": api_key,
    }
    files = {
        "text": (None, text),
        "voice": (None, str(voice_id)),
        "format": (None, format),
        "language": (None, language),
        "model": (None, "blizzard"),
        "sample_rate": (None, str(sample_rate)),
        "temperature": (None, str(temperature)),
        "top_p": (None, str(top_p)),
    }

    try:
        response = requests.post(LMNT_URL, headers=headers, files=files, timeout=60)
        time.sleep(0.5)
        response.raise_for_status()
        waveform, sr = torchaudio.load(io.BytesIO(response.content))
        return waveform, sr
    except requests.exceptions.HTTPError as e:
        print(f"\nError HTTP LMNT: {e}")
        if hasattr(response, "text"):
            print(f"Respuesta: {response.text}")
        return None, None
    except Exception as e:
        print(f"\nError LMNT: {e}")
        return None, None


def model_tts(text: str, language: str, audio_ref: str, **kwargs) -> tuple[torch.Tensor | None, int | None]:
    """Wrapper para usar como tts_fn en clone_voice_segments. audio_ref = voice_id."""
    return lmnt_tts(text, language, audio_ref, **kwargs)
