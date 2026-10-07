"""
Transcripción STT con Whisper y procesamiento con diarización.
"""
import contextlib
import io
import time
from pathlib import Path
from typing import Union, Tuple, Any, Optional

try:
    import stable_whisper
    import torchaudio
except ImportError:
    stable_whisper = None
    torchaudio = None

from src.config import DEVICE, DRIVE_DIR, KAGGLE_INPUT_DIR
from src.models import get_or_load_model
from src.diarization import get_diarization_model, speaker_diarization, process_audio
from src.translation import translate_text_list, generate_tiktok_title

WHISPER_DIR = DRIVE_DIR / "whisper_turbo" if DRIVE_DIR else None
if not WHISPER_DIR and KAGGLE_INPUT_DIR and KAGGLE_INPUT_DIR.exists():
    for cand in [
        KAGGLE_INPUT_DIR / "whisper_turbo",
        KAGGLE_INPUT_DIR / "whisper-turbo",
        KAGGLE_INPUT_DIR / "v2v-models" / "whisper_turbo",
    ]:
        if cand.exists():
            WHISPER_DIR = cand
            break


def get_whisper_model():
    return get_or_load_model(
        "whisper",
        stable_whisper.load_model,
        "turbo",
        device=DEVICE,
        download_root=WHISPER_DIR,
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
        t0_whisper = time.perf_counter()
        whisper_model = get_whisper_model()
        segments = whisper_model.transcribe(str(media_path), verbose=None)
        t_whisper = time.perf_counter() - t0_whisper
        print(f"⏱️ [Etapa: Transcripción (Whisper)] Completada en {t_whisper:.1f}s")

        t0_diarize = time.perf_counter()
        diarization_model = get_diarization_model()
        f_err = io.StringIO()
        with contextlib.redirect_stderr(f_err):
            diarize_segments = speaker_diarization(diarization_model, str(media_path))
        t_diarize = time.perf_counter() - t0_diarize
        print(f"⏱️ [Etapa: Diarización (Pyannote)] Completada en {t_diarize:.1f}s")

        t0_group = time.perf_counter()
        result = process_audio(
            segments,
            diarize_segments,
            group_segments=True,
            max_duration=duration,
            max_gap=gap,
        )
        t_group = time.perf_counter() - t0_group
        total_stt = t_whisper + t_diarize + t_group
        print(f"⏱️ [Etapa: STT + Diarización Total] {total_stt:.1f}s ({len(result)} segmentos generados)")
        return result, segments, diarize_segments, {"whisper": t_whisper, "diarization": t_diarize}

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
    use_search_grounding: bool = False,
) -> Tuple[list[dict], str, list[dict], Any, Any, dict]:
    """
    Pipeline principal: transcribe, opcionalmente traduce, genera título.
    Returns: (translated_result, output_name, result, transcription, diarization, stt_timings)
    """
    media_path = Path(media)
    vocals_path = media_path.with_name("vocals.wav")

    if not vocals_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de voces: {vocals_path}")

    res_tuple = transcribe_and_process(vocals_path)
    result, transcription, diarization = res_tuple[0], res_tuple[1], res_tuple[2]
    step_timings = res_tuple[3] if len(res_tuple) > 3 else {}
    t_whisper = step_timings.get("whisper", 0.0)
    t_diarize = step_timings.get("diarization", 0.0)

    times = []
    texts = []
    for r in result:
        times.append((float(r["start"]), float(r["end"])))
        texts.append(r["text"])

    translated_result = result
    t_trans = 0.0
    if translate:
        t0_trans = time.perf_counter()
        translated_texts = translate_text_list(
            texts,
            target_lang=translate,
            source_lang=transcription.language,
            use_search_grounding=use_search_grounding,
        )
        t_trans = time.perf_counter() - t0_trans
        if translated_texts:
            translated_result = []
            for (s, e), txt, orig in zip(times, translated_texts, result):
                seg_dict = dict(orig)
                seg_dict["start"] = s
                seg_dict["end"] = e
                seg_dict["text"] = txt
                translated_result.append(seg_dict)
            print(f"⏱️ [Etapa: Traducción (Gemini)] Completada en {t_trans:.1f}s ({len(translated_texts)} segmentos)")
        else:
            print("⚠️ No se pudo traducir, usando texto original")

    t_title = 0.0
    try:
        t0_title = time.perf_counter()
        fallback_summary = " ".join(t["text"] for t in (translated_result or result)[:12]) if (translated_result or result) else (title or "")
        output_name = generate_tiktok_title(
            url,
            translate if translate else transcription.language,
            fallback_text=fallback_summary,
            use_search_grounding=use_search_grounding,
        )
        t_title = time.perf_counter() - t0_title
        if output_name:
            print(f"⏱️ [Etapa: Título Viral (Gemini)] Generado en {t_title:.1f}s: {output_name}")
    except Exception as e:
        print(f"⚠️ Error al generar título viral (IA): {e}")
        output_name = None

    if output_name:
        # Limpiar solo si es un nombre autogenerado para seguridad básica, 
        # pero para el título original de YT lo dejamos tal cual.
        output_name = "".join(c for c in output_name if c not in r'\/:*?"<>|').replace('\n', ' ').strip() or "output"
    else: 
        # Fallback al título original de YouTube proporcionado por pipeline.py
        output_name = title or media_path.stem

    stt_timings = {
        "whisper": t_whisper,
        "diarization": t_diarize,
        "translation": t_trans,
        "title": t_title,
    }
    return translated_result, output_name, result, transcription, diarization, stt_timings
