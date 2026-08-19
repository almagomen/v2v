"""Regenerate segment and apply speed endpoints."""

import pickle
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.job_store import get_job
from api.schemas import (
    RegenerateSegmentRequest,
    ApplySpeedRequest,
    GenerateAudioSegmentRequest,
)
from api.service import SPEAKER_OPTIONS, resolve_speaker_key

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
        path,
        req.seg_idx,
        req.text,
        req.start,
        req.end,
        req.translate_lang,
        req.speaker,
        req.speed,
        req.target_duration,
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
    target_duration: float | None = None,
):
    from src.pipeline import split_audio_sequences
    from src.audio_utils import clone_voice_segments
    from src.tts import model_tts

    pkl_path = path.with_name("result.pkl")
    if not pkl_path.exists():
        raise HTTPException(status_code=404, detail="result.pkl no encontrado")

    with open(pkl_path, "rb") as f:
        # Carga directa de la nueva estructura de 7 campos (limpia, sin fallbacks)
        (
            texts_original,
            output_name,
            url,
            result,
            transcription,
            diarization,
            info,
            *extra,
        ) = pickle.load(f)

    if seg_idx < 1 or seg_idx > len(texts_original):
        raise HTTPException(status_code=400, detail="Índice de segmento inválido")

    t_edit = {
        "start": start,
        "end": end,
        "text": text,
        # Resolvemos siempre a la clave legible del diccionario (ej: 'mrbeast_lmnt')
        # aunque el frontend haya enviado el UUID (ej: 'd47094be-...') como speaker.
        # Esto garantiza que el archivo en disco se llame tts_mrbeast_lmnt_001.wav
        "speaker": resolve_speaker_key(speaker) if speaker else resolve_speaker_key(
            texts_original[seg_idx - 1].get("speaker", "SPEAKER_00")
        ),
    }
    texts_edited = list(texts_original)
    texts_edited[seg_idx - 1] = t_edit

    split_audio_sequences(
        path.with_name("vocals.wav"), texts_edited, edit_indices=[seg_idx]
    )

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
        target_duration=target_duration,
    )

    if not paths_es:
        raise HTTPException(status_code=500, detail="No se pudo generar el audio")

    with open(pkl_path, "wb") as f:
        pickle.dump(
            (texts_edited, output_name, url, result, transcription, diarization, info),
            f,
        )

    return FileResponse(paths_es[0], filename=paths_es[0].name, media_type="audio/wav")


@router.post("/apply-speed")
async def apply_speed(req: ApplySpeedRequest):
    """Aplica velocidad a un segmento de audio existente sin regenerar TTS."""
    import torchaudio
    from src.audio_utils import adjust_audio_duration

    path = _get_video_path_from_job(req.job_id, req.video_index)
    seqs_trg_dir = path.parent / "Seqs_trg"
    vocals_src = path.with_name("vocals.wav")

    from src.assets import get_segment
    
    seg_file_path = get_segment(path.parent, req.seg_idx)
    if not seg_file_path:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró el audio del segmento {req.seg_idx} en los activos",
        )

    # Validamos que de verdad exista en disco
    audio_path = Path(seg_file_path)
    if not audio_path.is_absolute():
        # si se guardó como relativo
        audio_path = path.parent / audio_path

    if not audio_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"El archivo reportado por el manifiesto no existe físicamente: {audio_path.name}",
        )
    
    # Intentamos leer siempre del RAW puro si existe, para no destruir fase ni acumular distorsiones.
    raw_path = audio_path.with_name(f"{audio_path.stem}_raw{audio_path.suffix}")
    if raw_path.exists():
        arr, rate = torchaudio.load(str(raw_path))
    else:
        arr, rate = torchaudio.load(str(audio_path))
        
    source_samples = arr.shape[-1]
    
    # El Frontend calculó req.speed sobre el original o mandó target_duration.
    if req.target_duration is not None and req.target_duration > 0:
        target_samples = int(req.target_duration * rate)
    elif req.speed is not None and req.speed > 0:
        target_samples = int(source_samples / req.speed)
    else:
        raise HTTPException(status_code=400, detail="Debe proporcionar speed o target_duration válido")

    # Aplicar la velocidad usando ajuste seguro de duración
    arr_new = adjust_audio_duration(arr, target_samples, rate)

    torchaudio.save(str(audio_path), arr_new, sample_rate=rate)

    return FileResponse(audio_path, filename=audio_path.name, media_type="audio/wav")


