from pathlib import Path
from fastapi import APIRouter, HTTPException

from api.schemas import SpeakerOption, SpeakerMapRequest, SpeakerDetectionResponse
from api.service import SPEAKER_OPTIONS
from api.job_store import get_job, update_job
from api.routes.files import _get_video_folder
from src.result_store import load_result, save_result

router = APIRouter(prefix="/api", tags=["speakers"])


@router.get("/speakers", response_model=list[SpeakerOption])
def get_speakers():
    """Return list of available speaker/voice options."""
    return [SpeakerOption(label=k, value=v) for k, v in SPEAKER_OPTIONS.items()]


@router.get("/job/{job_id}/speakers/{video_index}", response_model=SpeakerDetectionResponse)
def get_video_speakers(job_id: str, video_index: int):
    """Devuelve los speakers diarizados detectados en el video y el mapeo actual de voces."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")

    folder = _get_video_folder(job_id, video_index)
    result_data = load_result(folder) or {}
    segments = result_data.get("segments") or videos[video_index].get("segments") or []
    orig_segments = result_data.get("original_segments") or []

    detected_set: set[str] = set()
    current_map: dict[str, str] = {}

    for s in orig_segments + segments:
        orig = s.get("original_speaker") or s.get("speaker")
        if orig and isinstance(orig, str):
            detected_set.add(orig)

    # Reconstruir mapa de voces asignadas
    for s in segments:
        orig = s.get("original_speaker") or s.get("speaker")
        assigned = s.get("speaker")
        if orig and assigned:
            current_map[orig] = assigned

    detected_list = sorted(list(detected_set)) if detected_set else ["SPEAKER_00"]
    return SpeakerDetectionResponse(
        job_id=job_id,
        video_index=video_index,
        detected_speakers=detected_list,
        speaker_map=current_map,
    )


@router.post("/job/{job_id}/speakers/{video_index}/map", response_model=SpeakerDetectionResponse)
def update_video_speaker_map(job_id: str, video_index: int, req: SpeakerMapRequest):
    """Actualiza el mapeo de speakers diarizados para el video y sincroniza result.json."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")

    folder = _get_video_folder(job_id, video_index)
    result_data = load_result(folder)
    if not result_data:
        raise HTTPException(status_code=404, detail="result.json no encontrado")

    segments = result_data.get("segments", [])
    for s in segments:
        orig = s.get("original_speaker") or s.get("speaker")
        if orig in req.speaker_map:
            s["speaker"] = req.speaker_map[orig]

    save_result(folder, result_data)

    # Actualizar también en memoria del job
    if "segments" in videos[video_index]:
        for s in videos[video_index]["segments"]:
            orig = s.get("original_speaker") or s.get("speaker")
            if orig in req.speaker_map:
                s["speaker"] = req.speaker_map[orig]
        update_job(job_id, videos=videos)

    detected_speakers = sorted(list({
        s.get("original_speaker") or s.get("speaker")
        for s in segments
        if (s.get("original_speaker") or s.get("speaker"))
    }))

    return SpeakerDetectionResponse(
        job_id=job_id,
        video_index=video_index,
        detected_speakers=detected_speakers,
        speaker_map=req.speaker_map,
    )
