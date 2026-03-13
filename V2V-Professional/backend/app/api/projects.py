import uuid
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select
import asyncio

from app.core.database import (
    get_session,
    Project,
    VideoClip,
    AudioSegment,
    ProjectStatus,
)
from app.core.config import settings
from app.core.websocket import ws_manager
from app.schemas import (
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    VideoClipCreate,
    VideoClipUpdate,
    VideoClipResponse,
    AudioSegmentCreate,
    AudioSegmentUpdate,
    AudioSegmentResponse,
    TimelineExportRequest,
)

router = APIRouter()


# WebSocket endpoint
@router.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    await ws_manager.connect(project_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming messages if needed
    except WebSocketDisconnect:
        ws_manager.disconnect(project_id)


# Project endpoints
@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    project_data: ProjectCreate,
    session: Session = Depends(get_session),
):
    """Crea un nuevo proyecto desde una URL de YouTube."""
    project_id = str(uuid.uuid4())

    # Crear directorio del proyecto
    project_dir = settings.QUEUE_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    project = Project(
        id=project_id,
        url=project_data.url,
        output_name=f"project_{project_id[:8]}",
        status=ProjectStatus.PENDING,
    )

    session.add(project)
    session.commit()
    session.refresh(project)

    # Iniciar procesamiento en background
    asyncio.create_task(
        process_project_background(
            project_id,
            project_data.url,
            project_data.translate_lang,
            project_data.speaker_id,
        )
    )

    return project


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(session: Session = Depends(get_session)):
    """Lista todos los proyectos."""
    projects = session.exec(select(Project).order_by(Project.created_at.desc())).all()
    return projects


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, session: Session = Depends(get_session)):
    """Obtiene un proyecto por ID."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return project


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, session: Session = Depends(get_session)):
    """Elimina un proyecto."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    # Eliminar directorio
    project_dir = settings.QUEUE_DIR / project_id
    if project_dir.exists():
        import shutil

        shutil.rmtree(project_dir)

    session.delete(project)
    session.commit()

    return {"message": "Proyecto eliminado"}


# Video Clip endpoints
@router.post("/projects/{project_id}/clips", response_model=VideoClipResponse)
async def create_video_clip(
    project_id: str,
    clip_data: VideoClipCreate,
    session: Session = Depends(get_session),
):
    """Crea un nuevo clip de video."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    clip = VideoClip(**clip_data.dict())
    session.add(clip)
    session.commit()
    session.refresh(clip)

    return clip


@router.patch("/clips/{clip_id}", response_model=VideoClipResponse)
async def update_video_clip(
    clip_id: str,
    clip_update: VideoClipUpdate,
    session: Session = Depends(get_session),
):
    """Actualiza un clip de video."""
    clip = session.get(VideoClip, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip no encontrado")

    for key, value in clip_update.model_dump(exclude_unset=True).items():
        setattr(clip, key, value)

    clip.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(clip)

    return clip


# Audio Segment endpoints
@router.post("/projects/{project_id}/segments", response_model=AudioSegmentResponse)
async def create_audio_segment(
    project_id: str,
    segment_data: AudioSegmentCreate,
    session: Session = Depends(get_session),
):
    """Crea un nuevo segmento de audio."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    segment = AudioSegment(**segment_data.dict())
    session.add(segment)
    session.commit()
    session.refresh(segment)

    return segment