@router.post("/generate-audio-segment")
async def generate_audio_segment(req: GenerateAudioSegmentRequest):
    """Genera un nuevo segmento de audio TTS desde texto sin necesidad de un segmento existente."""
    path = _get_video_path_from_job(req.job_id, req.video_index)

    pkl_path = path.with_name("result.pkl")
    if not pkl_path.exists():
        raise HTTPException(status_code=404, detail="result.pkl no encontrado")

    import pickle

    with open(pkl_path, "rb") as f:
        (
            texts_original,
            output_name,
            url,
            result,
            transcription,
            diarization,
            info,
            *extra,
        ) = pickle.load(f)

    from src.tts import model_tts
    import torchaudio

    speaker_audio = SPEAKER_OPTIONS.get(req.speaker, req.speaker)
    lang = getattr(transcription, "language", None) or "es"
    speaker_key = resolve_speaker_key(req.speaker)
    safe_speaker = speaker_key.replace(" ", "_").replace("/", "_").replace("\\", "_")

    arr, rate = model_tts(req.text, lang, speaker_audio)
    if arr is None or rate is None:
        raise HTTPException(status_code=500, detail="Error en modelo TTS")

    seqs_trg_dir = path.parent / "Seqs_trg"
    seqs_trg_dir.mkdir(exist_ok=True)

    seq_num = 1
    while True:
        proposed_path = seqs_trg_dir / f"gen_{safe_speaker}_{seq_num:03d}.wav"
        if not proposed_path.exists():
            break
        seq_num += 1

    audio_es_path = seqs_trg_dir / f"gen_{safe_speaker}_{seq_num:03d}.wav"
    raw_es_path = seqs_trg_dir / f"gen_{safe_speaker}_{seq_num:03d}_raw.wav"

    torchaudio.save(str(raw_es_path), arr, sample_rate=rate)
    torchaudio.save(str(audio_es_path), arr, sample_rate=rate)

    from src.assets import update_assets
    # Registrar en la raíz del manifiesto porque no tiene clip original en segments
    update_assets(path.parent, **{audio_es_path.name: str(audio_es_path)})

    return FileResponse(audio_es_path, filename=audio_es_path.name, media_type="audio/wav")

@router.get("/segment-speed")
async def get_segment_speed(job_id: str, video_index: int, seg_idx: int):
    """Devuelve la relación de velocidad aplicada (Speed) calculada dinámica y directamente desde disco."""
    try:
        path = _get_video_path_from_job(job_id, video_index)
        from src.assets import get_segment
        seg_file_path = get_segment(path.parent, seg_idx)
        
        if not seg_file_path:
            return {"speed": 1.0}

        import torchaudio
        audio_path = Path(seg_file_path)
        if not audio_path.is_absolute():
            audio_path = path.parent / audio_path

        if not audio_path.exists():
            return {"speed": 1.0}

        raw_path = audio_path.with_name(audio_path.stem + "_raw" + audio_path.suffix)
        if not raw_path.exists():
            return {"speed": 1.0}

        info_current = torchaudio.info(str(audio_path))
        info_raw = torchaudio.info(str(raw_path))
        current_samples = info_current.num_frames
        raw_samples = info_raw.num_frames
        
        if current_samples == 0:
            return {"speed": 1.0}
            
        speed = raw_samples / current_samples
        return {"speed": round(speed, 3)}
    except Exception:
        return {"speed": 1.0}
