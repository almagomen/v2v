"""
Motor STT opcional CrisperWhisper (modo verbatim).

Vive en su propio módulo para poder probar la adaptación de resultados sin
arrastrar las dependencias de red de `src.stt` (google-genai).

CrisperWhisper 2 no expone detección de idioma: su `transcribe()` recibe
`language` como argumento obligatorio y el decoder se entrenó con el token de
idioma ya presente en el prompt. Pedirle los logits del idioma reparte la
probabilidad entre decenas de códigos (0.02 para casi todos), así que el
idioma se detecta con la cabeza de idioma de Whisper y se pasa ya resuelto.
"""
import os
from pathlib import Path
from typing import Any, Callable

from src.config import DEVICE
from src.models import get_or_load_model

# El tamaño se puede cambiar con CRISPERWHISPER_MODEL; "turbo" mantiene la
# misma velocidad que el Whisper actual.
CRISPER_MODEL = os.getenv("CRISPERWHISPER_MODEL", "turbo").strip() or "turbo"

LanguageDetector = Callable[[Path | str], Any]


def _split_device(device: str) -> tuple[str, int]:
    """Convierte 'cuda:1' en ('cuda', 1) para la API de CrisperWhisper."""
    raw = (device or "auto").strip()
    if ":" in raw:
        base, _, idx = raw.rpartition(":")
        if idx.isdigit():
            return base or "auto", int(idx)
    return raw or "auto", 0


def _load_crisper_model():
    try:
        from crisperwhisper import CrisperWhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "CrisperWhisper no está instalado en el backend. "
            "Instala 'crisperwhisper[ct2]' o cambia el motor STT a 'stable'."
        ) from exc

    device, device_index = _split_device(DEVICE)
    compute_type = "float16" if device == "cuda" else "float32"
    return CrisperWhisperModel(
        CRISPER_MODEL,
        backend="ct2",
        compute_type=compute_type,
        device=device,
        device_index=device_index,
    )


def get_crisper_model():
    return get_or_load_model("crisperwhisper", _load_crisper_model)


def _normalize_detection(detected: Any) -> tuple[str, float | None, str]:
    """Acepta un código suelto o una tupla (código, probabilidad, detalle)."""
    if isinstance(detected, (tuple, list)):
        language = str(detected[0] if detected else "").strip().lower()
        probability = None
        if len(detected) > 1 and detected[1] is not None:
            try:
                probability = float(detected[1])
            except (TypeError, ValueError):
                probability = None
        detail = str(detected[2]) if len(detected) > 2 and detected[2] else ""
        return language, probability, detail
    return str(detected or "").strip().lower(), None, ""


def _log_detection(language: str, probability: float | None, detail: str) -> None:
    if probability is None:
        print(f"🌐 [CrisperWhisper] Idioma detectado: {language}", flush=True)
        return
    print(
        f"🌐 [CrisperWhisper] Idioma detectado: {language} "
        f"({probability:.2f}){detail}",
        flush=True,
    )


def _crisper_result_to_segments(result: Any, language: str) -> dict:
    """Adapta TranscriptionResult de CrisperWhisper al formato de Whisper."""
    words = []
    for word in getattr(result, "words", None) or []:
        start = getattr(word, "start", None)
        end = getattr(word, "end", None)
        text = getattr(word, "word", "")
        if start is None or end is None or not str(text).strip():
            continue
        start = float(start)
        end = max(start, float(end))
        words.append({"word": str(text), "start": start, "end": end})

    full_text = str(getattr(result, "text", "") or "").strip()
    if not words and not full_text:
        return {
            "language": language,
            "text": "",
            "segments": [],
        }

    if words:
        start = words[0]["start"]
        end = words[-1]["end"]
    else:
        start = 0.0
        end = float(getattr(result, "duration", 0.0) or 0.0)

    return {
        "language": language,
        "text": full_text,
        "segments": [
            {
                "start": start,
                "end": end,
                "text": full_text,
                "words": words,
            }
        ],
    }


def transcribe_with_crisper(
    model: Any,
    media_path: Path | str,
    *,
    language: str | None = None,
    language_detector: LanguageDetector | None = None,
) -> dict:
    """Transcribe en modo verbatim con timestamps por palabra.

    El idioma debe venir resuelto (`language`) o mediante `language_detector`,
    que devuelve el código o una tupla `(código, probabilidad, detalle)`. No se
    usa el decoder de CrisperWhisper para identificarlo porque no fue entrenado
    para esa tarea.
    """
    if not language:
        if language_detector is None:
            raise RuntimeError(
                "CrisperWhisper necesita un detector de idioma externo. "
                "El pipeline usa la cabeza de idioma de Whisper."
            )
        language, probability, detail = _normalize_detection(
            language_detector(media_path)
        )
        if not language:
            raise RuntimeError(
                "El detector de idioma no devolvió un código válido."
            )
        _log_detection(language, probability, detail)

    result = model.transcribe(
        str(media_path),
        language=language,
        mode="verbatim",
        word_timestamps=True,
    )
    return _crisper_result_to_segments(result, language)
