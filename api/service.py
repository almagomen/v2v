"""Pipeline service - runs v2v pipeline and reports progress."""
import io
import sys
import time
import threading
from pathlib import Path

from api.job_store import create_job, update_job, append_log, get_job
from src.assets import load_assets
from src.result_store import load_result, save_result, update_result_segments, create_segment_entry

SPEAKER_OPTIONS = {
    "mrbeast": "49898752f6994bc9a6ef1502214190de",
    "default_fish": "",
}

# Lookup inverso: value/UUID → clave legible del diccionario
# Permite que aunque el frontend envíe el UUID, el archivo en disco use el nombre legible.
_SPEAKER_VALUE_TO_KEY: dict[str, str] = {v: k for k, v in SPEAKER_OPTIONS.items() if v}


def resolve_speaker_key(speaker_input: str) -> str:
    """Devuelve la clave legible del diccionario para un speaker.
    
    Acepta tanto la clave directa ('mrbeast') como el valor/UUID
    ('49898752f6994bc9a6ef1502214190de') y devuelve siempre la clave legible para nombrar archivos.
    """
    # Primero intenta lookup inverso por value/UUID
    if speaker_input in _SPEAKER_VALUE_TO_KEY:
        return _SPEAKER_VALUE_TO_KEY[speaker_input]
    # Si ya es la clave directa, la devuelve tal cual
    if speaker_input in SPEAKER_OPTIONS:
        return speaker_input
    # Fallback: devuelve el input sanitizado
    return speaker_input


class JobLogWriter(io.TextIOBase):
    """Redirects stdout to job log and mirrors to the real terminal stream."""

    def __init__(self, job_id: str, real_stream=None):
        self._job_id = job_id
        self._real_stream = real_stream

    def write(self, s: str) -> int:
        if s:
            append_log(self._job_id, s)
            if self._real_stream:
                try:
                    self._real_stream.write(s)
                    self._real_stream.flush()
                except Exception:
                    pass
        return len(s)

    def flush(self) -> None:
        if self._real_stream:
            try:
                self._real_stream.flush()
            except Exception:
                pass


