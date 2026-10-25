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
            print("⚠️ [Fallback Pyannote] Usando 'use_auth_token' por compatibilidad de versión.", flush=True)
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


MAJOR_PUNCT = re.compile(r"[.!?¡¿;:]+$")
CLAUSE_PUNCT = re.compile(r"[,—\-]+|\.{2,}$")
TITLE_ABBREV = re.compile(r"^[A-ZÁÉÍÓÚÑÇÀÈÌÒÙÄËÏÖÜ][a-záéíóúñç]{0,2}\.$")
INTERNAL_DOT = re.compile(r"\w\.\w")


def has_major_punct(word: str) -> bool:
    """Verifica si la palabra termina en signo de fin de oración o pausa mayor (. ! ? ¡ ¿ ; :) excluyendo abreviaturas/iniciales universales."""
    w = word.strip()
    if not w or not MAJOR_PUNCT.search(w):
        return False
    # Iniciales o siglas con puntos internos (ej. U.S., e.g., i.e.)
    if INTERNAL_DOT.search(w):
        return False
    # Abreviatura universal de título de 1-3 letras con mayúscula inicial (ej. Dr., Sr., Mr., St., Av.)
    if TITLE_ABBREV.match(w):
        return False
    return True


def has_clause_punct(word: str) -> bool:
    """Verifica si la palabra termina en signo de cláusula intermedia (, - — ...) excluyendo abreviaturas."""
    w = word.strip()
    if not w:
        return False
    return bool(CLAUSE_PUNCT.search(w))


def count_syllables_approx(text: str) -> int:
    """Estimación rápida de sílabas fonéticas multilingüe (ES/PT/EN/FR/IT), ignorando tags entre corchetes."""
    clean = re.sub(r"\[.*?\]", "", text.lower())
    words = re.findall(r"[a-záéíóúâêîôûãõàèìòùäëïöüñç]+", clean)
    total = 0
    for w in words:
        groups = re.findall(r"[aeiouáéíóúâêîôûãõàèìòùäëïöüy]+", w)
        if len(w) > 3 and w.endswith("e") and not w.endswith(("le", "ee", "ue")):
            syl = max(1, len(groups) - 1)
        else:
            syl = max(1, len(groups))
        total += syl
    return max(1, total)


