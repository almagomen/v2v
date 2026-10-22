import io
import json
import time
from pathlib import Path
from typing import Any, Tuple, Optional, Union

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


def normalize_pronunciation_dictionary(dict_input: Any) -> Optional[list[dict]]:
    """
    Normaliza cualquier entrada de diccionario de pronunciación al formato oficial de Fish Audio S2:
    - Lista de reglas inline: [{"items": [{"key": "...", "value": "...", "case_sensitive": bool}]}]
    - Lista de managed dictionaries: [{"id": "...", "version": "..."}]
    - Diccionario plano Python: {"Ghidra": "Gí-dra"} -> inline rules
    - Ruta (str o Path) hacia archivo JSON local
    """
    if dict_input is None:
        return None

    # Si es una ruta hacia un archivo JSON
    if isinstance(dict_input, (str, Path)):
        p = Path(dict_input)
        if p.exists() and p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return normalize_pronunciation_dictionary(data)
            except Exception as e:
                print(f"⚠️ Error al leer archivo de pronunciación {p}: {e}")
                return None
        return None

    # Si es un dict directo {"palabra": "fonética"} o estructurado
    if isinstance(dict_input, dict):
        if "items" in dict_input or "id" in dict_input:
            return [dict_input]
        items = []
        seen_keys = set()
        for k, v in dict_input.items():
            k_str = str(k).strip()
            if not k_str:
                continue

            if isinstance(v, str):
                v_str = v.strip()
                # Heurística inteligente: siglas o palabras de <= 4 letras requieren coincidencia exacta
                case_sensitive = len(k_str) <= 4 or k_str.isupper()
            elif isinstance(v, dict):
                k_str = str(v.get("key", k_str)).strip()
                v_str = str(v.get("value", "")).strip()
                case_sensitive = bool(v.get("case_sensitive", len(k_str) <= 4 or k_str.isupper()))
            else:
                continue

            dedup_key = k_str if case_sensitive else k_str.lower()
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            items.append({
                "key": k_str,
                "value": v_str,
                "case_sensitive": case_sensitive,
            })
        return [{"items": items}] if items else None


    # Si ya es una lista
    if isinstance(dict_input, list):
        normalized = []
        for entry in dict_input:
            if isinstance(entry, dict):
                if "items" in entry or "id" in entry:
                    normalized.append(entry)
                elif "key" in entry and "value" in entry:
                    normalized.append({
                        "items": [{
                            "key": str(entry["key"]),
                            "value": str(entry["value"]),
                            "case_sensitive": bool(entry.get("case_sensitive", False)),
                        }]
                    })
        return normalized if normalized else None

    return None


def find_pronunciation_dictionary(search_dir: Optional[Union[str, Path]] = None) -> Optional[list[dict]]:
    """
    Busca automáticamente un archivo de diccionario de pronunciación si no se pasa explícitamente:
    1. search_dir / "pronunciation.json"
    2. search_dir / "pronunciation_dictionary.json"
    3. Path.cwd() / "pronunciation.json"
    """
    candidates = []
    if search_dir:
        sd = Path(search_dir)
        if sd.is_file():
            sd = sd.parent
        candidates.append(sd / "pronunciation.json")
        candidates.append(sd / "pronunciation_dictionary.json")

    candidates.append(Path.cwd() / "pronunciation.json")
    candidates.append(Path.cwd() / "pronunciation_dictionary.json")

    for cand in candidates:
        if cand.exists() and cand.is_file():
            res = normalize_pronunciation_dictionary(cand)
            if res:
                return res
    return None


def fish_tts(
    text: str,
    language: str = "es",
    voice_id: Optional[str] = None,
    format: str = "wav",
    temperature: float = 0.7,
    sample_rate: Optional[int] = 44100,
    model: str = DEFAULT_MODEL,
    pronunciation_dictionary: Optional[Any] = None,
    **kwargs,
) -> Tuple[Any, Optional[int]]:
    """
    Genera audio con Fish Audio usando el modelo s2.1-pro-free / S2.
    voice_id puede ser un ID de modelo de Fish Audio (reference_id) o None para voz por defecto.
    Parámetros opcionales vía **kwargs:
      - top_p (0.7), repetition_penalty (1.2), speed (1.0), volume (0.0)
      - latency ("normal" | "balanced")
      - chunk_length (int 100-300)
      - pronunciation_dictionary (inline rules, managed id o path a json)
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
    volume = float(kwargs.get("volume", 0.0))

    payload: dict[str, Any] = {
        "text": text,
        "format": format,
        "temperature": float(temperature),
        "top_p": float(top_p),
        "repetition_penalty": float(repetition_penalty),
        "normalize": True,
    }

    if language:
        payload["language"] = language

    if sample_rate:
        payload["sample_rate"] = sample_rate

    # Latencia (normal | balanced)
    latency = kwargs.get("latency")
    if latency in ("normal", "balanced"):
        payload["latency"] = latency

    # Longitud de chunk
    chunk_length = kwargs.get("chunk_length")
    if chunk_length and isinstance(chunk_length, int):
        payload["chunk_length"] = chunk_length

    # Bitrate opcional para mp3 u opus
    if format == "mp3" and kwargs.get("mp3_bitrate"):
        payload["mp3_bitrate"] = int(kwargs["mp3_bitrate"])
    elif format == "opus" and kwargs.get("opus_bitrate"):
        payload["opus_bitrate"] = int(kwargs["opus_bitrate"])

    # Diccionario de pronunciación oficial de Fish Audio S2
    dict_source = pronunciation_dictionary if pronunciation_dictionary is not None else kwargs.get("pronunciation_dictionary")
    norm_dict = normalize_pronunciation_dictionary(dict_source)
    if not norm_dict:
        norm_dict = find_pronunciation_dictionary(kwargs.get("search_dir"))
    if norm_dict:
        payload["pronunciation_dictionary"] = norm_dict

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

