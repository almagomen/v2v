import io
import os
import tarfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from api.job_store import get_job

router = APIRouter(prefix="/api", tags=["files"])


def _safe_filename(name: str) -> bool:
    """Reject dangerous filenames and prevent common security issues."""
    # No permitimos subir de nivel con nombres que empiecen por punto o contengan separadores.
    return not (name.startswith(".") or "/" in name or "\\" in name) and len(name) < 256


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

    # Aseguramos que el path resuelto esté dentro de la carpeta permitida (seguridad real)
    base_dir = folder.resolve()
    file_path = (base_dir / filename).resolve()

    if not str(file_path).startswith(str(base_dir)):
        raise HTTPException(status_code=403, detail="Acceso denegado")

    if not file_path.exists() or not file_path.is_file():
        seqs_file = (base_dir / "Seqs_trg" / filename).resolve()
        if seqs_file.exists() and seqs_file.is_file():
            return FileResponse(seqs_file, filename=filename)
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

    WAVs are generated under `<video_folder>/Seqs_trg/tts_{speaker}_{NNNN}.wav`.
    Also supports legacy `vocals_XXXX.wav` format for backwards compatibility.
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

        # Buscar primero el formato nuevo: tts_{speaker}_{NNNN}.wav
        wav_path = None
        filename = None
        for candidate in seqs_trg.glob(f"tts_*_{seg:03d}.wav"):
            wav_path = candidate
            filename = candidate.name
            break

        # Fallback al formato legacy: vocals_NNN.wav
        if wav_path is None:
            legacy = seqs_trg / f"vocals_{seg:03d}.wav"
            if legacy.exists():
                wav_path = legacy
                filename = legacy.name

        if wav_path is None:
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
    """Serve a single WAV segment by seg index (1-based).

    Supports both formats: tts_{speaker}_{NNNN}.wav and vocals_NNNN.wav
    """
    if seg <= 0 or seg > 999:
        raise HTTPException(status_code=400, detail="Segmento inválido")
    folder = _get_video_folder(job_id, video_index)
    seqs_trg = folder / "Seqs_trg"

    # Buscar primero formato nuevo
    for candidate in seqs_trg.glob(f"tts_*_{seg:03d}.wav"):
        return FileResponse(candidate, filename=candidate.name, media_type="audio/wav")

    # Fallback formato legacy
    filename = f"vocals_{seg:03d}.wav"
    file_path = seqs_trg / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path, filename=filename, media_type="audio/wav")

    raise HTTPException(status_code=404, detail="Archivo no encontrado")


@router.get("/job/{job_id}/audio-segments-tar/{video_index}")
def serve_audio_segments_tar(job_id: str, video_index: int):
    """Empaqueta todos los segmentos de audio TTS de un video en un stream TAR ultrarrápido (1 sola petición HTTP)."""
    folder = _get_video_folder(job_id, video_index)
    seqs_trg = folder / "Seqs_trg"
    if not seqs_trg.exists() or not seqs_trg.is_dir():
        raise HTTPException(status_code=404, detail="Carpeta Seqs_trg no encontrada")

    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        for f in sorted(seqs_trg.glob("*.wav")):
            if f.is_file() and f.stat().st_size > 0:
                tar.add(f, arcname=f.name)

    tar_bytes = tar_stream.getvalue()
    if not tar_bytes:
        raise HTTPException(status_code=404, detail="No hay segmentos WAV disponibles para empaquetar")

    return Response(
        content=tar_bytes,
        media_type="application/x-tar",
        headers={
            "Content-Disposition": f'attachment; filename="audio_segments_{video_index}.tar"'
        },
    )