@router.patch("/segments/{segment_id}", response_model=AudioSegmentResponse)
async def update_audio_segment(
    segment_id: str,
    segment_update: AudioSegmentUpdate,
    session: Session = Depends(get_session),
):
    """Actualiza un segmento de audio."""
    segment = session.get(AudioSegment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segmento no encontrado")

    for key, value in segment_update.model_dump(exclude_unset=True).items():
        setattr(segment, key, value)

    # Marcar como dirty si se actualizó el texto o tiempos
    if (
        segment_update.text
        or segment_update.start_timeline
        or segment_update.end_timeline
    ):
        segment.is_dirty = True

    segment.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(segment)

    return segment


@router.post("/segments/{segment_id}/regenerate")
async def regenerate_segment(
    segment_id: str,
    session: Session = Depends(get_session),
):
    """Regenera el audio de un segmento específico."""
    segment = session.get(AudioSegment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segmento no encontrado")

    project = session.get(Project, segment.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    project_dir = settings.QUEUE_DIR / project.id

    # Importar servicio de TTS
    from app.services.tts import TTSService

    audio_path, success = await TTSService.regenerate_segment(
        segment_id=segment_id,
        project_dir=project_dir,
        ws_manager=ws_manager,
        project_id=project.id,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Error al regenerar segmento")

    return {"message": "Segmento regenerado", "audio_path": str(audio_path)}


# Background processing task
async def process_project_background(
    project_id: str,
    url: str,
    translate_lang: str | None,
    speaker_id: str,
):
    """Procesa el proyecto en background."""
    from app.services.download import DownloadService
    from app.services.stt import STTService
    from app.services.tts import TTSService

    project_dir = settings.QUEUE_DIR / project_id

    async with asyncio:
        try:
            # 1. Descargar video
            await ws_manager.send_progress(
                project_id, 0.1, "Descargando video...", "downloading"
            )

            video_path, info = DownloadService.download_video(url, project_dir)
            vocals_path, no_vocals_path = DownloadService.separate_vocals(video_path)

            # Actualizar proyecto
            with Session() as session:
                project = session.get(Project, project_id)
                project.video_path = str(video_path)
                project.vocals_path = str(vocals_path)
                project.no_vocals_path = str(no_vocals_path)
                project.output_name = info.get(
                    "title", f"project_{project_id[:8]}"
                ).replace(" ", "_")
                project.status = ProjectStatus.PROCESSING
                session.commit()

            # 2. Transcribir
            await ws_manager.send_progress(
                project_id, 0.5, "Transcribiendo...", "processing"
            )
            result, language = STTService.transcribe(
                vocals_path, ws_manager, project_id
            )

            # 3. Crear segmentos
            with Session() as session:
                project = session.get(Project, project_id)
                project.source_language = language
                session.commit()

                # Crear un clip de video para todo el video
                video_clip = VideoClip(
                    project_id=project_id,
                    start_original=0,
                    end_original=result[-1]["end"] if result else 0,
                    start_timeline=0,
                    end_timeline=result[-1]["end"] if result else 0,
                    track_index=0,
                    order=0,
                )
                session.add(video_clip)

                # Crear segmentos de audio
                for idx, r in enumerate(result):
                    segment = AudioSegment(
                        project_id=project_id,
                        text=r["text"],
                        speaker_id=r.get("speaker", "SPEAKER_00"),
                        start_original=r["start"],
                        end_original=r["end"],
                        start_timeline=r["start"],
                        end_timeline=r["end"],
                        track_index=1,
                        order=idx,
                    )
                    session.add(segment)

                session.commit()

            # 4. Generar audio para todos los segmentos
            with Session() as session:
                segments = session.exec(
                    select(AudioSegment).where(AudioSegment.project_id == project_id)
                ).all()

                await TTSService.generate_all_segments(
                    segments=segments,
                    project_dir=project_dir,
                    language=translate_lang or language,
                    speaker_id=speaker_id,
                    ws_manager=ws_manager,
                    project_id=project_id,
                )

                # Marcar como generados
                for seg in segments:
                    seg.is_generated = True
                    if seg.audio_path:
                        seg.is_dirty = False
                session.commit()

            # 5. Completar
            with Session() as session:
                project = session.get(Project, project_id)
                project.status = ProjectStatus.READY
                session.commit()

            await ws_manager.send_progress(
                project_id, 1.0, "Proyecto listo", "complete"
            )

        except Exception as e:
            await ws_manager.send_error(project_id, f"Error: {str(e)}")
            with Session() as session:
                project = session.get(Project, project_id)
                project.status = ProjectStatus.ERROR
                session.commit()
