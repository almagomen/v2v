"""Regenerate segment and apply speed endpoints."""

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
from src.result_store import load_result, save_result, update_result_segments

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
        temperature=req.temperature,
        top_p=req.top_p,
        repetition_penalty=req.repetition_penalty,
        volume=req.volume,
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
    temperature: float = 0.7,
    top_p: float = 0.7,
    repetition_penalty: float = 1.2,
    volume: float = 0.0,
):
    from src.pipeline import split_audio_sequences
    from src.audio_utils import clone_voice_segments
    from src.tts import model_tts

    result_data = load_result(path.parent)
    if not result_data:
        raise HTTPException(status_code=404, detail="result.json no encontrado")

    texts_original = result_data.get("segments", [])
    source_lang = result_data.get("source_lang", "es")

    if seg_idx < 1 or seg_idx > len(texts_original):
        raise HTTPException(status_code=400, detail="Índice de segmento inválido")

    t_edit = {
        "start": start,
        "end": end,
        "text": text,
        # Resolvemos siempre a la clave legible del diccionario (ej: 'mrbeast')
        # aunque el frontend haya enviado el ID de Fish Audio como speaker.
        # Esto garantiza que el archivo en disco se llame tts_mrbeast_001.wav
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
        else source_lang or "es"
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
        temperature=temperature,
        top_p=top_p,
        repetition_penalty=repetition_penalty,
        volume=volume,
    )

    if not paths_es:
        raise HTTPException(status_code=500, detail="No se pudo generar el audio")

    # Guardar segmentos actualizados en result.json
    update_result_segments(path.parent, texts_edited)

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

    # Actualizar end del segmento en result.json
    result_data = load_result(path.parent)
    if result_data:
        try:
            texts_list = result_data.get("segments", [])
            if 1 <= req.seg_idx <= len(texts_list):
                new_dur = arr_new.shape[-1] / rate
                texts_list[req.seg_idx - 1]["end"] = round(texts_list[req.seg_idx - 1]["start"] + new_dur, 3)
                texts_list[req.seg_idx - 1]["duration"] = round(new_dur, 3)
                update_result_segments(path.parent, texts_list)
        except Exception as e:
            print(f"⚠️ Error actualizando result.json tras apply-speed: {e}")

    return FileResponse(audio_path, filename=audio_path.name, media_type="audio/wav")


@router.post("/generate-audio-segment")
async def generate_audio_segment(req: GenerateAudioSegmentRequest):
    """Genera un nuevo segmento de audio TTS desde texto y lo registra como segmento N+1."""
    if req.job_id:
        path = _get_video_path_from_job(req.job_id, req.video_index)
    elif req.video_path:
        path = _get_video_path_from_path(req.video_path)
    else:
        raise HTTPException(status_code=400, detail="Proporciona job_id o video_path")

    result_data = load_result(path.parent)
    if not result_data:
        raise HTTPException(status_code=404, detail="result.json no encontrado")

    texts_original = list(result_data.get("segments", []))

    from src.tts import model_tts
    from src.audio_utils import adjust_audio_duration
    import torchaudio

    speaker_audio = SPEAKER_OPTIONS.get(req.speaker, req.speaker)
    lang = result_data.get("source_lang") or "es"
    speaker_key = resolve_speaker_key(req.speaker)
    safe_speaker = speaker_key.replace(" ", "_").replace("/", "_").replace("\\", "_")

    arr, rate = model_tts(
        req.text,
        lang,
        speaker_audio,
        temperature=req.temperature,
        top_p=req.top_p,
        repetition_penalty=req.repetition_penalty,
        volume=req.volume,
    )
    if arr is None or rate is None:
        raise HTTPException(status_code=500, detail="Error en modelo TTS")

    seqs_trg_dir = path.parent / "Seqs_trg"
    seqs_trg_dir.mkdir(exist_ok=True)

    # El nuevo segmento es N + 1 con respecto a texts_original
    new_seg_idx = len(texts_original) + 1

    audio_es_path = seqs_trg_dir / f"tts_{safe_speaker}_{new_seg_idx:03d}.wav"
    raw_es_path = seqs_trg_dir / f"tts_{safe_speaker}_{new_seg_idx:03d}_raw.wav"

    from src.audio_utils import adjust_audio_duration

    # Guardar siempre el RAW sin ajustes
    torchaudio.save(str(raw_es_path), arr, sample_rate=rate)

    # Aplicar velocidad si es diferente de 1.0
    if req.speed and req.speed > 0 and abs(req.speed - 1.0) > 0.01:
        source_samples = arr.shape[-1]
        target_samples = int(source_samples / req.speed)
        arr = adjust_audio_duration(arr, target_samples, rate)

    torchaudio.save(str(audio_es_path), arr, sample_rate=rate)

    duration = float(arr.shape[-1]) / float(rate)

    # Registrar el nuevo segmento en result.json al final (N + 1)
    new_segment = {
        "start": round(float(req.start or 0.0), 3),
        "end": round(float(req.start or 0.0) + duration, 3),
        "text": req.text,
        "speaker": speaker_key,
    }
    texts_original.append(new_segment)
    update_result_segments(path.parent, texts_original)


    # Sincronizar en memoria con el job si existe
    if req.job_id:
        job = get_job(req.job_id)
        if job and "videos" in job and 0 <= req.video_index < len(job["videos"]):
            job_segments = job["videos"][req.video_index].setdefault("segments", [])
            job_segments.append({
                "seg": new_seg_idx,
                "start": new_segment["start"],
                "end": new_segment["end"],
                "text": new_segment["text"],
                "speaker": new_segment["speaker"],
            })

    headers = {
        "X-Seg-Idx": str(new_seg_idx),
        "X-Audio-Duration": str(round(duration, 3)),
        "X-Audio-Filename": audio_es_path.name,
        "Access-Control-Expose-Headers": "X-Seg-Idx, X-Audio-Duration, X-Audio-Filename",
    }

    return FileResponse(
        audio_es_path,
        filename=audio_es_path.name,
        media_type="audio/wav",
        headers=headers,
    )

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

        def _get_samples(p):
            try:
                import wave
                with wave.open(str(p), "rb") as wf:
                    return wf.getnframes()
            except Exception:
                pass
            try:
                import soundfile as sf
                return sf.info(str(p)).frames
            except Exception:
                pass
            try:
                if torchaudio is not None and hasattr(torchaudio, "info"):
                    return torchaudio.info(str(p)).num_frames
            except Exception:
                pass
            try:
                if torchaudio is not None:
                    return torchaudio.load(str(p))[0].shape[-1]
            except Exception:
                pass
            return 0

        current_samples = _get_samples(audio_path)
        raw_samples = _get_samples(raw_path)
        
        if current_samples == 0:
            return {"speed": 1.0}
            
        speed = raw_samples / current_samples
        return {"speed": round(speed, 3)}
    except Exception:
        return {"speed": 1.0}