def smart_group_segments_strict(
    assigned_segments: list[dict],
    hard_gap: float = 1.1,
    min_sentence_gap: float = 0.16,
    min_silence_gap: float = 0.42,
    min_clause_gap: float = 0.30,
    min_duration: float = 2.2,
    max_merge_duration: float = 10.0,
    nonspeech_sections: list[dict] | None = None,
    **kwargs,
) -> list[dict]:
    """
    Agrupa palabras en segmentos prosódicos continuos agnósticos del idioma en dos pasos:
    Paso 1: Corte natural guiado por pausas acústicas reales, respiraciones y signos mayores,
            preservando unidades semánticas fluidas sin cortes artificiales arbitrarios.
    Paso 2: Fusión de micro-segmentos huérfanos (< 2.5s o <= 3 palabras) hacia el vecino
            del mismo hablante con menor separación acústica.
    """
    if not assigned_segments:
        return []

    all_words = []
    for seg in assigned_segments:
        seg_speaker = seg["speaker"]
        seg_words = seg.get("words", [])
        num_w = len(seg_words)
        for w_idx, w in enumerate(seg_words):
            word_copy = w.copy()
            if not word_copy.get("speaker") or word_copy.get("speaker") in ("UNKNOWN", ""):
                word_copy["speaker"] = seg_speaker
            word_copy["is_seg_end"] = (w_idx == num_w - 1)
            all_words.append(word_copy)

    if not all_words:
        return []

    # Suavizado anti-jitter de 1 palabra sobre all_words
    for k in range(1, len(all_words) - 1):
        prev_spk = all_words[k - 1].get("speaker")
        curr_spk = all_words[k].get("speaker")
        next_spk = all_words[k + 1].get("speaker")
        if prev_spk and next_spk and prev_spk == next_spk and curr_spk != prev_spk:
            gap_left = all_words[k]["start"] - all_words[k - 1]["end"]
            gap_right = all_words[k + 1]["start"] - all_words[k]["end"]
            if gap_left < 0.40 and gap_right < 0.40:
                all_words[k]["speaker"] = prev_spk

    def create_segment_from_words(words_list: list[dict]) -> dict | None:
        if not words_list:
            return None
        tokens = [w["word"].strip() for w in words_list]
        raw_text = " ".join(tokens)
        clean_text = re.sub(r"\s+([.,!?:;])", r"\1", raw_text)

        start_t = words_list[0]["start"]
        end_t = words_list[-1]["end"]
        dur = max(0.1, round(end_t - start_t, 3))

        # Cálculo robusto y limpio de pausas internas sumando gaps reales entre palabras contiguas
        internal_pause_time = 0.0
        for idx_w in range(1, len(words_list)):
            gap = words_list[idx_w]["start"] - words_list[idx_w - 1]["end"]
            if gap >= 0.35:
                internal_pause_time += gap

        net_dur = max(0.1, round(dur - internal_pause_time, 3))
        w_count = len(words_list)
        syl_count = count_syllables_approx(clean_text)
        c_count = len(clean_text)
        return {
            "start": start_t,
            "end": end_t,
            "duration": dur,
            "net_speech_duration": net_dur,
            "internal_pause_sec": round(internal_pause_time, 3),
            "text": clean_text,
            "speaker": words_list[0]["speaker"],
            "word_count": w_count,
            "syllable_count": syl_count,
            "char_count": c_count,
            "speech_rate": round(w_count / net_dur, 2) if net_dur > 0 else 0.0,
            "syllable_rate": round(syl_count / net_dur, 2) if net_dur > 0 else 0.0,
            "words": words_list,
        }

    # ─── PASO 1: Corte natural guiado por fronteras acústicas y respiraciones ───
    grouped_segments = []
    current_words = [all_words[0]]
    seg_start = all_words[0]["start"]

    for curr in range(1, len(all_words)):
        curr_word = all_words[curr]
        prev_word = all_words[curr - 1]
        speaker = current_words[0]["speaker"]

        prev_end = prev_word["end"]
        gap_before_curr = curr_word["start"] - prev_end
        dur_up_to_prev = prev_end - seg_start

        should_cut = False

        # 1. Cambio de hablante (diarización estricta)
        if curr_word["speaker"] != speaker:
            should_cut = True
        # 2. Silencio de escena o pausa mayor entre planos/frases
        elif gap_before_curr >= hard_gap:
            should_cut = True
        # 3. Fin de oración mayor (. ! ? ; :) con un mínimo de desarrollo y respiro posterior
        elif has_major_punct(prev_word["word"]):
            if dur_up_to_prev >= min_duration and gap_before_curr >= min_sentence_gap:
                should_cut = True
        # 4. Pausa de respiración acústica real del hablante
        elif dur_up_to_prev >= 3.0 and gap_before_curr >= min_silence_gap:
            should_cut = True
        # 5. Cláusula intermedia (, - — ...) o fin de segmento nativo de Whisper
        elif (has_clause_punct(prev_word["word"]) or prev_word.get("is_seg_end")) and dur_up_to_prev >= 3.2 and gap_before_curr >= min_clause_gap:
            should_cut = True
        # 6. Salvaguarda extrema para evitar enunciados continuos gigantescos (>12s)
        elif dur_up_to_prev >= 12.0 and gap_before_curr >= 0.20:
            should_cut = True

        if should_cut:
            seg = create_segment_from_words(current_words)
            if seg:
                grouped_segments.append(seg)
            current_words = [curr_word]
            seg_start = curr_word["start"]
        else:
            current_words.append(curr_word)

    if current_words:
        seg = create_segment_from_words(current_words)
        if seg:
            grouped_segments.append(seg)

    # ─── PASO 2: Fusión limpia de micro-segmentos (< 2.5s o <= 3 palabras) ───
    if len(grouped_segments) <= 1:
        return grouped_segments

    merged_segments = []
    i = 0
    while i < len(grouped_segments):
        cur_seg = grouped_segments[i]
        is_tiny = cur_seg["duration"] < 2.5 or cur_seg["word_count"] <= 3

        if is_tiny:
            can_merge_prev = False
            gap_prev = float("inf")
            if merged_segments and merged_segments[-1]["speaker"] == cur_seg["speaker"]:
                gap_prev = cur_seg["start"] - merged_segments[-1]["end"]
                if gap_prev <= 0.65 and (merged_segments[-1]["duration"] + cur_seg["duration"]) <= max_merge_duration:
                    can_merge_prev = True

            can_merge_next = False
            gap_next = float("inf")
            if i + 1 < len(grouped_segments) and grouped_segments[i + 1]["speaker"] == cur_seg["speaker"]:
                gap_next = grouped_segments[i + 1]["start"] - cur_seg["end"]
                if gap_next <= 0.65 and (cur_seg["duration"] + grouped_segments[i + 1]["duration"]) <= max_merge_duration:
                    can_merge_next = True

            # Priorizar el vecino con menor separación de silencio
            if can_merge_prev and can_merge_next:
                if gap_prev <= gap_next:
                    prev_seg = merged_segments[-1]
                    comb_words = prev_seg["words"] + cur_seg["words"]
                    merged_segments[-1] = create_segment_from_words(comb_words)
                    i += 1
                    continue
                else:
                    next_seg = grouped_segments[i + 1]
                    comb_words = cur_seg["words"] + next_seg["words"]
                    grouped_segments[i + 1] = create_segment_from_words(comb_words)
                    i += 1
                    continue
            elif can_merge_prev:
                prev_seg = merged_segments[-1]
                comb_words = prev_seg["words"] + cur_seg["words"]
                merged_segments[-1] = create_segment_from_words(comb_words)
                i += 1
                continue
            elif can_merge_next:
                next_seg = grouped_segments[i + 1]
                comb_words = cur_seg["words"] + next_seg["words"]
                grouped_segments[i + 1] = create_segment_from_words(comb_words)
                i += 1
                continue

        merged_segments.append(cur_seg)
        i += 1

    return merged_segments


def process_audio(
    whisper_result: Any,
    diarization_result: Any,
    group_segments: bool = True,
    include_words: bool = False,
    hard_gap: float = 1.1,
    min_sentence_gap: float = 0.16,
    min_silence_gap: float = 0.42,
    min_clause_gap: float = 0.30,
    min_duration: float = 2.2,
    max_merge_duration: float = 10.0,
    nonspeech_sections: list[dict] | None = None,
    **kwargs,
) -> list[dict]:
    assigned_data = assign_speakers_by_word(whisper_result, diarization_result)
    if group_segments:
        assigned_data = smart_group_segments_strict(
            assigned_data,
            hard_gap=hard_gap,
            min_sentence_gap=min_sentence_gap,
            min_silence_gap=min_silence_gap,
            min_clause_gap=min_clause_gap,
            min_duration=min_duration,
            max_merge_duration=max_merge_duration,
            nonspeech_sections=nonspeech_sections,
            **kwargs,
        )
    if not include_words:
        for seg in assigned_data:
            seg.pop("words", None)
    return assigned_data


