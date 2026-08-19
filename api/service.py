"""Pipeline service - runs v2v pipeline and reports progress."""
import io
import sys
import threading
from pathlib import Path

from api.job_store import create_job, update_job, append_log, get_job
from src.assets import load_assets

SPEAKER_OPTIONS = {
    "mrbeast_lmnt": "d47094be-9814-4323-9000-e735e04d8732",
    "warrick_lmnt": "warrick",
    "Dionisio Schuyler": "Dionisio Schuyler",
    "en-US-AndrewMultilingualNeural": "en-US-AndrewMultilingualNeural",
    "Chatterbox": "Chatterbox",
}

# Lookup inverso: value/UUID → clave legible del diccionario
# Permite que aunque el frontend envíe el UUID, el archivo en disco use el nombre legible.
_SPEAKER_VALUE_TO_KEY: dict[str, str] = {v: k for k, v in SPEAKER_OPTIONS.items()}


def resolve_speaker_key(speaker_input: str) -> str:
    """Devuelve la clave legible del diccionario para un speaker.
    
    Acepta tanto la clave directa ('mrbeast_lmnt') como el valor/UUID
    ('d47094be-...') y devuelve siempre la clave legible para nombrar archivos.
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
    """Redirects stdout to job log."""

    def __init__(self, job_id: str):
        self._job_id = job_id

    def write(self, s: str) -> int:
        if s:
            append_log(self._job_id, s)
        return len(s)

    def flush(self) -> None:
        pass


def _run_pipeline(job_id: str, urls: list[str], translate_lang: str | None, speaker_name: str) -> None:
    """Run pipeline with stdout redirected to job log."""
    from src.pipeline import process_video_queue, split_all_sequences
    from src.audio_utils import clone_voice_segments
    from src.tts import model_tts

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    try:
        sys.stdout = sys.stderr = JobLogWriter(job_id)
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

        for idx, u in enumerate(urls):
            res_list = process_video_queue(
                [u],
                translate_lang=translate_lang,
                on_stage=lambda u, st, msg: set_url_state(u, st, msg),
                current_idx=idx + 1,
                total_count=len(urls),
            )

            if not res_list:
                set_url_state(u, "error", "Error en descarga/transcripción")
                continue

            r = res_list[0]
            path = r["path"]
            texts = r["texts"]
            output_name = f"{idx + 1}. {r['output_name']}"
            transcription = r["transcription"]
            lang = translate_lang if translate_lang else getattr(transcription, "language", "es")

            # Leer activos deterministas desde el manifiesto
            assets = load_assets(path.parent)

            def make_segments(texts_list: list) -> list:
                return [
                    {
                        "seg": i + 1,
                        "start": t["start"],
                        "end": t["end"],
                        "text": t["text"],
                        "speaker": t.get("speaker", speaker_name),
                    }
                    for i, t in enumerate(texts_list)
                ]

            set_url_state(r.get("url", ""), "tts", "TTS:", index=idx, output_name=output_name)

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
                set_url_state(r.get("url", ""), "done", f"Listo (cache): {output_name}", index=idx, output_name=output_name)
                continue

            # ── Nuevo proceso ─────────────────────────────────────────────────────
            update_job(job_id, status="tts", message=f"Clonando voz: {path.stem} [{idx + 1}/{len(urls)}]")
            split_all_sequences([path])

            # ESTANDARIZACIÓN: Sobre-escribimos el tag 'speaker' devuelto por la diarizacion 
            # (ej: SPEAKER_00) con el nombre standard del diccionario preasignado para el pipeline.
            # Esto soluciona que archivos nazcan dispares entre Frontend y Filesystem.
            for t in texts:
                t["speaker"] = speaker_name

            print("⚡ TTS:")
            paths_es, _times, _freq = clone_voice_segments(
                path, texts, lang, speaker_audio, model_tts,
                slowdown_range=(0.5, 0.8), stretch_target_ratio=0.85,
            )
            print("\n")

            if not paths_es:
                set_url_state(r.get("url", ""), "error", "Error en TTS")
                continue

            # El pipeline termina aquí. El render se hace desde Colab Export.
            # Recargar el manifiesto (register_segment lo actualizó iterativamente).
            assets = load_assets(path.parent)
            segments = make_segments(texts)
            videos_data.append(build_entry(idx, path, output_name, segments, assets, r.get("url", "")))
            update_job(job_id, videos=videos_data, progress=(idx + 1.0) / len(urls))
            set_url_state(r.get("url", ""), "done", f"Listo: {output_name}", index=idx, output_name=output_name)

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


def start_process(urls: list[str], translate_lang: str | None, speaker_name: str) -> str:
    """Start pipeline in background, return job_id."""
    job_id = create_job()
    thread = threading.Thread(
        target=_run_pipeline,
        args=(job_id, urls, translate_lang, speaker_name),
    )
    thread.start()
    return job_id
