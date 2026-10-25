"""
Pipeline: cola de videos, transcripción, división en secuencias.
"""

import contextlib
import io
import time
from pathlib import Path
from typing import Union, Optional

try:
    import torchaudio
except ImportError:
    torchaudio = None

from src.download import yt
from src.stt import run_main
from src.config import QUEUE_DIR
from src.result_store import (
    load_result,
    save_result,
    create_result,
    register_url,
    lookup_folder_by_url,
    is_complete_result,
    get_result_original_segments,
)


def process_video_queue(
    urls: list[str],
    translate_lang: Union[bool, str] = False,
    on_stage: Optional[callable] = None,
    current_idx: Optional[int] = None,
    total_count: Optional[int] = None,
    force_reprocess: bool = False,
    enable_emotions: bool = True,
    initial_emotion_per_sentence: bool = False,
    initial_emotion_tag: str = "[excited]",
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
        if on_stage:
            try:
                on_stage(
                    u,
                    "downloading",
                    f"🚀 [Link {display_idx}/{display_total}] {u}",
                )
            except Exception:
                pass
        try:
            # --- Pre-verificación de Caché por URL (O(1) con índice) ---
            found_in_cache = False
            if not force_reprocess:
                cached_folder_name = lookup_folder_by_url(u)
                if cached_folder_name:
                    folder = QUEUE_DIR / cached_folder_name
                    result_data = load_result(folder) if folder.exists() else None
                    if is_complete_result(result_data):
                        from src.assets import load_assets
                        assets = load_assets(folder)
                        merged_name = assets.get("merged") or assets.get("video_only")
                        path = folder / merged_name if merged_name and (folder / merged_name).exists() else None
                        if not path:
                            video_files = [p for p in folder.glob("*.*") if p.suffix.lower() in (".mp4", ".mkv", ".webm") and not p.name.startswith("_")]
                            if video_files:
                                path = video_files[0]
                        if path and path.exists():
                            t_cache = time.perf_counter() - t_url_pipeline_start
                            out_title = result_data.get("output_name") or path.stem
                            c_segs = result_data.get("segments", [])
                            c_orig = result_data.get("original_segments") or get_result_original_segments(folder)
                            for i, cs in enumerate(c_segs):
                                if not cs.get("original_text") and i < len(c_orig):
                                    cs["original_text"] = c_orig[i].get("text", "")
                            results.append(
                                {
                                    "path": path,
                                    "output_name": out_title,
                                    "url": u,
                                    "info": result_data.get("info", {}),
                                    "texts": c_segs,
                                    "src_lang": result_data.get("source_lang", "es"),
                                    "result": c_orig,
                                    "transcription_lang": result_data.get("source_lang", "es"),
                                    "cached": True,
                                }
                            )
                            found_in_cache = True
                            print(f"♻️ Caché detectada por URL: {out_title} ({t_cache:.2f}s)")

            if found_in_cache:
                continue
            # ---------------------------------------

            path, info = yt(u, vocals_separation=True, force_new=force_reprocess)
            result_json_path = path.parent / "result.json"

            # --- Lógica de Caché por Path ---
            if not force_reprocess:
                cached_data = load_result(path.parent)
                if is_complete_result(cached_data):
                    t_cache = time.perf_counter() - t_url_pipeline_start
                    out_title = cached_data.get("output_name") or info.get("title") or path.stem
                    print(f"♻️ Cargando caché: {path.name}")
                    c_segs = cached_data.get("segments", [])
                    c_orig = cached_data.get("original_segments") or get_result_original_segments(path.parent)
                    for i, cs in enumerate(c_segs):
                        if not cs.get("original_text") and i < len(c_orig):
                            cs["original_text"] = c_orig[i].get("text", "")
                    results.append(
                        {
                            "path": path,
                            "output_name": out_title,
                            "url": u,
                            "info": cached_data.get("info", {}),
                            "texts": c_segs,
                            "src_lang": cached_data.get("source_lang", "es"),
                            "result": c_orig,
                            "transcription_lang": cached_data.get("source_lang", "es"),
                            "cached": True,
                        }
                    )
                    print(f"✅ {out_title} (cargado de caché en {t_cache:.2f}s)")
                    continue
            # -----------------------

            if on_stage:
                try:
                    on_stage(
                        u,
                        "transcribing",
                        "📝 Transcribiendo...",
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
                enable_emotions=enable_emotions,
                initial_emotion_per_sentence=initial_emotion_per_sentence,
                initial_emotion_tag=initial_emotion_tag,
            )
            translated_result = run_res[0]
            output_name = run_res[1]
            original_result = run_res[2]
            source_lang = run_res[3]
            stt_timings = run_res[4]

            from src.assets import load_assets
            existing_assets = load_assets(path.parent)

            # Guardar resultado en JSON y registrar en índice
            result_data = create_result(
                url=u,
                output_name=output_name,
                source_lang=source_lang,
                target_lang=translate_lang if isinstance(translate_lang, str) else None,
                segments=translated_result,
                original_segments=original_result,
                info=info,
                timings={
                    "download": info.get("_download_time", 0.0) if isinstance(info, dict) else 0.0,
                    "stems": info.get("_stems_time", 0.0) if isinstance(info, dict) else 0.0,
                    **stt_timings,
                },
                assets=existing_assets,
            )
            save_result(path.parent, result_data)
            register_url(u, path.parent.name)

            timings = result_data["timings"]

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
                    "src_lang": source_lang,
                    "result": original_result,
                    "transcription_lang": source_lang,
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
        s_sec = text_dict.get("orig_start") if text_dict.get("orig_start") is not None else text_dict.get("start", 0.0)
        e_sec = text_dict.get("orig_end") if text_dict.get("orig_end") is not None else text_dict.get("end", 0.0)

        start = max(0, int(round(float(s_sec) * org_sr)))
        end = min(arr.shape[-1], int(round(float(e_sec) * org_sr)))
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
        result_data = load_result(path.parent)
        if not result_data:
            print(f"⚠️ Saltando {path.stem}: no hay archivo de resultados")
            continue
        texts = result_data.get("original_segments") or result_data.get("segments", [])
        split_audio_sequences(
            audio_path=path.with_name("vocals.wav"),
            texts=texts,
            output_dir=path.parent / "Seqs_src",
        )