def _run_pipeline(
    job_id: str,
    urls: list[str],
    translate_lang: str | None,
    speaker_name: str,
    emotion: str | None = None,
    force_reprocess: bool = False,
    speaker_map: dict[str, str] | None = None,
    enable_emotions: bool = True,
) -> None:
    """Run pipeline with stdout redirected to job log."""
    from src.pipeline import process_video_queue, split_all_sequences
    from src.audio_utils import clone_voice_segments
    from src.tts import model_tts

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    try:
        sys.stdout = JobLogWriter(job_id, real_stream=old_stdout)
        sys.stderr = JobLogWriter(job_id, real_stream=old_stderr)
        # Inicializar estados por URL
        update_job(
            job_id,
            status="downloading",
            message="Descargando y transcribiendo...",
            url_states=[{"url": u, "status": "pending", "message": ""} for u in urls],
        )

        def set_url_state(url: str, status: str, message: str = "", **extra):
            job = get_job(job_id) or {}
            states = job.get("url_states") or []
            updated = []
            found = False
            for s in states:
                if s.get("url") == url:
                    found = True
                    ns = {**s, "status": status, "message": message, **extra}
                    updated.append(ns)
                else:
                    updated.append(s)
            if not found:
                updated.append({"url": url, "status": status, "message": message, **extra})
            update_job(job_id, url_states=updated)

        speaker_audio = SPEAKER_OPTIONS.get(speaker_name, speaker_name)
        videos_data = []

        def build_entry(idx: int, path: Path, output_name: str, segs: list, assets: dict, url: str) -> dict:
            """Construye la entrada de video usando sólo el manifiesto de activos."""
            return {
                "index": idx,
                "output_name": output_name,
                "video_path": str(path),
                "video_only_path": assets.get("video_only") or "",
                "instrumental_path": assets.get("no_vocals") or "",
                "original_audio_path": assets.get("audio_only") or "",
                "vocals_path": assets.get("vocals") or "",
                "segments": segs,
                "url": url,
            }

        t_all_start = time.perf_counter()
        for idx, u in enumerate(urls):
            t_link_start = time.perf_counter()
            print(f"\n🚀 [Link {idx + 1}/{len(urls)}] Descargando: {u}")
            res_list = process_video_queue(
                [u],
                translate_lang=translate_lang,
                on_stage=lambda u, st, msg: set_url_state(u, st, msg),
                current_idx=idx + 1,
                total_count=len(urls),
                force_reprocess=force_reprocess,
                enable_emotions=enable_emotions,
            )

            if not res_list:
                set_url_state(u, "error", "Error en descarga/transcripción")
                continue

            r = res_list[0]
            path = r["path"]
            texts = r["texts"]
            output_name = f"{idx + 1}. {r['output_name']}"
            lang = translate_lang if translate_lang else r.get("src_lang", "es")

            # Leer activos deterministas desde el manifiesto
            assets = load_assets(path.parent)

            orig_title = (r.get("info") or {}).get("title") or path.stem

            def make_segments(texts_list: list) -> list:
                return [
                    create_segment_entry(
                        seg=t.get("seg", i + 1),
                        start=t["start"],
                        end=t["end"],
                        text=t["text"],
                        original_text=t.get("original_text", ""),
                        speaker=t.get("speaker", speaker_name),
                        original_speaker=t.get("original_speaker") or t.get("speaker") or "SPEAKER_00",
                        phonemes=t.get("phonemes"),
                        internal_pause_sec=t.get("internal_pause_sec"),
                    )
                    for i, t in enumerate(texts_list)
                ]

            set_url_state(r.get("url", ""), "tts", "TTS:", index=idx, output_name=output_name, original_title=orig_title)

            # ── Caché: el job ya fue procesado antes ──────────────────────────────
            # Detectamos si los segmentos TTS ya existen como señal de caché completo.
            seqs_trg = path.parent / "Seqs_trg"
            already_done = seqs_trg.exists() and (
                any(seqs_trg.glob("tts_*.wav")) or any(seqs_trg.glob("vocals_*.wav"))
            )

            if already_done:
                segments = make_segments(texts)
                videos_data.append(build_entry(idx, path, output_name, segments, assets, r.get("url", "")))
                update_job(job_id, videos=videos_data, progress=(idx + 0.5) / len(urls))
                set_url_state(r.get("url", ""), "done", f"Listo (cache): {output_name}", index=idx, output_name=output_name, original_title=orig_title)
                
                # Pre-caching del paquete TAR en disco para entrega instantánea vía Cloudflare
                try:
                    from api.routes.files import ensure_audio_segments_tar, ensure_src_audio_segments_tar
                    ensure_audio_segments_tar(path.parent)
                    ensure_src_audio_segments_tar(path.parent)
                except Exception:
                    pass

                t_link_total = time.perf_counter() - t_link_start
                print("=" * 60)
                print(f"⏱️ RESUMEN DE TIEMPOS [Link {idx + 1}/{len(urls)}]: {output_name}")
                print(f"• Estado: ♻️ Cargado completamente de caché")
                print(f"🏁 TIEMPO TOTAL LINK: {t_link_total:.2f}s")
                print("=" * 60)
                continue

            # ── Nuevo proceso ─────────────────────────────────────────────────────
            update_job(job_id, status="tts", message=f"Clonando voz: {path.stem} [{idx + 1}/{len(urls)}]")
            
            t0_split = time.perf_counter()
            split_all_sequences([path])
            t_split = time.perf_counter() - t0_split
            print(f"⏱️ [Corte de Secuencias] Completado en {t_split:.1f}s")

            # Preservar el tag 'original_speaker' devuelto por la diarización (ej: SPEAKER_00)
            # y asignar la voz correspondiente según speaker_map o speaker_name por defecto.
            for t in texts:
                orig_spk = t.get("original_speaker") or t.get("speaker") or "SPEAKER_00"
                t["original_speaker"] = orig_spk
                if speaker_map and orig_spk in speaker_map:
                    t["speaker"] = speaker_map[orig_spk]
                else:
                    t["speaker"] = speaker_name

            # Fallback opcional si se especificó una emoción inicial global legacy
            if emotion and emotion != "none":
                clean_tag = emotion if emotion.startswith("[") else f"[{emotion}]"
                for t in texts:
                    current_txt = t.get("text", "").strip()
                    has_bracket_tag = current_txt.startswith("[") and "]" in current_txt.split(maxsplit=1)[0]
                    if not has_bracket_tag and not t.get("emotion"):
                        t["text"] = f"{clean_tag} {current_txt}"
                        t["emotion"] = emotion.strip("[]")

            print("⚡ TTS:")
            t0_tts = time.perf_counter()
            paths_es, _times, _freq = clone_voice_segments(
                path, texts, lang, speaker_audio, model_tts,
                slowdown_range=(0.40, 0.99), stretch_target_ratio=1.0,
                speaker_map=speaker_map,
                source_lang=r.get("src_lang", "pt"),
            )
            t_tts = time.perf_counter() - t0_tts
            print(f"⏱️ [Síntesis TTS (Fish Audio)] Completada en {t_tts:.1f}s ({len(paths_es)} audios generados)\n")

            if not paths_es:
                set_url_state(r.get("url", ""), "error", "Error en TTS")
                continue

            # Guardar segmentos actualizados (con emociones y duraciones TTS) — una sola escritura
            update_result_segments(path.parent, texts)

            # Pre-empaquetado anticipado en background del TAR de segmentos para entrega instantánea vía Cloudflare
            try:
                t0_tar = time.perf_counter()
                from api.routes.files import ensure_audio_segments_tar, ensure_src_audio_segments_tar
                tar_file = ensure_audio_segments_tar(path.parent)
                tar_src_file = ensure_src_audio_segments_tar(path.parent)
                t_tar = time.perf_counter() - t0_tar
                if tar_file:
                    sz_mb = tar_file.stat().st_size / (1024 * 1024)
                    print(f"📦 [Pre-caching TAR] {len(paths_es)} segmentos empaquetados en {t_tar:.2f}s ({sz_mb:.1f}MB)")
                if tar_src_file:
                    sz_src_mb = tar_src_file.stat().st_size / (1024 * 1024)
                    print(f"📦 [Pre-caching TAR Orig] Segmentos originales empaquetados ({sz_src_mb:.1f}MB)")
            except Exception as e:
                print(f"⚠️ Error en pre-caching TAR: {e}")

            # El pipeline termina aquí. El render se hace desde Colab Export.
            # Cargar los activos base del video (rutas relativas limpias).
            assets = load_assets(path.parent)
            segments = make_segments(texts)
            videos_data.append(build_entry(idx, path, output_name, segments, assets, r.get("url", "")))
            update_job(job_id, videos=videos_data, progress=(idx + 1.0) / len(urls))
            set_url_state(r.get("url", ""), "done", f"Listo: {output_name}", index=idx, output_name=output_name, original_title=orig_title)

            t_link_total = time.perf_counter() - t_link_start
            mins = int(t_link_total // 60)
            secs = int(t_link_total % 60)
            fmt_total = f"{t_link_total:.1f}s ({mins}m {secs:02d}s)" if mins > 0 else f"{t_link_total:.1f}s"

            link_timings = r.get("timings", {})
            t_dl = link_timings.get("download", 0.0)
            t_stems = link_timings.get("stems", 0.0)
            t_whisper = link_timings.get("whisper", 0.0)
            t_diar = link_timings.get("diarization", 0.0)
            t_trans = link_timings.get("translation", 0.0)
            t_title = link_timings.get("title", 0.0)

            print("=" * 60)
            print(f"⏱️ RESUMEN DE TIEMPOS [Link {idx + 1}/{len(urls)}]: {output_name}")
            if t_dl > 0:
                print(f"• 📥 Descarga: {t_dl:.1f}s")
            if t_stems > 0:
                print(f"• 🎵 Separación: {t_stems:.1f}s")
            if t_whisper > 0:
                print(f"• 📝 Transcripción: {t_whisper:.1f}s")
            if t_diar > 0:
                print(f"• 👥 Diarización: {t_diar:.1f}s")
            if t_trans > 0:
                print(f"• 🌐 Traducción: {t_trans:.1f}s ({len(texts)} segmentos)")
            if t_title > 0:
                print(f"• ✨ Título Viral: {t_title:.1f}s")
            print(f"• ✂️ Corte secuencias: {t_split:.1f}s")
            print(f"• 🗣️ TTS: {t_tts:.1f}s ({len(paths_es)} segmentos)")
            print(f"🏁 TIEMPO TOTAL: {fmt_total}")
            print("=" * 60 + "\n")

        if len(urls) > 1 and videos_data:
            t_total_all = time.perf_counter() - t_all_start
            mins_all = int(t_total_all // 60)
            secs_all = int(t_total_all % 60)
            fmt_all = f"{t_total_all:.1f}s ({mins_all}m {secs_all:02d}s)" if mins_all > 0 else f"{t_total_all:.1f}s"
            print("=" * 60)
            print(f"🏁 RESUMEN TOTAL: {len(videos_data)} videos completados")
            print(f"🏁 TIEMPO TOTAL ACUMULADO: {fmt_all}")
            print("=" * 60 + "\n")

        if not videos_data:
            update_job(job_id, status="error", message="No se pudo procesar ningún video.", error="No results")
            return

        update_job(
            job_id,
            status="done",
            message=f"Completado: {len(videos_data)} videos",
            output_paths=[v["video_path"] for v in videos_data],
            videos=videos_data,
            progress=1.0,
        )
    except Exception as e:
        import traceback
        append_log(job_id, traceback.format_exc())
        update_job(job_id, status="error", message=str(e), error=str(e))
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def start_process(
    urls: list[str],
    translate_lang: str | None,
    speaker_name: str,
    emotion: str | None = None,
    force_reprocess: bool = False,
    speaker_map: dict[str, str] | None = None,
    enable_emotions: bool = True,
) -> str:
    """Start pipeline in background, return job_id."""
    job_id = create_job()
    thread = threading.Thread(
        target=_run_pipeline,
        args=(
            job_id,
            urls,
            translate_lang,
            speaker_name,
            emotion,
            force_reprocess,
            speaker_map,
            enable_emotions,
        ),
    )
    thread.start()
    return job_id
