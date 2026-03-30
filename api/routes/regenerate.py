"""Regenerate segment and video endpoints."""
import pickle
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from api.job_store import get_job
from api.schemas import RegenerateSegmentRequest, RegenerateVideoRequest, SegmentSchema, ApplySpeedRequest
from api.service import SPEAKER_OPTIONS

router = APIRouter(prefix="/api", tags=["regenerate"])


def _get_video_path_from_job(job_id: str, video_index: int) -> Path:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")
    return Path(videos[video_index]["video_path"])


def _get_video_path_from_path(video_path: str) -> Path:
    """Resolve video path - must be under Queue dir."""
    from src.config import QUEUE_DIR
    folder = QUEUE_DIR.resolve()
    p = Path(video_path).resolve()
    try:
        if not p.is_relative_to(folder):
            raise HTTPException(status_code=400, detail="Ruta de video no permitida")
    except (ValueError, AttributeError):
        if not str(p).startswith(str(folder)):
            raise HTTPException(status_code=400, detail="Ruta de video no permitida")
    if not p.exists():
        raise HTTPException(status_code=404, detail="Video no encontrado")
    return p


@router.post("/regenerate-segment")
async def regenerate_segment(req: RegenerateSegmentRequest):
    """Regenerate a single segment's TTS audio."""
    if req.job_id:
        path = _get_video_path_from_job(req.job_id, req.video_index)
    elif req.video_path:
        path = _get_video_path_from_path(req.video_path)
    else:
        raise HTTPException(status_code=400, detail="Proporciona job_id o video_path")
    return _do_regenerate_segment(
        path, req.seg_idx, req.text, req.start, req.end, req.translate_lang, req.speaker, req.speed
    )


def _do_regenerate_segment(
    path: Path,
    seg_idx: int,
    text: str,
    start: float,
    end: float,
    translate_lang: str | None,
    speaker: str,
    speed: float = 1.0,
):
    from src.pipeline import split_audio_sequences
    from src.audio_utils import clone_voice_segments
    from src.tts import model_tts

    pkl_path = path.with_name("result.pkl")
    if not pkl_path.exists():
        raise HTTPException(status_code=404, detail="result.pkl no encontrado")

    with open(pkl_path, "rb") as f:
        # Carga directa de la nueva estructura de 7 campos (limpia, sin fallbacks)
        texts_original, output_name, url, result, transcription, diarization, info, *extra = pickle.load(f)

    if seg_idx < 1 or seg_idx > len(texts_original):
        raise HTTPException(status_code=400, detail="Índice de segmento inválido")

    t_edit = {
        "start": start,
        "end": end,
        "text": text,
        # Si el usuario mandó un speaker explícito, lo usamos, si no mantenemos el original
        "speaker": speaker if speaker else texts_original[seg_idx - 1].get("speaker", "SPEAKER_00"),
    }
    texts_edited = list(texts_original)
    texts_edited[seg_idx - 1] = t_edit

    split_audio_sequences(path.with_name("vocals.wav"), texts_edited, edit_indices=[seg_idx])

    speaker_audio = SPEAKER_OPTIONS.get(speaker, speaker)
    lang = (
        translate_lang
        if translate_lang and translate_lang != "None"
        else getattr(transcription, "language", None) or "es"
    )

    paths_es, _, _ = clone_voice_segments(
        path,
        texts_edited,
        lang,
        speaker_audio,
        model_tts,
        only_indices=[seg_idx],
        speed=speed,
    )

    if not paths_es:
        raise HTTPException(status_code=500, detail="No se pudo generar el audio")

    with open(pkl_path, "wb") as f:
        pickle.dump((texts_edited, output_name, url, result, transcription, diarization, info), f)

    return FileResponse(paths_es[0], filename=paths_es[0].name, media_type="audio/wav")


