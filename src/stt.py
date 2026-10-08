"""
Transcripción STT con Whisper y procesamiento con diarización.
"""
import concurrent.futures
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


_TITLE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="v2v_title")


def launch_async_title_generation(
    url: str,
    target_lang: str,
    fallback_text: Optional[str] = None,
) -> concurrent.futures.Future:
    """Lanza la inferencia de título viral en segundo plano sin congelar el hilo principal."""
    return _TITLE_EXECUTOR.submit(
        generate_tiktok_title,
        youtube_url=url,
        target_lang=target_lang,
        fallback_text=fallback_text,
    )


def resolve_final_title(
    title_future: Optional[concurrent.futures.Future],
    fallback_title: str,
) -> tuple[str, float]:
    """
    Espera la resolución del título viral de forma segura sin timeout forzado.
    Garantiza que el título definitivo (sea el inferido por IA o el fallback original)
    esté siempre definido antes de que el tag de la URL pase a completado.
    """
    t0 = time.perf_counter()
    if not title_future:
        return fallback_title, 0.0

    try:
        raw_title = title_future.result()
        elapsed = time.perf_counter() - t0
        if raw_title and str(raw_title).strip():
            clean = "".join(c for c in str(raw_title) if c not in r'\/:*?"<>|').replace('\n', ' ').strip()
            if clean:
                print(f"⏱️ [Etapa: Título Viral (Gemini)] Generado en {elapsed:.1f}s: {clean}", flush=True)
                return clean, elapsed
    except Exception as e:
        print(f"⚠️ [Título Viral] Error en generación: {e}. Usando título original: '{fallback_title}'", flush=True)

    elapsed = time.perf_counter() - t0
    return fallback_title, elapsed


def run_main(
    media: Union[str, Path],
    url: str,
    translate: Union[bool, str] = False,
    title: Optional[str] = None,
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

    # Inferencia asíncrona con resolución garantizada antes de retornar al pipeline
    fallback_summary = " ".join(t["text"] for t in (translated_result or result)) if (translated_result or result) else (title or "")
    default_title = title or media_path.stem
    title_fut = launch_async_title_generation(
        url=url,
        target_lang=translate if translate else transcription.language,
        fallback_text=fallback_summary,
    )
    output_name, t_title = resolve_final_title(title_fut, fallback_title=default_title)

    stt_timings = {
        "whisper": t_whisper,
        "diarization": t_diarize,
        "translation": t_trans,
        "title": t_title,
    }
    return translated_result, output_name, result, transcription, diarization, stt_timings
