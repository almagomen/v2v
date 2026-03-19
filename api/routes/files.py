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

    # Preferimos video_only_path (sin audio) para pegar en timeline con TTS por segmentos.
    # Luego fallback a output_video_path (render) y al video_path original.
    out = (
        videos[video_index].get("video_only_path")
        or videos[video_index].get("output_video_path")
        or videos[video_index].get("video_path")
    )
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


@router.get("/job/{job_id}/audio-segments/{video_index}")
def list_audio_segments(job_id: str, video_index: int):
    """List audio segment WAVs for a job/video.

    WAVs are generated under `<video_folder>/Seqs_trg/vocals_XXXX.wav`.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")

    folder = _get_video_folder(job_id, video_index)
    seqs_trg = folder / "Seqs_trg"
    segments = videos[video_index].get("segments", []) or []

    items = []
    for s in segments:
        try:
            seg = int(s.get("seg"))
        except Exception:
            continue
        filename = f"vocals_{seg:04d}.wav"
        wav_path = seqs_trg / filename
        if not wav_path.exists():
            # No listamos segmentos sin archivo (evita 404 en frontend).
            continue
        items.append(
            {
                "seg": seg,
                "start": s.get("start", 0.0),
                "end": s.get("end", 0.0),
                "speaker": s.get("speaker") or "",
                "filename": filename,
            }
        )
    return items


@router.get("/job/{job_id}/audio-segments/{video_index}/{seg}")
def serve_audio_segment(job_id: str, video_index: int, seg: int):
    """Serve a single WAV segment by seg index (1-based)."""
    if seg <= 0 or seg > 9999:
        raise HTTPException(status_code=400, detail="Segmento inválido")
    folder = _get_video_folder(job_id, video_index)
    seqs_trg = folder / "Seqs_trg"
    filename = f"vocals_{seg:04d}.wav"
    file_path = seqs_trg / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(file_path, filename=filename, media_type="audio/wav")
