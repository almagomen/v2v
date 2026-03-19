"""Pipeline service - runs v2v pipeline and reports progress."""
import io
import sys
import threading
from pathlib import Path

from api.job_store import create_job, update_job, append_log, get_job

SPEAKER_OPTIONS = {
    "mrbeast_lmnt": "d47094be-9814-4323-9000-e735e04d8732",
    "Dionisio Schuyler": "Dionisio Schuyler",
    "en-US-AndrewMultilingualNeural": "en-US-AndrewMultilingualNeural",
    "Chatterbox": "Chatterbox",
}


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
    from src.audio_utils import clone_voice_segments, merge_cloned_audio
    from src.render import render_video
    from src.tts import model_tts
    import torchaudio

    old_stdout = sys.stdout
    try:
        sys.stdout = JobLogWriter(job_id)
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
        results = process_video_queue(
            urls,
            translate_lang=translate_lang,
            on_stage=lambda u, st, msg: set_url_state(u, st, msg),
        )

        if not results:
            update_job(job_id, status="error", message="No se pudo procesar ningún video.", error="No results")
            return

        output_paths: list[Path] = []
        videos_data = []

        for idx, r in enumerate(results):
            path = r["path"]
            texts = r["texts"]
            output_name = r["output_name"]
            transcription = r["transcription"]
            lang = translate_lang if translate_lang else transcription.language
            output_video_path = path.parent / f"{output_name}.mp4"
            # Preferimos el bestvideo que yt-dlp ya descargó (sin audio) si está disponible.
            info = r.get("info") or {}
            v2v_paths = info.get("_v2v_paths") if isinstance(info, dict) else {}
            vonly = (v2v_paths or {}).get("video_only") if isinstance(v2v_paths, dict) else None
            video_only_path = Path(vonly) if vonly else path.with_name(f"{path.stem}_video{path.suffix}")

            set_url_state(r.get("url", ""), "tts", f"TTS/segmentos: {output_name}", index=idx, output_name=output_name)
            if output_video_path.exists():
                output_paths.append(output_video_path)
                segments = [
                    {"seg": i + 1, "start": t["start"], "end": t["end"], "text": t["text"], "speaker": t.get("speaker")}
                    for i, t in enumerate(texts)
                ]
                videos_data.append({
                    "index": idx,
                    "output_name": output_name,
                    "video_path": str(path),
                    "output_video_path": str(output_video_path),
                    "video_only_path": str(video_only_path) if video_only_path.exists() else "",
                    "output_filename": output_video_path.name,
                    "segments": segments,
                    "url": r.get("url", ""),
                })
                set_url_state(r.get("url", ""), "done", f"Listo (cache): {output_name}", index=idx, output_name=output_name)
                continue

            update_job(job_id, status="tts", message=f"Clonando voz: {path.stem} [{idx + 1}/{len(results)}]")
            split_all_sequences([path])

            paths_es, times, freq = clone_voice_segments(
                path, texts, lang, speaker_audio, model_tts,
                slowdown_range=(0.5, 0.8), stretch_target_ratio=0.85,
            )

            if not paths_es:
                continue

            vocals_es_path = path.with_name("vocals_es.wav")
            merged = merge_cloned_audio(path.with_name("vocals.wav"), paths_es, times, freq)
            torchaudio.save(str(vocals_es_path), merged, freq)

            no_vocals_path = path.with_name("no_vocals.wav")
            if not no_vocals_path.exists():
                continue

            # En este punto ya existen Seqs_trg/vocals_XXXX.wav, así que el frontend puede importar audios.
            set_url_state(r.get("url", ""), "audio_ready", "Audios listos para importar", index=idx, output_name=output_name)

            update_job(job_id, status="rendering", message=f"Renderizando video {idx + 1}...")
            output_path = render_video(path, output_name, vocals_es_path, no_vocals_path, output_dir=path.parent)
            output_paths.append(output_path)

            segments = [
                {"seg": i + 1, "start": t["start"], "end": t["end"], "text": t["text"], "speaker": t.get("speaker")}
                for i, t in enumerate(texts)
            ]
            videos_data.append({
                "index": idx,
                "output_name": output_name,
                "video_path": str(path),
                "output_video_path": str(output_path),
                "video_only_path": str(video_only_path) if video_only_path.exists() else "",
                "output_filename": output_path.name,
                "segments": segments,
                "url": r.get("url", ""),
            })
            set_url_state(r.get("url", ""), "done", f"Listo: {output_name}", index=idx, output_name=output_name)

        update_job(
            job_id,
            status="done",
            message=f"Completado: {len(output_paths)} videos",
            output_paths=[str(p) for p in output_paths],
            videos=videos_data,
            progress=1.0,
        )
    except Exception as e:
        import traceback
        append_log(job_id, traceback.format_exc())
        update_job(job_id, status="error", message=str(e), error=str(e))
    finally:
        sys.stdout = old_stdout


def start_process(urls: list[str], translate_lang: str | None, speaker_name: str) -> str:
    """Start pipeline in background, return job_id."""
    job_id = create_job()
    thread = threading.Thread(
        target=_run_pipeline,
        args=(job_id, urls, translate_lang, speaker_name),
    )
    thread.start()
    return job_id
