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
    max_gap: float = 1.2,
    target_duration: float = 7.0,
    min_duration: float = 2.0,
    min_sentence_gap: float = 0.40,
    min_clause_gap: float = 0.18,
    min_silence_gap: float = 0.35,
    max_duration: float | None = None,
) -> list[dict]:
    """
    Agrupa palabras en segmentos de longitud natural orientados a target_duration.

    Reglas:
    1. Si la duración acumulada está dentro de target_duration (<= 7s) y alcanza min_duration (>= 2s):
       Corta en signos fuertes (. ! ? ¡ ¿) SI Y SOLO SI el silencio posterior (gap) es >= min_sentence_gap (0.40s).
       Evita falsos positivos en abreviaturas (node.js, Dr., etc.) y frases demasiado cortas.
    2. Si se supera target_duration (> 7s):
       Paso 1: Busca hacia adelante cualquier signo (. ! ? , ; : - —) que tenga un gap posterior >= min_clause_gap (0.18s).
       Paso 2 (sin signos en adelante): Busca el primer gap >= min_silence_gap (0.35s).
              Si ninguno lo supera, elige el mayor gap del tramo.
    """
    if max_duration is not None and target_duration == 7.0:
        target_duration = float(max_duration)

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

    strong_punct = re.compile(r"[.!?¡¿]")
    any_punct = re.compile(r"[.!?,;:—–\-]")

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

    grouped_segments = []
    n = len(all_words)
    start_idx = 0

    while start_idx < n:
        speaker = all_words[start_idx]["speaker"]
        seg_start = all_words[start_idx]["start"]
        chosen_cut_idx = None
        curr = start_idx

        while curr < n:
            # 1. Corte inmediato si cambia el hablante (diarización)
            if curr > start_idx and all_words[curr]["speaker"] != speaker:
                chosen_cut_idx = curr - 1
                break

            # 2. Comprobaciones con la palabra anterior
            if curr > start_idx:
                prev_end = all_words[curr - 1]["end"]
                gap_before_curr = all_words[curr]["start"] - prev_end
                dur_up_to_prev = prev_end - seg_start

                # Corte por silencio largo absoluto (> max_gap, ej. 1.2s)
                if gap_before_curr > max_gap:
                    chosen_cut_idx = curr - 1
                    break

                # [DENTRO DEL TARGET (dur_up_to_prev <= target_duration)]:
                # Corta en punto fuerte SI Y SOLO SI hay silencio real >= min_sentence_gap (0.40s)
                # y al menos min_duration acumulados para evitar microfrases de 1 palabra.
                if dur_up_to_prev <= target_duration and dur_up_to_prev >= min_duration:
                    if strong_punct.search(all_words[curr - 1]["word"]) and gap_before_curr >= min_sentence_gap:
                        chosen_cut_idx = curr - 1
                        break

            # Duración acumulada incluyendo la palabra curr
            dur_curr = all_words[curr]["end"] - seg_start

            # 3. [AL SUPERAR EL TARGET (dur_curr >= target_duration)]:
            if dur_curr >= target_duration:
                # Paso 1: Explorar hacia adelante buscando cualquier signo con gap real >= min_clause_gap
                forward_cut = None
                forward_indices = []
                fwd = curr
                while fwd < n:
                    if all_words[fwd]["speaker"] != speaker:
                        break
                    if fwd > start_idx and (all_words[fwd]["start"] - all_words[fwd - 1]["end"]) > max_gap:
                        break

                    forward_indices.append(fwd)

                    if any_punct.search(all_words[fwd]["word"]):
                        if fwd + 1 < n and all_words[fwd + 1]["speaker"] == speaker:
                            next_gap = all_words[fwd + 1]["start"] - all_words[fwd]["end"]
                        else:
                            next_gap = min_clause_gap

                        if next_gap >= min_clause_gap:
                            forward_cut = fwd
                            break
                    fwd += 1

                if forward_cut is not None:
                    chosen_cut_idx = forward_cut
                    break

                # Paso 2 (Si no hay signos de puntuación en adelante):
                # Cortar en el primer gap >= min_silence_gap (0.35s); si ninguno lo supera, elegir el mayor gap
                first_valid_gap_idx = None
                largest_gap_val = -1.0
                largest_gap_idx = curr

                for f_idx in forward_indices:
                    if f_idx + 1 < n and all_words[f_idx + 1]["speaker"] == speaker:
                        g = all_words[f_idx + 1]["start"] - all_words[f_idx]["end"]
                        if g >= min_silence_gap and first_valid_gap_idx is None:
                            first_valid_gap_idx = f_idx
                        if g > largest_gap_val:
                            largest_gap_val = g
                            largest_gap_idx = f_idx

                if first_valid_gap_idx is not None:
                    chosen_cut_idx = first_valid_gap_idx
                elif largest_gap_idx is not None and largest_gap_idx >= curr:
                    chosen_cut_idx = largest_gap_idx
                else:
                    chosen_cut_idx = curr
                break

            # Si es la última palabra del audio completo
            if curr == n - 1:
                chosen_cut_idx = curr
                break

            curr += 1

        if chosen_cut_idx is None or chosen_cut_idx < start_idx:
            chosen_cut_idx = start_idx

        seg_words = all_words[start_idx : chosen_cut_idx + 1]
        seg = create_segment_from_words(seg_words)
        if seg:
            grouped_segments.append(seg)
        start_idx = chosen_cut_idx + 1

    return grouped_segments


def process_audio(
    whisper_result: Any,
    diarization_result: Any,
    group_segments: bool = True,
    include_words: bool = False,
    max_gap: float = 1.2,
    target_duration: float = 7.0,
    min_duration: float = 2.0,
    max_duration: float | None = None,
) -> list[dict]:
    assigned_data = assign_speakers_by_word(whisper_result, diarization_result)
    if group_segments:
        assigned_data = smart_group_segments_strict(
            assigned_data,
            max_gap=max_gap,
            target_duration=target_duration,
            min_duration=min_duration,
            max_duration=max_duration,
        )
    if not include_words:
        for seg in assigned_data:
            seg.pop("words", None)
    return assigned_data
