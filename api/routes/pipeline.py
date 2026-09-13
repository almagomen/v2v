"""
Endpoint de procesamiento de videos: inicia el pipeline V2V en background.
"""
import queue
import sys
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter

from api.schemas import (
    JobResponse,
    JobStatus,
    JobStatusResponse,
    ProcessRequest,
    ProjectSummary,
)

router = APIRouter(prefix="/api", tags=["pipeline"])

# ── Estado global de jobs (en memoria, suficiente para Colab) ──────────

_jobs: dict[str, dict] = {}

# Mapeo speaker: nombre en UI -> reference_id Fish Audio o nombre de voz
SPEAKER_OPTIONS = {
    "mrbeast": "49898752f6994bc9a6ef1502214190de",
    "Dionisio Schuyler": "Dionisio Schuyler",
    "en-US-AndrewMultilingualNeural": "en-US-AndrewMultilingualNeural",
    "Chatterbox": "Chatterbox",
}


def _get_job(job_id: str) -> dict:
    """Obtiene un job o lanza 404."""
    if job_id not in _jobs:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Job {job_id} no encontrado")
    return _jobs[job_id]


class _LogCapture:
    """Captura stdout en una lista de logs y una queue para streaming."""
    def __init__(self, log_list: list[str], log_queue: queue.Queue):
        self._logs = log_list
        self._queue = log_queue

    def write(self, s: str) -> int:
        if s and s.strip():
            self._logs.append(s)
            self._queue.put(s)
        return len(s) if s else 0

    def flush(self):
        pass


def _run_pipeline_worker(job_id: str, urls: list[str], translate_lang: str | None, speaker_name: str):
    """Worker que ejecuta el pipeline en un thread separado."""
    job = _jobs[job_id]
    old_stdout = sys.stdout

    try:
        sys.stdout = _LogCapture(job["logs"], job["log_queue"])

        # ── Imports pesados (solo al ejecutar) ──
        from src.config import TEMP_DIR
        from src.pipeline import process_video_queue, split_all_sequences
        from src.audio_utils import clone_voice_segments, merge_cloned_audio
        from src.render import render_video
        from src.tts import model_tts
        import torchaudio

        job["status"] = JobStatus.DOWNLOADING
        job["current_step"] = "Descargando y transcribiendo..."

        speaker_audio = SPEAKER_OPTIONS.get(speaker_name, speaker_name)
        results = process_video_queue(urls, translate_lang=translate_lang)

        if not results:
            job["status"] = JobStatus.FAILED
            job["error"] = "No se pudo procesar ningún video"
            return

        for idx, r in enumerate(results):
            path = r["path"]
            texts = r["texts"]
            output_name = r["output_name"]
            transcription = r["transcription"]
            lang = translate_lang if translate_lang else transcription.language

            output_video_path = path.parent / f"{output_name}.mp4"

            # Generar project summary
            project = ProjectSummary(
                id=path.parent.name,
                name=output_name,
                url=r["url"],
                segment_count=len(texts),
                src_lang=transcription.language,
                cached=r.get("cached", False),
            )

            # Caché check
            if output_video_path.exists():
                project.has_video = True
                project.video_path = str(output_video_path)
                job["results"].append(project)
                continue

            job["status"] = JobStatus.CLONING
            job["current_step"] = f"Clonando voz: {path.stem} [{idx + 1}/{len(results)}]"
            job["progress"] = (idx / len(results)) * 0.8

            # Dividir audio en secuencias
            split_all_sequences([path])

            # Clonado de voz
            paths_es, times, freq = clone_voice_segments(
                path, texts, lang, speaker_audio, model_tts,
                slowdown_range=(0.5, 0.8), stretch_target_ratio=0.85,
            )

            if not paths_es:
                print(f"❌ No se generaron segmentos para {path.stem}")
                continue

            # Merge audio
            vocals_es_path = path.with_name("vocals_es.wav")
            merged = merge_cloned_audio(path.with_name("vocals.wav"), paths_es, times, freq)
            torchaudio.save(str(vocals_es_path), merged, freq)

            no_vocals_path = path.with_name("no_vocals.wav")
            if not no_vocals_path.exists():
                print(f"❌ No se encontró no_vocals.wav para {path.stem}")
                continue

            # Render
            job["status"] = JobStatus.RENDERING
            job["current_step"] = f"Renderizando: {output_name}"
            output_path = render_video(path, output_name, vocals_es_path, no_vocals_path, output_dir=path.parent)

            project.has_video = True
            project.video_path = str(output_path)
            job["results"].append(project)

        job["status"] = JobStatus.COMPLETED
        job["progress"] = 1.0
        job["current_step"] = f"Completado — {len(job['results'])}/{len(results)} videos"

    except Exception as e:
        import traceback
        job["status"] = JobStatus.FAILED
        job["error"] = str(e)
        job["logs"].append(traceback.format_exc())

    finally:
        sys.stdout = old_stdout
        job["log_queue"].put(None)  # Señal de fin


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/process", response_model=JobResponse)
async def process_videos(req: ProcessRequest):
    """Inicia el pipeline de procesamiento de videos en background."""
    job_id = uuid.uuid4().hex[:12]

    translate = None if not req.translate_lang or req.translate_lang == "None" else req.translate_lang

    _jobs[job_id] = {
        "status": JobStatus.QUEUED,
        "progress": 0.0,
        "current_step": "En cola...",
        "logs": [],
        "log_queue": queue.Queue(),
        "results": [],
        "error": None,
        "thread": None,
    }

    thread = threading.Thread(
        target=_run_pipeline_worker,
        args=(job_id, req.urls, translate, req.speaker),
        daemon=True,
    )
    _jobs[job_id]["thread"] = thread
    thread.start()

    return JobResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        message=f"Pipeline iniciado para {len(req.urls)} URL(s)",
    )


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Obtiene el estado actual de un job de procesamiento."""
    job = _get_job(job_id)
    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        current_step=job["current_step"],
        logs=job["logs"][-50:],  # Últimos 50 logs
        results=job["results"],
        error=job["error"],
    )


@router.get("/speakers")
async def list_speakers():
    """Lista los speakers disponibles."""
    return {"speakers": list(SPEAKER_OPTIONS.keys())}