@router.post("/apply-speed")
async def apply_speed(req: ApplySpeedRequest):
    """Aplica velocidad a un segmento de audio existente sin regenerar TTS."""
    import torchaudio
    from src.audio_utils import adjust_audio_duration

    path = _get_video_path_from_job(req.job_id, req.video_index)
    seqs_trg_dir = path.parent / "Seqs_trg"
    vocals_src = path.with_name("vocals.wav")
    
    # El nombre del archivo se deduce por convención: vocals_{idx:04d}.wav para src
    # Pero aquí necesitamos el target que ya fue generado una vez: tts_..._seg.wav
    # Lo más seguro es buscarlo en el Seqs_trg según el índice
    possible_files = list(seqs_trg_dir.glob(f"*_{req.seg_idx:04d}.wav"))
    if not possible_files:
        # Intenta tts_*_seg.wav
        possible_files = list(seqs_trg_dir.glob(f"tts_*_{req.seg_idx:04d}.wav"))
        
    if not possible_files:
        raise HTTPException(status_code=404, detail=f"No se encontró el audio del segmento {req.seg_idx}")
    
    audio_path = possible_files[0]
    arr, rate = torchaudio.load(str(audio_path))
    
    # Aplicar la velocidad
    # atempo=1.5 -> target_duration = original_duration / 1.5
    # En adjust_audio_duration pasamos target_duration_samples
    target_samples = int(arr.shape[-1] / req.speed)
    
    # Usamos la lógica de adjust_audio_duration que internamente usa atempo
    arr_new = adjust_audio_duration(arr, target_samples, rate)
    
    torchaudio.save(str(audio_path), arr_new, sample_rate=rate)
    
    return FileResponse(audio_path, filename=audio_path.name, media_type="audio/wav")


@router.post("/regenerate-video")
async def regenerate_video(req: RegenerateVideoRequest):
    """Apply segment edits and re-render the video."""
    import torchaudio

    path = _get_video_path_from_job(req.job_id, req.video_index)
    segments = [s.model_dump() if hasattr(s, "model_dump") else s for s in req.segments]
    pkl_path = path.with_name("result.pkl")
    if not pkl_path.exists():
        raise HTTPException(status_code=404, detail="result.pkl no encontrado")

    with open(pkl_path, "rb") as f:
        # Carga robusta de 7 campos para regeneración de video
        texts_original, output_name, url, result, transcription, diarization, info, *extra = pickle.load(f)

    texts_edited = []
    changed_indices = []
    seg_by_num = {s["seg"]: s for s in segments}
    for idx, t_orig in enumerate(texts_original):
        seg_num = idx + 1
        s = seg_by_num.get(seg_num, {})
        t_edit = {
            "start": float(s.get("start", t_orig.get("start"))),
            "end": float(s.get("end", t_orig.get("end"))),
            "text": str(s.get("text", t_orig.get("text"))),
            # Si el frontend envió el speaker modificado, lo mantenemos; sino fallback al original
            "speaker": s.get("speaker", t_orig.get("speaker", "SPEAKER_00")),
        }
        texts_edited.append(t_edit)
        if str(t_orig) != str(t_edit):
            changed_indices.append(seg_num)

    from src.pipeline import split_audio_sequences
    from src.audio_utils import clone_voice_segments, merge_cloned_audio
    from src.render import render_video
    from src.tts import model_tts

    if changed_indices:
        split_audio_sequences(path.with_name("vocals.wav"), texts_edited, edit_indices=changed_indices)
        speaker_audio = SPEAKER_OPTIONS.get(req.speaker, req.speaker)
        lang = req.translate_lang if req.translate_lang and req.translate_lang != "None" else transcription.language
        clone_voice_segments(
            path,
            texts_edited,
            lang,
            speaker_audio,
            model_tts,
            only_indices=changed_indices,
            slowdown_range=(0.5, 0.8),
            stretch_target_ratio=0.85,
        )

    with open(pkl_path, "wb") as f:
        pickle.dump((texts_edited, output_name, url, result, transcription, diarization, info), f)

    seqs_trg_dir = path.parent / "Seqs_trg"
    all_paths_es = sorted(seqs_trg_dir.glob("*.wav"))
    if not all_paths_es:
        raise HTTPException(status_code=500, detail="No se encontraron segmentos de audio")

    _, freq = torchaudio.load(str(all_paths_es[0]))
    all_times = [int(t["start"] * freq) for t in texts_edited]

    vocals_es_path = path.with_name("vocals_es.wav")
    merged = merge_cloned_audio(path.with_name("vocals.wav"), all_paths_es, all_times, freq)
    torchaudio.save(str(vocals_es_path), merged, freq)

    no_vocals_path = path.with_name("no_vocals.wav")
    if not no_vocals_path.exists():
        raise HTTPException(status_code=404, detail="no_vocals.wav no encontrado")

    output_path = render_video(path, output_name, vocals_es_path, no_vocals_path, output_dir=path.parent)

    return {"output_path": str(output_path), "filename": output_path.name}
