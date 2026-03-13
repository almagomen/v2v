from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.database import (
    get_session,
    Project,
    VideoClip,
    AudioSegment,
    ProjectStatus,
)
from app.core.config import settings
from app.core.websocket import ws_manager
from app.services.render import RenderService

router = APIRouter()


@router.post("/projects/{project_id}/export")
async def export_project(
    project_id: str,
    session: Session = Depends(get_session),
):
    """
    Renderiza el video final basándose en las ediciones del timeline.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    if project.status != ProjectStatus.READY:
        raise HTTPException(
            status_code=400, detail="Proyecto no está listo para exportar"
        )

    # Obtener clips de video y segmentos de audio
    video_clips = session.exec(
        select(VideoClip).where(VideoClip.project_id == project_id)
    ).all()

    audio_segments = session.exec(
        select(AudioSegment).where(AudioSegment.project_id == project_id)
    ).all()

    if not video_clips or not audio_segments:
        raise HTTPException(
            status_code=400, detail="No hay clips o segmentos para exportar"
        )

    video_path = Path(project.video_path)
    project_dir = settings.QUEUE_DIR / project_id

    # Preparar datos para renderizado
    video_clips_data = [
        {
            "start_original": clip.start_original,
            "end_original": clip.end_original,
            "start_timeline": clip.start_timeline,
            "end_timeline": clip.end_timeline,
        }
        for clip in video_clips
    ]

    audio_segments_data = [
        {
            "start_timeline": seg.start_timeline,
            "end_timeline": seg.end_timeline,
            "audio_path": seg.audio_path,
        }
        for seg in audio_segments
    ]

    # Renderizar en background
    import asyncio

    asyncio.create_task(
        render_in_background(
            project_id=project_id,
            video_path=video_path,
            video_clips=video_clips_data,
            audio_segments=audio_segments_data,
            project_dir=project_dir,
            output_name=project.output_name,
        )
    )

    return {
        "message": "Renderizado iniciado",
        "project_id": project_id,
        "output_name": project.output_name,
    }


async def render_in_background(
    project_id: str,
    video_path: Path,
    video_clips: list[dict],
    audio_segments: list[dict],
    project_dir: Path,
    output_name: str,
):
    """Renderiza el video en background."""
    try:
        output_path = await RenderService.render_timeline_edits(
            project_id=project_id,
            video_path=video_path,
            video_clips=video_clips,
            audio_segments=audio_segments,
            project_dir=project_dir,
            output_name=output_name,
            ws_manager=ws_manager,
        )

        # Actualizar proyecto con el path del video renderizado
        with Session() as session:
            project = session.get(Project, project_id)
            if project:
                project.video_path = str(output_path)
                session.commit()

    except Exception as e:
        await ws_manager.send_error(project_id, f"Error en renderizado: {str(e)}")


@router.get("/projects/{project_id}/download")
async def download_rendered_video(
    project_id: str,
    session: Session = Depends(get_session),
):
    """Obtiene la URL de descarga del video renderizado."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    if not project.video_path:
        raise HTTPException(status_code=400, detail="Video no renderizado")

    video_path = Path(project.video_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Archivo de video no encontrado")

    # En producción, esto podría ser un endpoint de streaming
    # Por ahora, devolvemos la ruta
    return {
        "video_path": str(video_path),
        "video_url": f"/api/files/{project_id}/{video_path.name}",
    }
