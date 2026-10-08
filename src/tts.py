"""
TTS vía API Fish Audio (modelo s2.1-pro-free).
Usa FISH_API_KEY desde config (env o Colab Secrets).
"""
import io
import time
from pathlib import Path
from typing import Any, Tuple, Optional

import requests

try:
    import torch
    import torchaudio
except ImportError:
    torch = None
    torchaudio = None

from src.config import get_fish_api_key

FISH_TTS_URL = "https://api.fish.audio/v1/tts"
DEFAULT_MODEL = "s2.1-pro-free"


def fish_tts(
    text: str,
    language: str = "es",
    voice_id: Optional[str] = None,
    format: str = "wav",
    temperature: float = 0.7,
    top_p: float = 0.7,
    sample_rate: Optional[int] = 44100,
    speed: float = 1.0,
    volume: float = 0.0,
    repetition_penalty: float = 1.2,
    model: str = DEFAULT_MODEL,
    **kwargs,
) -> Tuple[Any, Optional[int]]:
    """
    Genera audio con Fish Audio usando el modelo s2.1-pro-free.
    voice_id puede ser un ID de modelo de Fish Audio (reference_id) o None para voz por defecto.
    Returns: (waveform, sample_rate) o (None, None) en caso de error.
    """
    api_key = get_fish_api_key()
    if not api_key:
        print("Error: FISH_API_KEY no configurada. Configura en Colab Secrets o .env")
        return None, None

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "model": model or DEFAULT_MODEL,
    }

    payload: dict[str, Any] = {
        "text": text,
        "format": format,
        "temperature": float(temperature),
        "top_p": float(top_p),
        "repetition_penalty": float(repetition_penalty),
        "normalize": True,
    }

    if sample_rate:
        payload["sample_rate"] = sample_rate

    # Si se especificó un voice_id / reference_id
    if voice_id and str(voice_id).strip():
        v_str = str(voice_id).strip()
        # Si es un path a un archivo que no existe como modelo, omitir o verificar
        if not Path(v_str).exists():
            payload["reference_id"] = v_str

    prosody: dict[str, Any] = {"normalize_loudness": True}
    if speed and speed != 1.0:
        prosody["speed"] = float(speed)
    if volume and volume != 0.0:
        prosody["volume"] = float(volume)
    if len(prosody) > 1 or prosody.get("speed") or prosody.get("volume"):
        payload["prosody"] = prosody

    try:
        response = requests.post(FISH_TTS_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        if torchaudio is None:
            raise RuntimeError("torchaudio no está disponible en el entorno")

        waveform, sr = torchaudio.load(io.BytesIO(response.content))
        return waveform, sr

    except requests.exceptions.HTTPError as e:
        print(f"\nError HTTP Fish Audio: {e}")
        if hasattr(response, "text") and response.text:
            print(f"Respuesta Fish Audio: {response.text}")
        return None, None

    except Exception as e:
        print(f"\nError Fish Audio: {e}")
        return None, None


def model_tts(text: str, language: str, audio_ref: str, **kwargs) -> tuple:
    """Wrapper para usar como tts_fn en clone_voice_segments. audio_ref = voice_id / reference_id."""
    return fish_tts(text=text, language=language, voice_id=audio_ref, **kwargs)


# Alias para compatibilidad con notebooks y scripts
synthesize_speech = model_tts
