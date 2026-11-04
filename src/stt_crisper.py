"""
Motor STT opcional CrisperWhisper (modo verbatim).

Vive en su propio módulo para poder probar la adaptación de resultados sin
arrastrar las dependencias de red de `src.stt` (google-genai).
"""
import os
from pathlib import Path
from typing import Any

from src.config import DEVICE
from src.models import get_or_load_model

# El tamaño se puede cambiar con CRISPERWHISPER_MODEL; "turbo" mantiene la
# misma velocidad que el Whisper actual.
CRISPER_MODEL = os.getenv("CRISPERWHISPER_MODEL", "turbo").strip() or "turbo"


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


def _load_audio_head(media_path: Path | str, seconds: float = 30.0):
    """Lee solo los primeros segundos del audio y lo remuestrea a 16 kHz."""
    import soundfile as sf
    from crisperwhisper.audio import load_audio

    info = sf.info(str(media_path))
    frames = max(1, min(int(info.frames), int(seconds * info.samplerate)))
    audio, sample_rate = sf.read(
        str(media_path), frames=frames, dtype="float32", always_2d=False
    )
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)
    return load_audio(audio, sr=sample_rate)


def _logits_to_array(logits: Any):
    """Convierte los logits del decoder CT2 en un ndarray de NumPy en CPU.

    `StorageView` solo expone `__array_interface__` cuando sus datos viven en
    CPU; en GPU ese atributo lanza `AttributeError` y NumPy acaba creando un
    array 0-d de objetos con la propia vista dentro, que luego revienta al
    convertirlo a float. Por eso movemos la vista a CPU antes de leerla.
    """
    import numpy as np

    if hasattr(logits, "to_device"):
        import ctranslate2

        if hasattr(logits, "to"):
            logits = logits.to(ctranslate2.DataType.float32)
        logits = logits.to_device(ctranslate2.Device.cpu)
    array = np.asarray(logits)
    if array.dtype == object:
        raise RuntimeError(
            "No se pudieron leer los logits de CrisperWhisper como números."
        )
    return array


def _language_scores(logits: Any, lang_ids: dict[str, int]) -> tuple[str, float]:
    """Softmax sobre los logits de los tokens de idioma -> (código, probabilidad).

    Réplica en Python de lo que hace `detect_language` en el C++ de CT2, pero
    usando el vocabulario del tokenizer en lugar del `config.json` del modelo.
    """
    import numpy as np

    scores = _logits_to_array(logits).astype(np.float64).reshape(-1)
    codes = list(lang_ids)
    ids = [int(lang_ids[code]) for code in codes]
    if not ids or max(ids) >= scores.size:
        raise RuntimeError(
            "Los tokens de idioma de CrisperWhisper no coinciden con su vocabulario."
        )
    lang_scores = scores[ids]
    lang_scores -= lang_scores.max()
    probs = np.exp(lang_scores)
    probs /= probs.sum()
    best = int(probs.argmax())
    return codes[best], float(probs[best])


def detect_language_crisper(model: Any, media_path: Path | str) -> str:
    """Detecta el idioma de origen con el decoder de CrisperWhisper (CT2).

    No usamos `raw_model.detect_language`: el conversor de CrisperWhisper copia
    el `config.json` de HuggingFace encima del de CTranslate2 y el modelo se
    queda sin `lang_ids`, lo que hace que el C++ lea una clave inexistente y
    falle con un `json.exception.type_error.302` engañoso. En su lugar pedimos
    los logits del primer paso del decoder (token SOT), que es exactamente lo
    que hace `detect_language` internamente.
    """
    engine = getattr(model, "_engine", None)
    raw_model = getattr(engine, "model", None)
    lang_ids = dict(getattr(engine, "_lang_ids", None) or {})
    sot_id = getattr(engine, "sot_id", None)
    if (
        raw_model is None
        or not hasattr(raw_model, "prefill")
        or sot_id is None
        or not lang_ids
    ):
        raise RuntimeError(
            "CrisperWhisper no expone el decoder CT2 necesario para detectar el idioma. "
            "Usa el backend ct2 ('crisperwhisper[ct2]') o cambia el motor STT a 'stable'."
        )

    features = engine.extract_features(_load_audio_head(media_path))
    _, logits = raw_model.prefill(features, [int(sot_id)])
    try:
        language, probability = _language_scores(logits, lang_ids)
    except (IndexError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "No se pudo detectar el idioma de origen con CrisperWhisper."
        ) from exc
    print(f"🌐 [CrisperWhisper] Idioma detectado: {language} ({probability:.2f})", flush=True)
    return language


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


def transcribe_with_crisper(model: Any, media_path: Path | str) -> dict:
    """Transcribe en modo verbatim con timestamps por palabra."""
    language = detect_language_crisper(model, media_path)
    result = model.transcribe(
        str(media_path),
        language=language,
        mode="verbatim",
        word_timestamps=True,
    )
    return _crisper_result_to_segments(result, language)
