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
    sample_rate: Optional[int] = 44100,
    model: str = DEFAULT_MODEL,
    **kwargs,
) -> Tuple[Any, Optional[int]]:
    """
    Genera audio con Fish Audio usando el modelo s2.1-pro-free.
    voice_id puede ser un ID de modelo de Fish Audio (reference_id) o None para voz por defecto.
    Parámetros opcionales vía **kwargs: top_p (0.7), repetition_penalty (1.2), speed (1.0).
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

    top_p = float(kwargs.get("top_p", 0.7))
    repetition_penalty = float(kwargs.get("repetition_penalty", 1.2))
    speed = float(kwargs.get("speed", 1.0))

    payload: dict[str, Any] = {
        "text": text,
        "format": format,
        "temperature": float(temperature),
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
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

    # No enviar "volume" al servidor: su API aplica un compresor/fade-in inicial si se envía ese parámetro.
    prosody: dict[str, Any] = {"normalize_loudness": True}
    if speed != 1.0:
        prosody["speed"] = speed
    if len(prosody) > 1 or prosody.get("speed"):
        payload["prosody"] = prosody

    # Timeout proporcional a la longitud del texto: base 30s, +30s por cada 100 chars, máx 3 min
    base_timeout = 30
    chars_factor = max(1, len(text) / 100)
    timeout = min(int(base_timeout * chars_factor), 180)

    for attempt in range(3):
        try:
            response = requests.post(FISH_TTS_URL, headers=headers, json=payload, timeout=timeout)
            if response.status_code == 429:
                wait_time = 2.0 * (attempt + 1)
                print(f"\n⚠️ [Fish Audio 429] Rate limit alcanzado. Esperando {wait_time:.1f}s antes de reintentar...")
                time.sleep(wait_time)
                continue
            response.raise_for_status()

            if torchaudio is None:
                raise RuntimeError("torchaudio no está disponible en el entorno")

            waveform, sr = torchaudio.load(io.BytesIO(response.content))

            # Ganancia +6 dB post-respuesta: se aplica directamente aquí porque el servidor con el
            # parámetro volumen aplica un fade inicial; en local el aumento es instantáneo y sin rampa.
            gain_factor = 10.0 ** (6.0 / 20.0)  # +6.0 dB ≈ 1.995x
            if torch is not None:
                waveform = torch.clamp(waveform * gain_factor, -0.99, 0.99)
            else:
                waveform = waveform * gain_factor

            return waveform, sr

        except requests.exceptions.RequestException as e:
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
            print(f"\nError HTTP Fish Audio tras 3 intentos: {e}")
            if "response" in locals() and hasattr(response, "text") and response.text:
                print(f"Respuesta Fish Audio: {response.text}")
            return None, None
        except Exception as e:
            print(f"\nError Fish Audio: {e}")
            return None, None

    return None, None


def model_tts(text: str, language: str, audio_ref: str, **kwargs) -> tuple:
    """Wrapper para usar como tts_fn en clone_voice_segments. audio_ref = voice_id / reference_id."""
    return fish_tts(text=text, language=language, voice_id=audio_ref, **kwargs)


# Alias para compatibilidad con notebooks y scripts
synthesize_speech = model_tts
