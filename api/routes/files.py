"""File serving endpoints."""
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.job_store import get_job

router = APIRouter(prefix="/api", tags=["files"])


def _safe_filename(name: str) -> bool:
    """Reject path traversal in filename."""
    return ".." not in name and "/" not in name and "\\" not in name and len(name) < 256


def _get_video_folder(job_id: str, video_index: int) -> Path:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")
    video_path = Path(videos[video_index]["video_path"])
    return video_path.parent


def _get_video_output_path(job_id: str, video_index: int) -> Path:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")

    # Preferimos output_video_path (lo que se renderizó), evitando depender de filename
    # para caracteres largos/Unicode en la URL.
    out = videos[video_index].get("output_video_path") or videos[video_index].get("video_path")
    if not out:
        raise HTTPException(status_code=404, detail="Output no encontrado")
    return Path(out)


@router.get("/job/{job_id}/files/{video_index}/{filename}")
def serve_file(job_id: str, video_index: int, filename: str):
    """Serve a file from the job's video folder."""
    if not _safe_filename(filename):
        raise HTTPException(status_code=400, detail="Nombre de archivo no permitido")
    folder = _get_video_folder(job_id, video_index)
    file_path = folder / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(file_path, filename=filename)


@router.get("/job/{job_id}/files/{video_index}")
def serve_file_by_index(job_id: str, video_index: int):
    """Serve el MP4 renderizado usando el path guardado en el job.

    Esto evita fallos 404 cuando el frontend pasa un `filename` muy largo o con
    caracteres que no coinciden exactamente con el nombre real del archivo.
    """
    file_path = _get_video_output_path(job_id, video_index)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(file_path, filename=file_path.name)
