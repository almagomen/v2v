"""
TTS vía Fish Audio API (modelo s2.1-pro-free).
Usa FISH_API_KEY desde config (env o Colab Secrets).
"""
import io

import requests

try:
    import torch
    import torchaudio
except ImportError:
    torch = None
    torchaudio = None

from src.config import get_fish_api_key

FISH_URL = "https://api.fish.audio/v1/tts"


def fish_tts(
    text: str,
    language: str,
    voice_id: str,
    format: str = "wav",
    temperature: float = 0.7,
    top_p: float = 0.7,
    sample_rate: int = 44100,
) -> tuple[torch.Tensor | None, int | None]:
    """
    Genera audio con Fish Audio (s2.1-pro-free).
    voice_id: reference_id del modelo de voz en Fish Audio.
    Returns: (waveform, sample_rate) o (None, None) en error.
    """
    api_key = get_fish_api_key()
    if not api_key:
        print("Error: FISH_API_KEY no configurada. Configura en Colab Secrets o .env")
        return None, None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "model": "s2.1-pro-free",
    }

    payload = {
        "text": text,
        "reference_id": voice_id,
        "format": format,
        "sample_rate": sample_rate,
        "temperature": temperature,
        "top_p": top_p,
        "chunk_length": 300,
        "normalize": True,
        "latency": "normal",
        "mp3_bitrate": 128,
    }

    try:
        response = requests.post(FISH_URL, headers=headers, json=payload)
        response.raise_for_status()
        waveform, sr = torchaudio.load(io.BytesIO(response.content))
        return waveform, sr

    except requests.exceptions.HTTPError as e:
        print(f"\nError HTTP Fish Audio: {e}")
        if hasattr(response, "text"): print(f"Respuesta: {response.text}")
        return None, None

    except Exception as e:
        print(f"\nError Fish Audio: {e}")
        return None, None


def model_tts(text: str, language: str, audio_ref: str, **kwargs) -> tuple[torch.Tensor | None, int | None]:
    """Wrapper para usar como tts_fn en clone_voice_segments. audio_ref = reference_id."""
    return fish_tts(text, language, audio_ref, **kwargs)
