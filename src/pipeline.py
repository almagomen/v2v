"""
Pipeline: cola de videos, transcripción, división en secuencias.
"""

import contextlib
import io
import time
import pickle
from pathlib import Path
from typing import Union, Optional

try:
    import torchaudio
except ImportError:
    torchaudio = None

from src.download import yt
from src.stt import run_main
from src.config import QUEUE_DIR


def process_video_queue(
    urls: list[str],
    translate_lang: Union[bool, str] = False,
    on_stage: Optional[callable] = None,
    current_idx: Optional[int] = None,
    total_count: Optional[int] = None,
    force_reprocess: bool = False,
) -> list[dict]:
    """
    Procesa una cola de videos: descarga, transcribe y traduce.
    Si ya existe un procesamiento previo completo, lo carga de caché a menos que force_reprocess=True.
    """
    results = []
    for idx, u in enumerate(urls, 1):
        t_url_pipeline_start = time.perf_counter()
        display_idx = current_idx if current_idx is not None else idx
        display_total = total_count if total_count is not None else len(urls)
        print(f"⚙️ Procesando: {u}  [{display_idx}/{display_total}]")
        if on_stage:
            try:
                on_stage(
                    u,
                    "downloading",
                    f"⚙️ Procesando: {u}  [{display_idx}/{display_total}]",
                )
            except Exception:
                pass
        try:
            # --- Pre-verificación de Caché por URL ---
            found_in_cache = False
            if not force_reprocess:
                # Escanear carpetas en Queue para ver si alguna tiene este link
                for folder in QUEUE_DIR.glob("*"):
                    pkl_file = folder / "result.pkl"
                    if pkl_file.exists() and pkl_file.is_file():
                        try:
                            with open(pkl_file, "rb") as f:
                                (
                                    translated_result,
                                    output_name,
                                    cached_url,
                                    result,
                                    transcription,
                                    diarization,
                                    info,
                                    *extra,
                                ) = pickle.load(f)

                            if cached_url != u:
                                continue

                            if not isinstance(info, dict):
                                info = {}

                            video_files = [p for p in folder.glob("*.mp4") if not p.name.startswith("_")]
                            if video_files:
                                path = video_files[0]
                                results.append(
                                    {
                                        "path": path,
                                        "output_name": output_name,
                                        "url": u,
                                        "info": info,
                                        "texts": translated_result,
                                        "src_lang": getattr(transcription, "language", "es") if transcription else "es",
                                        "result": result,
                                        "transcription": transcription,
                                        "diarization": diarization,
                                        "cached": True,
                                    }
                                )
                                found_in_cache = True
                                t_cache = time.perf_counter() - t_url_pipeline_start
                                print(f"♻️ Caché detectada por URL: {output_name} ({t_cache:.2f}s)")
                                break
                        except Exception:
                            continue

            if found_in_cache:
                continue
            # ---------------------------------------

            path, info = yt(u, vocals_separation=True, force_new=force_reprocess)
            output_file = path.with_name("result.pkl")

            # --- Lógica de Caché por Path ---
            if not force_reprocess and output_file.exists():
                print(f"♻️ Cargando caché: {path.name}")
                with open(output_file, "rb") as f:
                    # Carga directa de la nueva estructura de 7 campos
                    (
                        translated_result,
                        output_name,
                        url,
                        result,
                        transcription,
                        diarization,
                        info,
                        *extra,
                    ) = pickle.load(f)
                    if not isinstance(info, dict):
                        info = {}

                t_cache = time.perf_counter() - t_url_pipeline_start
                results.append(
                    {
                        "path": path,
                        "output_name": output_name,
                        "url": u,
                        "info": info,
                        "texts": translated_result,
                        "src_lang": getattr(transcription, "language", "es") if transcription else "es",
                        "result": result,
                        "transcription": transcription,
                        "diarization": diarization,
                        "cached": True,
                    }
                )
                print(f"✅ {output_name} (cargado de caché en {t_cache:.2f}s)")
                continue
            # -----------------------

            print("📝 Transcribiendo (Whisper + diarización)...")
            if on_stage:
                try:
                    on_stage(
                        u,
                        "transcribing",
                        "📝 Transcribiendo (Whisper + diarización)...",
                    )
                except Exception:
                    pass
            # Uso del título original para la visualización en el frontend
            safe_title = info.get("output_name") or info.get("safe_name") or (info.get("title") if isinstance(info, dict) else None)
            run_res = run_main(
                path,
                u,
                translate=translate_lang,
                title=safe_title,
            )
            translated_result = run_res[0]
            output_name = run_res[1]
            result = run_res[2]
            transcription = run_res[3]
            diarization = run_res[4]
            stt_timings = run_res[5] if len(run_res) > 5 else {}

            with open(output_file, "wb") as f:
                pickle.dump(
                    (
                        translated_result,
                        output_name,
                        u,
                        result,
                        transcription,
                        diarization,
                        info,
                    ),
                    f,
                )

            from src.assets import update_assets
            update_assets(path.parent, output_name=output_name)

            timings = {
                "download": info.get("_download_time", 0.0) if isinstance(info, dict) else 0.0,
                "stems": info.get("_stems_time", 0.0) if isinstance(info, dict) else 0.0,
                "whisper": stt_timings.get("whisper", 0.0),
                "diarization": stt_timings.get("diarization", 0.0),
                "translation": stt_timings.get("translation", 0.0),
                "title": stt_timings.get("title", 0.0),
            }

            if on_stage:
                try:
                    on_stage(u, "ready", f"Listo: {output_name}")
                except Exception:
                    pass
            results.append(
                {
                    "path": path,
                    "output_name": output_name,
                    "url": u,
                    "info": info,
                    "texts": translated_result,
                    "src_lang": getattr(transcription, "language", "es") if transcription else "es",
                    "result": result,
                    "transcription": transcription,
                    "diarization": diarization,
                    "cached": False,
                    "timings": timings,
                }
            )
        except Exception as e:
            import traceback

            error_trace = traceback.format_exc()
            print(f"DEBUG: Error detectado en el pipeline:")
            print(error_trace)
            print(f"❌ Error procesando {u}: {e}\n")
            if on_stage:
                try:
                    on_stage(u, "error", str(e))
                except Exception:
                    pass
            continue
    return results


