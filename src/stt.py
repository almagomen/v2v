"""
Transcripción STT con Whisper y procesamiento con diarización.
"""
import concurrent.futures
import contextlib
import io
import re
import time
from pathlib import Path
from typing import Union, Tuple, Any, Optional

try:
    import torch
    import stable_whisper
    import torchaudio
except ImportError:
    torch = None
    stable_whisper = None
    torchaudio = None

from src.config import DEVICE, DRIVE_DIR, KAGGLE_INPUT_DIR
from src.models import get_or_load_model
from src.diarization import get_diarization_model, speaker_diarization, process_audio
from src.translation import translate_text_list, generate_tiktok_title
from src.result_store import create_segment_entry

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
    gap: float = 0.85,
    target_duration: Optional[float] = None,
    duration: Optional[int] = None,
) -> Tuple[list[dict], str, dict]:
    """
    Transcribe y procesa con diarización en paralelo cuando hay 2 GPUs.
    Returns: (result, detected_language, timings)
    """
    if duration is not None:
        target_duration = float(duration)

    if segments is None:
        if media_path is None:
            raise ValueError("Se requiere media_path o segments.")

        t0_stt_wall = time.perf_counter()

        def _run_whisper():
            t0 = time.perf_counter()
            whisper_model = get_whisper_model()
            try:
                # vad=True activa Silero VAD para no cortar inicios de palabras;
                # p=0.06+0.06 añade micro-padding de 60ms en bordes sin pisar palabras contiguas.
                res = whisper_model.transcribe(
                    str(media_path),
                    vad=True,
                    regroup="isp=1_cm=2.5+1.2++0_p=0.06+0.06",
                    verbose=None,
                )
                print(f"[STT] Transcripción con vad/regroup completada", flush=True)
            except Exception as e:
                print(f"⚠️ [Fallback STT] Transcribe con vad/regroup falló ({e}), intentando sin vad...", flush=True)
                try:
                    res = whisper_model.transcribe(str(media_path), regroup="isp=1_cm=2.5+1.2++0", verbose=None)
                except Exception as e2:
                    print(f"⚠️ [Fallback STT] Ejecutando transcribe estándar ({e2}).", flush=True)
                    res = whisper_model.transcribe(str(media_path), verbose=None)
            t_taken = time.perf_counter() - t0
            return res, t_taken

        def _run_diarization():
            t0 = time.perf_counter()
            diarization_model = get_diarization_model()
            f_err = io.StringIO()
            with contextlib.redirect_stderr(f_err):
                d_segs = speaker_diarization(diarization_model, str(media_path))
            t_taken = time.perf_counter() - t0
            return d_segs, t_taken

        gpu_count = torch.cuda.device_count() if (torch is not None and torch.cuda.is_available()) else 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="v2v_stt_diarize") as executor:
            fut_whisper = executor.submit(_run_whisper)
            fut_diarize = executor.submit(_run_diarization)
            segments, t_whisper = fut_whisper.result()
            diarize_segments, t_diarize = fut_diarize.result()

        wh_gpu_tag = " | GPU 0" if gpu_count >= 2 else ""
        dia_gpu_tag = " | GPU 1" if gpu_count >= 2 else ""
        print(f"⏱️ [Transcripción (Whisper{wh_gpu_tag})] Completada en {t_whisper:.1f}s")
        print(f"⏱️ [Diarización (Pyannote{dia_gpu_tag})] Completada en {t_diarize:.1f}s")

        # Extraer idioma detectado antes de procesar
        detected_language = getattr(segments, "language", "es") if segments else "es"

        # Guardar volcado crudo de Whisper para debug y auditoría (palabras, timestamps y probabilidades)
        try:
            raw_path = Path(media_path).parent / "whisper_raw.json"
            import json
            if hasattr(segments, "to_dict"):
                raw_payload = segments.to_dict()
            elif hasattr(segments, "__dict__"):
                raw_payload = segments.__dict__
            else:
                raw_payload = {"text": getattr(segments, "text", str(segments)), "language": detected_language}
            raw_path.write_text(json.dumps(raw_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"⚠️ No se pudo guardar whisper_raw.json: {e}")

        t0_group = time.perf_counter()
        result = process_audio(
            segments,
            diarize_segments,
            group_segments=True,
            max_gap=gap if gap is not None else 0.85,
        )
        t_group = time.perf_counter() - t0_group
        total_stt_wall = time.perf_counter() - t0_stt_wall
        return result, detected_language, {"whisper": t_whisper, "diarization": t_diarize}

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
    enable_emotions: bool = True,
    initial_emotion_per_sentence: bool = False,
    initial_emotion_tag: str = "[excited]",
) -> Tuple[list[dict], str, list[dict], str, dict]:
    """
    Pipeline principal: transcribe, opcionalmente traduce, genera título.
    Returns: (translated_result, output_name, original_result, source_lang, stt_timings)
    
    Nota: Ya no retorna objetos Whisper/Pyannote. Retorna solo datos JSON-serializables.
    """
    media_path = Path(media)
    vocals_path = media_path.with_name("vocals.wav")

    if not vocals_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de voces: {vocals_path}")

    result, detected_language, step_timings = transcribe_and_process(vocals_path)
    t_whisper = step_timings.get("whisper", 0.0)
    t_diarize = step_timings.get("diarization", 0.0)

    try:
        from src.expression import extract_acoustic_prosody
        result = extract_acoustic_prosody(vocals_path, result)
    except Exception as e_ac:
        print(f"⚠️ Error en prosodia acústica: {e_ac}")

    times = []
    texts = []
    for r in result:
        times.append((float(r["start"]), float(r["end"])))
        texts.append(r["text"])

    translated_result = result
    t_trans = 0.0

    target_language = translate if translate else detected_language
    should_infer = bool(translate or enable_emotions)

    if should_infer:
        t0_trans = time.perf_counter()
        translated_texts, phonemes_list = translate_text_list(
            texts,
            target_lang=target_language,
            source_lang=detected_language,
            times=times,
            segments_meta=result,
            enable_emotions=enable_emotions,
            initial_emotion_per_sentence=initial_emotion_per_sentence,
            initial_emotion_tag=initial_emotion_tag,
            return_details=True,
        )
        t_trans = time.perf_counter() - t0_trans

        if translated_texts and len(translated_texts) == len(result):
            translated_result = [
                create_segment_entry(
                    seg=orig.get("seg", i + 1),
                    start=s,
                    end=e,
                    text=txt,
                    original_text=orig.get("original_text", orig.get("text", "")),
                    speaker=orig.get("speaker"),
                    original_speaker=orig.get("original_speaker") or orig.get("speaker"),
                    phonemes=phonemes_list[i] if phonemes_list and i < len(phonemes_list) else orig.get("phonemes"),
                    internal_pause_sec=orig.get("internal_pause_sec"),
                )
                for i, ((s, e), txt, orig) in enumerate(zip(times, translated_texts, result))
            ]
        elif translated_texts:
            print(f"⚠️ Reconciliando {len(translated_texts)} inferencias con {len(result)} segmentos originales...", flush=True)
            translated_result = [
                create_segment_entry(
                    seg=orig.get("seg", i + 1),
                    start=s,
                    end=e,
                    text=translated_texts[i] if i < len(translated_texts) else orig.get("text", ""),
                    original_text=orig.get("original_text", orig.get("text", "")),
                    speaker=orig.get("speaker"),
                    original_speaker=orig.get("original_speaker") or orig.get("speaker"),
                    phonemes=phonemes_list[i] if phonemes_list and i < len(phonemes_list) else orig.get("phonemes"),
                    internal_pause_sec=orig.get("internal_pause_sec"),
                )
                for i, ((s, e), orig) in enumerate(zip(times, result))
            ]
        else:
            print("⚠️ No se pudo procesar inferencia, usando texto original", flush=True)
            translated_result = [
                create_segment_entry(
                    seg=r.get("seg", i + 1),
                    start=r["start"],
                    end=r["end"],
                    text=r["text"],
                    original_text=r.get("original_text", r.get("text", "")),
                    speaker=r.get("speaker"),
                    original_speaker=r.get("original_speaker") or r.get("speaker"),
                    phonemes=r.get("phonemes"),
                    internal_pause_sec=r.get("internal_pause_sec"),
                )
                for i, r in enumerate(result)
            ]
    else:
        def _apply_initial_tag(t: str) -> str:
            if not initial_emotion_per_sentence:
                return t
            tag = initial_emotion_tag if (initial_emotion_tag and initial_emotion_tag.startswith("[")) else f"[{initial_emotion_tag or 'excited'}]"
            clean_t = re.sub(r"^\[[a-zA-Z0-9\s_-]+\]\s*", "", t).strip()
            return f"{tag} {clean_t}".strip()

        translated_result = [
            create_segment_entry(
                seg=r.get("seg", i + 1),
                start=r["start"],
                end=r["end"],
                text=_apply_initial_tag(r["text"]),
                original_text=r.get("original_text", r.get("text", "")),
                speaker=r.get("speaker"),
                original_speaker=r.get("original_speaker") or r.get("speaker"),
                phonemes=r.get("phonemes"),
                internal_pause_sec=r.get("internal_pause_sec"),
            )
            for i, r in enumerate(result)
        ]

    # Normalizar también result original con create_segment_entry
    result = [
        create_segment_entry(
            seg=r.get("seg", i + 1),
            start=r["start"],
            end=r["end"],
            text=r.get("original_text", r.get("text", "")),
            original_text=r.get("original_text", r.get("text", "")),
            speaker=r.get("speaker"),
            original_speaker=r.get("original_speaker") or r.get("speaker"),
            phonemes=r.get("phonemes"),
            internal_pause_sec=r.get("internal_pause_sec"),
        )
        for i, r in enumerate(result)
    ]

    # Limpiar clave temporal de pista acústica de los segmentos originales
    for r in result:
        r.pop("acoustic_hint", None)

    # Inferencia asíncrona con resolución garantizada antes de retornar al pipeline
    fallback_summary = " ".join(t["text"] for t in (translated_result or result)) if (translated_result or result) else (title or "")
    default_title = title or media_path.stem
    title_fut = launch_async_title_generation(
        url=url,
        target_lang=translate if translate else detected_language,
        fallback_text=fallback_summary,
    )
    output_name, t_title = resolve_final_title(title_fut, fallback_title=default_title)

    stt_timings = {
        "whisper": t_whisper,
        "diarization": t_diarize,
        "translation": t_trans,
        "title": t_title,
    }
    return translated_result, output_name, result, detected_language, stt_timings
