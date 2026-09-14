"""
Endpoints para gestionar proyectos procesados y servir archivos.
"""
import os
import pickle
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from api.schemas import ProjectDetail, ProjectSummary, SegmentInfo
from bridge.project_builder import build_opencut_project
from bridge.opencut_schema import OpenCutProject

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_queue_dir() -> Path:
    from src.config import QUEUE_DIR
    return QUEUE_DIR


@router.get("", response_model=list[ProjectSummary])
async def list_projects():
    """Lista todos los proyectos procesados en Queue/."""
    queue_dir = _get_queue_dir()
    projects = []

    for folder in sorted(queue_dir.glob("*")):
        if not folder.is_dir():
            continue

        pkl_path = folder / "result.pkl"
        if not pkl_path.exists():
            continue

        try:
            with open(pkl_path, "rb") as f:
                # Soporte para 6 campos (legacy) y 7 campos (con info de yt-dlp)
                texts, output_name, url, result, transcription, diarization, *extra = pickle.load(f)

            # Buscar video: cualquier .mp4 en la carpeta del proyecto
            video_files = [p for p in folder.glob("*.mp4") if not p.name.startswith("_")]
            has_video = bool(video_files)

            projects.append(ProjectSummary(
                id=folder.name,
                name=output_name,
                url=url,
                video_path=str(video_files[0]) if has_video else None,
                has_video=has_video,
                segment_count=len(texts),
                src_lang=getattr(transcription, "language", None),
                cached=True,
            ))
        except Exception:
            continue

    return projects


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: str):
    """Obtiene los detalles de un proyecto específico."""
    queue_dir = _get_queue_dir()
    folder = queue_dir / project_id

    if not folder.is_dir():
        raise HTTPException(status_code=404, detail=f"Proyecto {project_id} no encontrado")

    pkl_path = folder / "result.pkl"
    if not pkl_path.exists():
        raise HTTPException(status_code=404, detail="result.pkl no encontrado")

    with open(pkl_path, "rb") as f:
        # Soporte para 6 campos (legacy) y 7 campos (con info de yt-dlp)
        texts, output_name, url, result, transcription, diarization, *extra = pickle.load(f)

    segments = [
        SegmentInfo(
            index=i + 1,
            start=t["start"],
            end=t["end"],
            text=t["text"],
            speaker=t.get("speaker"),
        )
        for i, t in enumerate(texts)
    ]

    # Listar archivos disponibles
    files = {}
    for p in folder.iterdir():
        if p.is_file() and p.suffix in (".mp4", ".wav", ".pkl"):
            files[p.name] = f"/api/projects/{project_id}/files/{p.name}"

    # Incluir archivos en subdirectorios (Seqs_src, Seqs_trg)
    for subdir in ("Seqs_src", "Seqs_trg"):
        sub_path = folder / subdir
        if sub_path.is_dir():
            for p in sub_path.iterdir():
                if p.is_file():
                    files[f"{subdir}/{p.name}"] = f"/api/projects/{project_id}/files/{subdir}/{p.name}"

    return ProjectDetail(
        id=project_id,
        name=output_name,
        url=url,
        segments=segments,
        files=files,
        src_lang=getattr(transcription, "language", None),
    )


@router.get("/{project_id}/opencut", response_model=OpenCutProject)
async def get_opencut_project(project_id: str):
    """Genera y devuelve la estructura de proyecto lista para importar en OpenCut."""
    queue_dir = _get_queue_dir()
    folder = queue_dir / project_id

    if not folder.is_dir():
        raise HTTPException(status_code=404, detail=f"Proyecto {project_id} no encontrado")

    try:
        project = build_opencut_project(folder)
        return project
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al construir proyecto OpenCut: {str(e)}")


@router.get("/{project_id}/files/{file_path:path}")
async def get_project_file(project_id: str, file_path: str, request: Request):
    """Sirve un archivo de un proyecto con soporte de Range requests (necesario para <video>)."""
    queue_dir = _get_queue_dir()
    file_full_path = queue_dir / project_id / file_path

    if not file_full_path.exists() or not file_full_path.is_file():
        raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {file_path}")

    # Seguridad: verificar que el path no sale de la carpeta del proyecto
    try:
        file_full_path.resolve().relative_to((queue_dir / project_id).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    media_type = _guess_media_type(file_full_path.suffix)
    file_size = os.path.getsize(str(file_full_path))

    # --- Range request support (necesario para <video> seek en el navegador) ---
    range_header = request.headers.get("range")
    if range_header and file_full_path.suffix.lower() in (".mp4", ".webm", ".wav", ".mp3", ".m4a"):
        try:
            range_val = range_header.strip().replace("bytes=", "")
            start_str, end_str = range_val.split("-")
            start = int(start_str)
            end = int(end_str) if end_str else file_size - 1
            end = min(end, file_size - 1)
            content_length = end - start + 1

            def file_chunk_generator(path: str, start: int, end: int, chunk: int = 65536):
                with open(path, "rb") as f:
                    f.seek(start)
                    remaining = end - start + 1
                    while remaining > 0:
                        data = f.read(min(chunk, remaining))
                        if not data:
                            break
                        remaining -= len(data)
                        yield data

            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Content-Type": media_type,
            }
            return StreamingResponse(
                file_chunk_generator(str(file_full_path), start, end),
                status_code=206,
                headers=headers,
                media_type=media_type,
            )
        except Exception:
            pass  # Fallback a respuesta completa si hay error al parsear el range

    # Respuesta completa con Accept-Ranges para indicar al navegador que soportamos Range
    return FileResponse(
        path=str(file_full_path),
        filename=file_full_path.name,
        media_type=media_type,
        headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)},
    )


def _guess_media_type(suffix: str) -> str:
    """Determina el media type basado en la extensión."""
    return {
        ".mp4": "video/mp4",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".pkl": "application/octet-stream",
        ".json": "application/json",
    }.get(suffix.lower(), "application/octet-stream")
