"""Share (Catbox) and ZIP endpoints."""

import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.job_store import get_job
from src.config import TEMP_DIR
from api.routes.render import upload_to_catbox

router = APIRouter(prefix="/api", tags=["share"])


@router.get("/job/{job_id}/share/{video_index}")
def share_to_catbox(job_id: str, video_index: int):
    """Upload video to Catbox and return URL."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")

    video = videos[video_index]

    output_path = None
    for key in ("video_path", "video_only_path", "output_video_path"):
        p = video.get(key)
        if p:
            candidate = Path(p)
            if candidate.exists():
                output_path = candidate
                break

    if output_path is None:
        raise HTTPException(
            status_code=404,
            detail="No se encontró ningún archivo de video para este job. El video puede no haberse procesado aún.",
        )

    try:
        url = upload_to_catbox(output_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir a Catbox: {e}")
    if not url:
        raise HTTPException(
            status_code=500,
            detail="Error al subir a Catbox (curl falló o no devolvió URL).",
        )
    return {"url": url, "filename": output_path.name}


@router.get("/job/{job_id}/zip")
def download_all_zip(job_id: str):
    """Create ZIP with all videos and return it."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    output_paths: list[Path] = []
    videos = job.get("videos", [])

    for video in videos:
        for key in ("video_path", "video_only_path", "output_video_path"):
            p = video.get(key)
            if p:
                candidate = Path(p)
                if candidate.exists() and candidate not in output_paths:
                    output_paths.append(candidate)
                    break

    if not output_paths:
        raise HTTPException(
            status_code=404,
            detail="No hay videos para descargar. Los videos pueden no haberse procesado aún.",
        )

    zip_path = TEMP_DIR / f"videos_inferidos_{job_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in output_paths:
            zf.write(p, arcname=p.name)

    return FileResponse(
        zip_path, filename="videos_inferidos.zip", media_type="application/zip"
    )
