"""Segment editor and bulk retranslation endpoints."""

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
from src.result_store import load_result

router = APIRouter(prefix="/api", tags=["segments"])


def _load_result_texts(video_folder: Path) -> tuple[list[dict], list[dict], str | None]:
    """Returns (tts_texts, original_stt_texts, source_lang)."""
    result_data = load_result(video_folder)
    if not result_data:
        raise HTTPException(status_code=404, detail="result.json no encontrado")

    tts_list = result_data.get("segments", [])
    original_list = result_data.get("original_segments", [])
    if not original_list:
        from src.result_store import get_result_original_segments
        original_list = get_result_original_segments(video_folder)
    source_lang = result_data.get("source_lang")

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
    from src.assets import get_segment
    cand = get_segment(folder, seg)
    return cand.name if cand else None


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
    tts_list, original_list, source_lang = _load_result_texts(folder)
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

        # Texto original (lenguaje fuente STT, ej. portugués) preservado fielmente
        original_text = (
            orig_d.get("original_text")
            or orig_d.get("text")
            or tts_d.get("original_text")
            or (js.get("original_text") if i < len(job_segments) else "")
            or ""
        )

        orig_spk = (
            orig_d.get("original_speaker")
            or orig_d.get("speaker")
            or tts_d.get("original_speaker")
            or (js.get("original_speaker") if i < len(job_segments) else None)
            or "SPEAKER_00"
        )

        slot = max(0.0, end - start)
        orig_s = float(orig_d.get("orig_start", orig_d.get("start", tts_d.get("orig_start", tts_d.get("start", start)))))
        orig_e = float(orig_d.get("orig_end", orig_d.get("end", tts_d.get("orig_end", tts_d.get("end", end)))))
        orig_dur = float(orig_d.get("orig_duration", tts_d.get("orig_duration", max(0.0, orig_e - orig_s))))
        seg_ph = tts_d.get("phonemes") or orig_d.get("phonemes") or (js.get("phonemes") if i < len(job_segments) else None)
        rows.append(
            SegmentEditorRow(
                seg=seg_num,
                start=start,
                end=end,
                slot_duration=round(slot, 3),
                orig_start=round(orig_s, 3),
                orig_end=round(orig_e, 3),
                orig_duration=round(orig_dur, 3),
                original_text=original_text,
                tts_text=tts_text,
                speaker=speaker,
                original_speaker=orig_spk,
                filename=_find_tts_filename(folder, seg_num),
                phonemes=seg_ph,
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
    tts_list, original_list, source_lang = _load_result_texts(folder)

    if not source_lang:
        source_lang = "en"

    job = get_job(req.job_id)
    target_lang = req.target_lang
    if not target_lang and job:
        target_lang = job.get("translate_lang")
    if not target_lang or target_lang in ("None", ""):
        # Fallback inteligente: español si el origen no es español, de lo contrario inglés
        target_lang = "es" if source_lang != "es" else "en"

    indices = sorted(set(req.seg_indices))
    sentences: list[str] = []
    valid_indices: list[int] = []
    times_list: list[tuple[float, float]] = []
    meta_list: list[dict] = []

    for seg_idx in indices:
        if seg_idx < 1 or seg_idx > len(original_list):
            continue
        orig_d = _segment_dict_at(original_list, seg_idx - 1)
        text = ""
        if req.custom_texts:
            text = str(req.custom_texts.get(str(seg_idx)) or req.custom_texts.get(seg_idx) or "").strip()
        if not text:
            text = str(orig_d.get("text", "")).strip()
        if not text:
            tts_d = _segment_dict_at(tts_list, seg_idx - 1)
            text = str(tts_d.get("text", "")).strip()
        if text:
            sentences.append(text)
            valid_indices.append(seg_idx)
            s_t = float(orig_d.get("start", 0.0))
            e_t = float(orig_d.get("end", s_t + 2.0))
            times_list.append((s_t, e_t))
            meta_list.append(orig_d)

    if not sentences:
        raise HTTPException(status_code=400, detail="No hay textos para retraducir")

    from src.translation import translate_text_list

    res = translate_text_list(
        sentences,
        target_lang=target_lang,
        source_lang=source_lang,
        times=times_list if len(times_list) == len(sentences) else None,
        segments_meta=meta_list if len(meta_list) == len(sentences) else None,
        return_details=True,
    )
    if not res or not res[0] or len(res[0]) != len(sentences):
        raise HTTPException(status_code=500, detail="Error al retraducir con Gemini")

    translated, phonemes_list = res

    # Actualizar result.json con los nuevos textos y fonemas de los segmentos retraducidos
    try:
        from src.result_store import create_segment_entry, update_result_segments
        for seg_idx, txt, ph, meta in zip(valid_indices, translated, phonemes_list or [], meta_list):
            if 1 <= seg_idx <= len(tts_list):
                curr = tts_list[seg_idx - 1]
                tts_list[seg_idx - 1] = create_segment_entry(
                    seg=seg_idx,
                    start=curr.get("start", meta.get("start", 0.0)),
                    end=curr.get("end", meta.get("end", 0.0)),
                    text=txt,
                    original_text=meta.get("original_text") or curr.get("original_text") or txt,
                    speaker=curr.get("speaker") or meta.get("speaker") or "mrbeast",
                    original_speaker=meta.get("original_speaker") or curr.get("original_speaker") or "SPEAKER_00",
                    phonemes=ph or meta.get("phonemes") or curr.get("phonemes"),
                    extra={
                        k: v for k, v in curr.items()
                        if k not in (
                            "seg", "start", "end", "duration", "text",
                            "original_text", "speaker",
                            "original_speaker", "phonemes"
                        )
                    },
                )
        update_result_segments(folder, tts_list)
    except Exception as e_upd:
        print(f"⚠️ Error actualizando result.json tras retranslate: {e_upd}")

    return RetranslateSegmentsResponse(
        segments=[
            RetranslateSegmentItem(seg=seg, text=txt, phonemes=ph or meta.get("phonemes"))
            for seg, txt, ph, meta in zip(valid_indices, translated, phonemes_list or [None] * len(translated), meta_list)
        ]
    )

