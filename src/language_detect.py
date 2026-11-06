"""Detección de idioma con la cabeza de idioma de Whisper.

CrisperWhisper 2 no tiene detector propio y su decoder no se entrenó para
identificar el idioma: al pedirle esos logits reparte la probabilidad entre
decenas de idiomas (0.02 para casi todos). Whisper sí está entrenado para esa
tarea, así que se resuelve el idioma aquí y se le pasa ya elegido.

Para esta tarea se usa por defecto `whisper-tiny` (~39M parámetros), no el
modelo de transcripción: promediar tres ventanas de 30 s sobre la voz separada
basta para el idioma y ahorra ~1.5 GB de VRAM frente a `turbo`. El tamaño se
puede cambiar con `WHISPER_LANG_MODEL` (`base`, `small`, …).

El módulo no importa Whisper ni `src.stt` al cargarse: así los tests pueden
usarlo sin arrastrar torch, google-genai ni el resto del pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def select_audio_windows(
    total_samples: int, span_samples: int, count: int = 3
) -> list[int]:
    """Reparte hasta `count` ventanas de 30 s por el audio, sin repetirlas."""
    if total_samples <= span_samples:
        return [0]
    count = max(1, min(count, total_samples // span_samples))
    if count == 1:
        return [0]
    return [
        int(i * (total_samples - span_samples) / (count - 1))
        for i in range(count)
    ]


def detect_language_whisper(
    media_path: Path | str,
    model: Any = None,
) -> tuple[str, float, str]:
    """Detecta el idioma promediando hasta tres ventanas de 30 s de Whisper.

    Devuelve `(código, probabilidad, detalle)`. El detalle solo incluye
    alternativas cuando la confianza es baja, para no ensuciar el log.
    """
    import whisper

    if model is None:
        from src.stt import get_language_detector_model

        model = get_language_detector_model()

    audio = whisper.load_audio(str(media_path))
    span = int(whisper.audio.N_SAMPLES)
    starts = select_audio_windows(len(audio), span)

    totals: dict[str, float] = {}
    for start in starts:
        chunk = audio[start:start + span]
        if chunk.shape[0] < span:
            chunk = whisper.pad_or_trim(chunk)
        mel = whisper.log_mel_spectrogram(
            chunk, n_mels=model.dims.n_mels
        ).to(model.device)
        _, probs = model.detect_language(mel)
        for code, value in probs.items():
            totals[code] = totals.get(code, 0.0) + float(value)

    if not totals:
        raise RuntimeError("Whisper no devolvió probabilidades de idioma.")

    average = {
        code: value / len(starts) for code, value in totals.items()
    }
    ordered = sorted(average.items(), key=lambda item: item[1], reverse=True)
    language, probability = ordered[0]
    detail = ""
    if probability < 0.5:
        alternatives = ", ".join(
            f"{code} {value:.2f}" for code, value in ordered[1:4]
        )
        detail = f" · alternativas: {alternatives}"
    return language, float(probability), detail