def split_audio_sequences(
    audio_path: Path,
    texts: list[dict],
    output_dir: Optional[Path] = None,
    edit_indices: Optional[list[int]] = None,
) -> list[Path]:
    """Divide el audio en secuencias según los segmentos de texto."""
    if output_dir is None:
        output_dir = audio_path.parent / "Seqs_src"
    output_dir.mkdir(exist_ok=True)

    arr, org_sr = torchaudio.load(str(audio_path))
    generated_files = []

    texts_to_process = (
        texts if edit_indices is None else [texts[i - 1] for i in edit_indices]
    )

    for idx, text_dict in enumerate(texts_to_process):
        start = int(text_dict["start"] * org_sr)
        end = int(text_dict["end"] * org_sr)
        arr_split = arr[:, start:end]

        seq_num = edit_indices[idx] if edit_indices else idx + 1
        audio_filename = f"{audio_path.stem}_{seq_num:03d}.wav"
        audio_path_out = output_dir / audio_filename

        f_err = io.StringIO()
        with contextlib.redirect_stderr(f_err):
            torchaudio.save(str(audio_path_out), arr_split, sample_rate=org_sr)
        generated_files.append(audio_path_out)

    return generated_files


def split_all_sequences(video_paths: list[Path]) -> None:
    """Divide el audio de todos los videos en secuencias."""
    for path in video_paths:
        texts_file = path.with_name("result.pkl")
        if not texts_file.exists():
            print(f"⚠️ Saltando {path.stem}: no hay archivo de textos")
            continue
        with open(texts_file, "rb") as f:
            # Sincronización con el nuevo formato de 7 campos en todos los procesos
            texts, output_name, url, result, transcription, diarization, info, *rest = (
                pickle.load(f)
            )
        split_audio_sequences(
            audio_path=path.with_name("vocals.wav"),
            texts=texts,
            output_dir=path.parent / "Seqs_src",
        )
