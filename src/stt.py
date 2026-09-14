"""
Transcripción STT con Whisper y procesamiento con diarización.
"""
import contextlib
import io
from pathlib import Path
from typing import Union, Tuple, Any, Optional

try:
    import stable_whisper
    import torchaudio
except ImportError:
    stable_whisper = None
    torchaudio = None

from src.config import DEVICE, DRIVE_DIR
from src.models import get_or_load_model
from src.diarization import get_diarization_model, speaker_diarization, process_audio
from src.translation import translate_text_list, generate_tiktok_title


def find_whisper_dir() -> Path | None:
    """Busca dinámicamente el directorio del modelo whisper_turbo."""
    candidates = []
    if DRIVE_DIR:
        candidates.append(DRIVE_DIR / "whisper_turbo")
    candidates.extend([
        Path("/content/drive/MyDrive/v2v/whisper_turbo"),
        Path("/content/drive/MyDrive/whisper_turbo"),
        Path("/content/v2v/whisper_turbo"),
        Path("/content/whisper_turbo"),
    ])
    for p in candidates:
        if p and p.exists():
            return p
    return candidates[0] if DRIVE_DIR else None


def get_whisper_model():
    whisper_dir = find_whisper_dir()
    return get_or_load_model(
        "whisper",
        stable_whisper.load_model,
        "turbo",
        device=DEVICE,
        download_root=whisper_dir,
    )


def transcribe_and_process(
    media_path: Path | str | None = None,
    segments: Any = None,
    gap: float = 1,
    duration: int = 7,
) -> Tuple[list[dict], Any, Any]:
    """
    Transcribe y procesa con diarización. Si segments es None, transcribe desde media_path.
    Returns: (result, transcription_segments, diarize_segments)
    """
    if segments is None:
        if media_path is None:
            raise ValueError("Se requiere media_path o segments.")
        whisper_model = get_whisper_model()
        segments = whisper_model.transcribe(str(media_path), verbose=None)

        diarization_model = get_diarization_model()
        f_err = io.StringIO()
        with contextlib.redirect_stderr(f_err):
            diarize_segments = speaker_diarization(diarization_model, str(media_path))

        result = process_audio(
            segments,
            diarize_segments,
            group_segments=True,
            max_duration=duration,
            max_gap=gap,
        )
        return result, segments, diarize_segments

    raise ValueError("Pasando segments sin media_path no soportado aquí.")


def write_subtitle_file(segments: Any, output_path: Path, word_level: bool = False) -> None:
    """Escribe archivo de subtítulos desde segmentos Whisper."""
    _original_to_srt_vtt = segments.to_srt_vtt
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        _original_to_srt_vtt(str(output_path), word_level=word_level)
    print("✅ Subtítulos guardados")


def run_main(
    media: Union[str, Path],
    url: str,
    translate: Union[bool, str] = False,
    title: Optional[str] = None,
) -> Tuple[list[dict], str, list[dict], Any, Any]:
    """
    Pipeline principal: transcribe, opcionalmente traduce, genera título.

    Args:
        media: ruta al video.
        url: URL de YouTube (para generar título viral con Gemini).
        translate: idioma destino de la traducción, o False para no traducir.
        title: título original del video de YouTube (fallback si Gemini falla).

    Returns: (translated_result, output_name, result, transcription, diarization)
    """
    media_path = Path(media)
    vocals_path = media_path.with_name("vocals.wav")

    if not vocals_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de voces: {vocals_path}")

    result, transcription, diarization = transcribe_and_process(vocals_path)

    times = []
    texts = []
    for r in result:
        times.append((float(r["start"]), float(r["end"])))
        texts.append(r["text"])

    translated_result = result
    if translate:
        translated_texts = translate_text_list(
            texts,
            target_lang=translate,
            source_lang=transcription.language,
        )
        if translated_texts:
            # BUG FIX: preservar todos los metadatos del segmento original (speaker, words, etc.)
            # En lugar de crear un dict nuevo que pierde el campo 'speaker'.
            translated_result = []
            for (s, e), txt, orig in zip(times, translated_texts, result):
                seg_dict = dict(orig)
                seg_dict["start"] = s
                seg_dict["end"] = e
                seg_dict["text"] = txt
                translated_result.append(seg_dict)
        else:
            print("⚠️ No se pudo traducir, usando texto original")

    # Generar título viral con Gemini (con manejo de error robusto)
    try:
        output_name = generate_tiktok_title(url, translate if translate else transcription.language)
    except Exception as e:
        print(f"⚠️ Error al generar título viral (IA): {e}")
        output_name = None

    if output_name:
        # Limpiar nombre para archivo (quitar caracteres inválidos en Windows)
        output_name = "".join(c for c in output_name if c not in r'\/:*?"<>|').replace('\n', ' ').strip() or "output"
    else:
        # Fallback al título original de YouTube proporcionado por pipeline.py
        output_name = title or media_path.stem

    return translated_result, output_name, result, transcription, diarization
