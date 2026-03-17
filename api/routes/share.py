"""Share (Catbox) and ZIP endpoints."""
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.job_store import get_job
from src.config import TEMP_DIR
from src.render import upload_to_catbox

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
    output_path = Path(videos[video_index]["output_video_path"])
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Video no encontrado")
    url = upload_to_catbox(output_path)
    if not url:
        raise HTTPException(status_code=500, detail="Error al subir a Catbox")
    return {"url": url}


@router.get("/job/{job_id}/zip")
def download_all_zip(job_id: str):
    """Create ZIP with all videos and return it."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    output_paths = [Path(p) for p in job.get("output_paths", []) if Path(p).exists()]
    if not output_paths:
        raise HTTPException(status_code=404, detail="No hay videos para descargar")

    zip_path = TEMP_DIR / "videos_inferidos.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in output_paths:
            zf.write(p, arcname=p.name)

    return FileResponse(zip_path, filename="videos_inferidos.zip", media_type="application/zip")
