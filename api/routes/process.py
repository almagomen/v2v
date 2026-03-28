"""Process and job status endpoints."""
from fastapi import APIRouter, HTTPException

from api.schemas import (
    ProcessUrlsRequest, ProcessUrlsResponse, JobStatusResponse,
    JobResultResponse, VideoResult, SegmentSchema, JobPollResponse
)
from api.job_store import get_job
from api.service import start_process

router = APIRouter(prefix="/api", tags=["process"])


@router.post("/process-urls", response_model=ProcessUrlsResponse)
def process_urls(req: ProcessUrlsRequest):
    urls = [u.strip() for u in req.urls if u.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="Introduce al menos una URL de YouTube")

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
        raise HTTPException(status_code=400, detail=job.get("error", job.get("message", "Error desconocido")))

    videos = []
    for v in job.get("videos", []):
        output_filename = v.get("output_filename") or f"{v['output_name']}.mp4"
        videos.append(VideoResult(
            index=v["index"],
            output_name=v["output_name"],
            video_path=v["video_path"],
            video_only_path=v.get("video_only_path"),
            output_video_path=v["output_video_path"],
            output_filename=output_filename,
            segments=[SegmentSchema(**s) for s in v["segments"]],
            url=v.get("url", ""),
        ))
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

    # 1. Status
    status_resp = JobStatusResponse(
        job_id=job_id,
        status=job.get("status", "pending"),
        message=job.get("message"),
        progress=job.get("progress", 0),
    )

    # 2. Result (videos)
    videos = []
    for v in job.get("videos", []):
        videos.append(VideoResult(
            index=v["index"],
            output_name=v["output_name"],
            video_path=v["video_path"],
            video_only_path=v.get("video_only_path", ""),
            instrumental_path=v.get("instrumental_path", ""),
            original_audio_path=v.get("original_audio_path", ""),
            vocals_path=v.get("vocals_path", ""),
            segments=[SegmentSchema(**s) for s in v["segments"]],
            url=v.get("url", ""),
        ))
    result_resp = JobResultResponse(
        job_id=job_id,
        status=job.get("status", "done"),
        videos=videos,
        log=job.get("log"),
    )

    return JobPollResponse(
        job_id=job_id,
        status=status_resp,
        log=job.get("log", ""),
        items=job.get("url_states", []),
        result=result_resp
    )
