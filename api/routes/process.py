"""Process and job status endpoints."""

from fastapi import APIRouter, HTTPException

from api.schemas import (
    ProcessUrlsRequest,
    ProcessUrlsResponse,
    JobStatusResponse,
    JobResultResponse,
    VideoResult,
    SegmentSchema,
    JobPollResponse,
    TokenSettingsRequest,
    TokenSettingsResponse,
)
from api.job_store import get_job
from api.service import start_process

router = APIRouter(prefix="/api", tags=["process"])


@router.post("/process-urls", response_model=ProcessUrlsResponse)
def process_urls(req: ProcessUrlsRequest):
    urls = [u.strip() for u in req.urls if u.strip()]
    if not urls:
        raise HTTPException(
            status_code=400, detail="Introduce al menos una URL de YouTube"
        )

    translate = None if req.translate_lang in ("None", "", None) else req.translate_lang
    job_id = start_process(urls, translate, req.speaker)
    return ProcessUrlsResponse(job_id=job_id, message="Procesamiento iniciado")


@router.get("/job/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return JobStatusResponse(
        job_id=job_id,
        status=job.get("status", "pending"),
        message=job.get("message"),
        progress=job.get("progress", 0),
    )


@router.get("/job/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    if job.get("status") == "error":
        raise HTTPException(
            status_code=400,
            detail=job.get("error", job.get("message", "Error desconocido")),
        )
    if job.get("status") == "interrupted":
        raise HTTPException(
            status_code=410,
            detail="El job fue interrumpido por un reinicio del servidor. Reinicia el proceso.",
        )

    videos = []
    for v in job.get("videos", []):
        videos.append(
            VideoResult(
                index=v["index"],
                output_name=v["output_name"],
                video_path=v["video_path"],
                video_only_path=v.get("video_only_path", ""),
                instrumental_path=v.get("instrumental_path", ""),
                original_audio_path=v.get("original_audio_path", ""),
                vocals_path=v.get("vocals_path", ""),
                segments=[SegmentSchema(**s) for s in v["segments"]],
                url=v.get("url", ""),
            )
        )
    return JobResultResponse(
        job_id=job_id,
        status=job.get("status", "done"),
        videos=videos,
        log=job.get("log"),
    )


@router.get("/job/{job_id}/log")
def get_job_log(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return {"job_id": job_id, "log": job.get("log", "")}


@router.get("/job/{job_id}/poll", response_model=JobPollResponse)
def get_job_poll(job_id: str):
    """Endpoint consolidado para polling."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    status = job.get("status", "pending")

    # 1. Status
    status_resp = JobStatusResponse(
        job_id=job_id,
        status=status,
        message=job.get("message"),
        progress=job.get("progress", 0),
    )

    # 2. Result (videos)
    videos = []
    for v in job.get("videos", []):
        videos.append(
            VideoResult(
                index=v["index"],
                output_name=v["output_name"],
                video_path=v["video_path"],
                video_only_path=v.get("video_only_path", ""),
                instrumental_path=v.get("instrumental_path", ""),
                original_audio_path=v.get("original_audio_path", ""),
                vocals_path=v.get("vocals_path", ""),
                segments=[SegmentSchema(**s) for s in v["segments"]],
                url=v.get("url", ""),
            )
        )
    result_resp = JobResultResponse(
        job_id=job_id,
        status=status,
        videos=videos,
        log=job.get("log"),
    )

    return JobPollResponse(
        job_id=job_id,
        status=status_resp,
        log=job.get("log", ""),
        items=job.get("url_states", []),
        result=result_resp,
    )


@router.get("/jobs/reconcile")
def reconcile_jobs():
    """
    Retorna todos los jobs con estado 'done' o 'interrupted' cargados desde disco.
    Permite al frontend reconstruir el estado después de un reinicio del servidor.
    """
    from api.job_store import _jobs
    from api.job_store import _lock

    with _lock:
        jobs_summary = []
        for job_id, job_data in _jobs.items():
            status = job_data.get("status", "unknown")
            if status in ("done", "interrupted", "error"):
                jobs_summary.append(
                    {
                        "job_id": job_id,
                        "status": status,
                        "message": job_data.get("message", ""),
                        "video_count": len(job_data.get("videos", [])),
                        "videos": job_data.get("videos", []),
                    }
                )

    return {"jobs": jobs_summary}


@router.get("/settings/tokens", response_model=TokenSettingsResponse)
def get_tokens():
    from src.config import get_google_api_key, get_fish_api_key
    return TokenSettingsResponse(
        fish_api_key=get_fish_api_key() or "",
        google_api_key=get_google_api_key() or "",
    )


@router.post("/settings/tokens", response_model=TokenSettingsResponse)
def post_tokens(req: TokenSettingsRequest):
    import os
    from pathlib import Path

    fish_api_val = (req.fish_api_key or "").strip()
    if fish_api_val:
        os.environ["FISH_AUDIO_API_KEY"] = fish_api_val
        os.environ["FISH_API_KEY"] = fish_api_val

    google_api_val = ""
    if req.google_api_key:
        google_api_val = req.google_api_key.strip()
        os.environ["GOOGLE_API_KEY"] = google_api_val

    # Intentar guardar persistente en .env
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    try:
        lines = []
        exists = env_path.exists()
        google_found = False
        fish_found = False

        if exists:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            for i, line in enumerate(lines):
                if line.strip().startswith("FISH_AUDIO_API_KEY="):
                    if fish_api_val:
                        lines[i] = f"FISH_AUDIO_API_KEY={fish_api_val}\n"
                    fish_found = True
                elif line.strip().startswith("GOOGLE_API_KEY="):
                    if google_api_val:
                        lines[i] = f"GOOGLE_API_KEY={google_api_val}\n"
                    google_found = True

        if not fish_found and fish_api_val:
            lines.append(f"FISH_AUDIO_API_KEY={fish_api_val}\n")
        if not google_found and google_api_val:
            lines.append(f"GOOGLE_API_KEY={google_api_val}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception as e:
        print(f"Error escribiendo en .env: {e}")

    return TokenSettingsResponse(
        fish_api_key=fish_api_val or None,
        google_api_key=google_api_val or None,
        message="Configuración de tokens actualizada en caliente",
    )
