"""Pipeline service - runs v2v pipeline and reports progress."""
import io
import sys
import threading
from pathlib import Path

from api.job_store import create_job, update_job, append_log, get_job

# Speaker options from app_gradio
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
        update_job(job_id, status="downloading", message="Descargando y transcribiendo...")

        speaker_audio = SPEAKER_OPTIONS.get(speaker_name, speaker_name)
        results = process_video_queue(urls, translate_lang=translate_lang)

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
                    "output_filename": output_video_path.name,
                    "segments": segments,
                    "url": r.get("url", ""),
                })
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
                "output_filename": output_path.name,
                "segments": segments,
                "url": r.get("url", ""),
            })

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
