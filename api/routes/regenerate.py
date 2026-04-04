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
        # Si el usuario mandó un speaker explícito, lo usamos, si no mantenemos el original
        "speaker": speaker
        if speaker
        else texts_original[seg_idx - 1].get("speaker", "SPEAKER_00"),
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

    # El nombre del archivo se deduce por convención: vocals_{idx:04d}.wav para src
    # Pero aquí necesitamos el target que ya fue generado una vez: tts_..._seg.wav
    # Lo más seguro es buscarlo en el Seqs_trg según el índice
    possible_files = list(seqs_trg_dir.glob(f"*_{req.seg_idx:03d}.wav"))
    if not possible_files:
        # Intenta tts_*_seg.wav
        possible_files = list(seqs_trg_dir.glob(f"tts_*_{req.seg_idx:03d}.wav"))

    if not possible_files:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró el audio del segmento {req.seg_idx}",
        )

    audio_path = possible_files[0]
    
    # Intentamos leer siempre del RAW puro si existe, para no destruir fase.
    raw_path = audio_path.with_name(f"{audio_path.stem}_raw{audio_path.suffix}")
    if raw_path.exists():
        arr, rate = torchaudio.load(str(raw_path))
    else:
        arr, rate = torchaudio.load(str(audio_path))

    # Aplicar la velocidad
    # atempo=1.5 -> target_duration = original_duration / 1.5
    # En adjust_audio_duration pasamos target_duration_samples
    target_samples = int(arr.shape[-1] / req.speed)

    # Usamos la lógica de adjust_audio_duration que internamente usa atempo
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

    from src.audio_utils import clone_voice_segments
    from src.tts import model_tts

    speaker_audio = SPEAKER_OPTIONS.get(req.speaker, req.speaker)
    lang = getattr(transcription, "language", None) or "es"

    texts_for_tts = [
        {
            "text": req.text,
            "start": 0.0,
            "end": 1.0,
            "speaker": "SPEAKER_00",
        }
    ]

    from src.assets import update_assets

    paths_es, _, _ = clone_voice_segments(
        path,
        texts_for_tts,
        lang,
        speaker_audio,
        model_tts,
        only_indices=[1],
        speed=1.0,
        register=False,
    )

    if not paths_es:
        raise HTTPException(status_code=500, detail="No se pudo generar el audio")

    # Registrar en el manifiesto general con su nombre real para que el renderizador lo encuentre
    # pero sin que colisione con el mapeo de "segments"
    update_assets(path.parent, **{paths_es[0].name: str(paths_es[0])})

    return FileResponse(paths_es[0], filename=paths_es[0].name, media_type="audio/wav")
