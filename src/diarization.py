"""
Diarización de hablantes con Pyannote.
"""
import re
from typing import Any

try:
    import torch
    import torchaudio
    from pyannote.audio import Pipeline
    from pyannote.core import Segment
except ImportError:
    torch = None
    torchaudio = None
    Pipeline = None
    Segment = None

from src.config import DEVICE, DEVICE_SECONDARY, DRIVE_DIR, KAGGLE_INPUT_DIR, get_hf_token
from src.models import get_or_load_model

DIARIZATION_DIR = DRIVE_DIR / "speaker-diarization-community-1" if DRIVE_DIR else None
if not DIARIZATION_DIR and KAGGLE_INPUT_DIR and KAGGLE_INPUT_DIR.exists():
    for cand in [
        KAGGLE_INPUT_DIR / "speaker-diarization-community-1",
        KAGGLE_INPUT_DIR / "speaker_diarization_community_1",
        KAGGLE_INPUT_DIR / "v2v-models" / "speaker-diarization-community-1",
    ]:
        if cand.exists():
            DIARIZATION_DIR = cand
            break


def _load_diarization_model() -> Any:
    pretrained = (
        DIARIZATION_DIR
        if DIARIZATION_DIR and DIARIZATION_DIR.exists()
        else "pyannote/speaker-diarization-3.1"
    )
    token = get_hf_token()
    load_kwargs = {}
    if token and not (DIARIZATION_DIR and DIARIZATION_DIR.exists()):
        load_kwargs["token"] = token

    try:
        model = Pipeline.from_pretrained(pretrained, **load_kwargs)
    except TypeError:
        # Retrocompatibilidad con versiones de pyannote.audio que usan use_auth_token
        if "token" in load_kwargs:
            load_kwargs["use_auth_token"] = load_kwargs.pop("token")
            model = Pipeline.from_pretrained(pretrained, **load_kwargs)
        else:
            raise

    target_dev = DEVICE_SECONDARY if (torch is not None and torch.cuda.is_available()) else DEVICE
    model.to(torch.device(target_dev))
    return model


def get_diarization_model() -> Any:
    return get_or_load_model("community-1", _load_diarization_model)


def speaker_diarization(diarization_model: Any, wav_audio: str, num_speakers: int | None = None) -> Any:
    waveform, sample_rate = torchaudio.load(wav_audio)
    output = diarization_model(
        {"waveform": waveform, "sample_rate": sample_rate},
        num_speakers=num_speakers,
    )
    return output.exclusive_speaker_diarization


def assign_speakers_by_word(whisper_result: Any, diarization: Any) -> list[dict]:
    """Asigna hablantes a cada segmento de Whisper según la diarización."""
    segments_list = whisper_result.segments if hasattr(whisper_result, "segments") else whisper_result
    assigned_segments = []

    for seg in segments_list:
        seg_start = float(seg.start) if hasattr(seg, "start") else seg["start"]
        seg_end = float(seg.end) if hasattr(seg, "end") else seg["end"]
        seg_text = seg.text if hasattr(seg, "text") else seg["text"]
        seg_words = seg.words if hasattr(seg, "words") else seg.get("words", [])

        if not seg_words:
            seg_words = [{"start": seg_start, "end": seg_end, "word": seg_text}]

        speaker_counts: dict[str, float] = {}
        enriched_words = []

        for word in seg_words:
            w_start = float(word["start"] if isinstance(word, dict) else word.start)
            w_end = float(word["end"] if isinstance(word, dict) else word.end)
            w_text = word["word"] if isinstance(word, dict) else word.word

            word_segment = Segment(w_start, w_end)
            turn = diarization.crop(word_segment)
            best_speaker = "UNKNOWN"
            max_overlap = 0.0

            for segment, _, label in turn.itertracks(yield_label=True):
                overlap = segment & word_segment
                if overlap.duration > max_overlap:
                    max_overlap = overlap.duration
                    best_speaker = label

            if best_speaker != "UNKNOWN":
                speaker_counts[best_speaker] = speaker_counts.get(best_speaker, 0) + max_overlap

            enriched_words.append({
                "word": w_text, "start": w_start, "end": w_end, "speaker": best_speaker
            })

        segment_speaker = max(speaker_counts, key=speaker_counts.get) if speaker_counts else "UNKNOWN"
        assigned_segments.append({
            "start": seg_start,
            "end": seg_end,
            "text": seg_text,
            "speaker": segment_speaker,
            "words": enriched_words,
        })

    return assigned_segments


def smart_group_segments_strict(
    assigned_segments: list[dict],
    max_gap: float = 1.5,
    max_duration: float = 10,
) -> list[dict]:
    """Agrupa segmentos priorizando integridad de frase. No corta en comas."""
    if not assigned_segments:
        return []

    all_words = []
    for seg in assigned_segments:
        seg_speaker = seg["speaker"]
        for w in seg["words"]:
            word_copy = w.copy()
            word_copy["speaker"] = seg_speaker
            all_words.append(word_copy)

    if not all_words:
        return []

    grouped_segments = []
    current_words = [all_words[0]]
    strong_punct = re.compile(r"[.!?¡¿]")

    def create_segment_from_words(words_list: list[dict]) -> dict | None:
        if not words_list:
            return None
        raw_text = " ".join([w["word"].strip() for w in words_list])
        clean_text = re.sub(r"\s+([.,!?:;])", r"\1", raw_text)
        return {
            "start": words_list[0]["start"],
            "end": words_list[-1]["end"],
            "text": clean_text,
            "speaker": words_list[0]["speaker"],
            "words": words_list,
        }

    for i in range(1, len(all_words)):
        next_word = all_words[i]
        if not current_words:
            current_words.append(next_word)
            continue

        last_word = current_words[-1]
        gap = next_word["start"] - last_word["end"]
        speaker_changed = next_word["speaker"] != current_words[0]["speaker"]
        gap_too_big = gap > max_gap

        if speaker_changed or gap_too_big:
            seg = create_segment_from_words(current_words)
            if seg:
                grouped_segments.append(seg)
            current_words = [next_word]
            continue

        current_words.append(next_word)
        current_duration = current_words[-1]["end"] - current_words[0]["start"]

        if current_duration > max_duration:
            split_index = -1
            for idx in range(len(current_words) - 1, -1, -1):
                if strong_punct.search(current_words[idx]["word"]):
                    split_index = idx
                    break
            if split_index != -1:
                part_one = current_words[: split_index + 1]
                part_two = current_words[split_index + 1:]
                seg = create_segment_from_words(part_one)
                if seg:
                    grouped_segments.append(seg)
                current_words = part_two

    if current_words:
        seg = create_segment_from_words(current_words)
        if seg:
            grouped_segments.append(seg)

    return grouped_segments


def process_audio(
    whisper_result: Any,
    diarization_result: Any,
    group_segments: bool = True,
    include_words: bool = False,
    max_gap: float = 1.5,
    max_duration: float = 10,
) -> list[dict]:
    assigned_data = assign_speakers_by_word(whisper_result, diarization_result)
    if group_segments:
        assigned_data = smart_group_segments_strict(
            assigned_data, max_gap=max_gap, max_duration=max_duration
        )
    if not include_words:
        for seg in assigned_data:
            seg.pop("words", None)
    return assigned_data
