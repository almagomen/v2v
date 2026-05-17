"""Segment editor and bulk retranslation endpoints."""

import pickle
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.job_store import get_job
from api.routes.files import _get_video_folder
from api.schemas import (
    SegmentEditorRow,
    SegmentsEditorResponse,
    RetranslateSegmentsRequest,
    RetranslateSegmentsResponse,
    RetranslateSegmentItem,
)

router = APIRouter(prefix="/api", tags=["segments"])


def _load_pkl_texts(video_folder: Path) -> tuple[list[dict], list[dict], str | None]:
    """Returns (tts_texts, original_stt_texts, source_lang)."""
    pkl_path = video_folder / "result.pkl"
    if not pkl_path.exists():
        raise HTTPException(status_code=404, detail="result.pkl no encontrado")

    with open(pkl_path, "rb") as f:
        data = pickle.load(f)

    if not isinstance(data, (tuple, list)) or len(data) < 4:
        raise HTTPException(status_code=500, detail="Formato de result.pkl no reconocido")

    tts_list = data[0] if isinstance(data[0], list) else []
    original_list = data[3] if isinstance(data[3], list) else []

    source_lang = None
    if len(data) > 4 and data[4] is not None:
        transcription = data[4]
        source_lang = getattr(transcription, "language", None)

    return tts_list, original_list, source_lang


def _segment_dict_at(items: list, index: int) -> dict:
    if index < 0 or index >= len(items):
        return {"start": 0.0, "end": 0.0, "text": "", "speaker": None}
    item = items[index]
    if isinstance(item, dict):
        return item
    return {
        "start": float(getattr(item, "start", 0)),
        "end": float(getattr(item, "end", 0)),
        "text": str(getattr(item, "text", "")),
        "speaker": getattr(item, "speaker", None),
    }


def _find_tts_filename(folder: Path, seg: int) -> str | None:
    seqs_trg = folder / "Seqs_trg"
    if not seqs_trg.exists():
        return None
    for candidate in seqs_trg.glob(f"tts_*_{seg:03d}.wav"):
        return candidate.name
    legacy = seqs_trg / f"vocals_{seg:03d}.wav"
    if legacy.exists():
        return legacy.name
    return None


@router.get("/job/{job_id}/segments-editor/{video_index}", response_model=SegmentsEditorResponse)
def get_segments_editor(job_id: str, video_index: int):
    """Original STT vs TTS texts for bulk editing in OpenReel."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")

    folder = _get_video_folder(job_id, video_index)
    tts_list, original_list, source_lang = _load_pkl_texts(folder)
    job_video = videos[video_index]
    job_segments = job_video.get("segments", []) or []

    count = max(len(tts_list), len(original_list), len(job_segments))
    rows: list[SegmentEditorRow] = []

    for i in range(count):
        seg_num = i + 1
        tts_d = _segment_dict_at(tts_list, i)
        orig_d = _segment_dict_at(original_list, i)

        if i < len(job_segments):
            js = job_segments[i]
            start = float(js.get("start", tts_d["start"]))
            end = float(js.get("end", tts_d["end"]))
            tts_text = str(js.get("text", tts_d["text"]))
            speaker = js.get("speaker") or tts_d.get("speaker")
        else:
            start = float(tts_d["start"] or orig_d["start"])
            end = float(tts_d["end"] or orig_d["end"])
            tts_text = str(tts_d["text"])
            speaker = tts_d.get("speaker") or orig_d.get("speaker")

        original_text = str(orig_d["text"])
        if not original_text.strip() and tts_text.strip():
            original_text = tts_text

        slot = max(0.0, end - start)
        rows.append(
            SegmentEditorRow(
                seg=seg_num,
                start=start,
                end=end,
                slot_duration=round(slot, 3),
                original_text=original_text,
                tts_text=tts_text,
                speaker=speaker,
                filename=_find_tts_filename(folder, seg_num),
            )
        )

    translate_lang = job.get("translate_lang")
    if not translate_lang and job.get("items"):
        for item in job["items"]:
            if isinstance(item, dict) and item.get("translate_lang"):
                translate_lang = item["translate_lang"]
                break

    return SegmentsEditorResponse(
        job_id=job_id,
        video_index=video_index,
        source_lang=source_lang,
        target_lang=translate_lang,
        segments=rows,
    )


@router.post("/retranslate-segments", response_model=RetranslateSegmentsResponse)
def retranslate_segments(req: RetranslateSegmentsRequest):
    """Propose new translations for selected segments (does not regenerate audio)."""
    folder = _get_video_folder(req.job_id, req.video_index)
    _tts_list, original_list, source_lang = _load_pkl_texts(folder)

    if not source_lang:
        source_lang = "en"

    job = get_job(req.job_id)
    target_lang = req.target_lang
    if not target_lang and job:
        target_lang = job.get("translate_lang")
    if not target_lang or target_lang in ("None", ""):
        raise HTTPException(
            status_code=400,
            detail="No se pudo inferir el idioma objetivo. Indica target_lang.",
        )

    indices = sorted(set(req.seg_indices))
    sentences: list[str] = []
    valid_indices: list[int] = []

    for seg_idx in indices:
        if seg_idx < 1 or seg_idx > len(original_list):
            continue
        orig_d = _segment_dict_at(original_list, seg_idx - 1)
        text = str(orig_d["text"]).strip()
        if not text:
            tts_d = _segment_dict_at(_tts_list, seg_idx - 1)
            text = str(tts_d["text"]).strip()
        if text:
            sentences.append(text)
            valid_indices.append(seg_idx)

    if not sentences:
        raise HTTPException(status_code=400, detail="No hay textos para retraducir")

    from src.translation import translate_text_list

    translated = translate_text_list(
        sentences,
        target_lang=target_lang,
        source_lang=source_lang,
    )
    if not translated or len(translated) != len(sentences):
        raise HTTPException(status_code=500, detail="Error al retraducir con Gemini")

    return RetranslateSegmentsResponse(
        segments=[
            RetranslateSegmentItem(seg=seg, text=txt)
            for seg, txt in zip(valid_indices, translated)
        ]
    )
