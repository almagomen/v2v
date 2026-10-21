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


MAJOR_PUNCT = re.compile(r"[.!?¡¿;:]+$")
CLAUSE_PUNCT = re.compile(r"[,—\-]+|\.{2,}$")
ABBREVIATIONS = {
    "dr.", "dra.", "sr.", "sra.", "mr.", "mrs.", "ms.", "prof.", "etc.", "vs.", "ex.", "pág.", "vol.", "inc.", "corp."
}
DANGLING_CONNECTORS = {
    # Conectores y preposiciones
    "de", "del", "da", "do", "das", "dos", "e", "y", "and", "ou", "o", "u",
    "a", "el", "la", "los", "las", "the", "un", "una", "unos", "unas", "um", "uma",
    "em", "en", "in", "on", "at", "na", "no", "nas", "nos", "para", "por",
    "pra", "pro", "for", "to", "que", "that", "se", "si", "if", "com", "con",
    "with", "como", "as", "mas", "pero", "but", "sin", "sem", "without",
    "ao", "aos", "à", "às", "or",
    # Demostrativos y relativos incompletos
    "este", "esta", "estes", "estas", "esse", "essa", "esses", "essas",
    "aquele", "aquela", "esto", "eso", "aquello", "aqui", "aquí", "aí", "ahí",
    "onde", "donde", "cujo", "cuja", "cuyo", "cuya",
    # Modificadores / Intensificadores que dejan la frase trunca
    "totalmente", "completamente", "bastante", "muito", "muy", "más", "mais",
    "menos", "tan", "tão", "tanto", "tanta", "apenas", "solo", "somente",
    # Verbos copulativos / auxiliares colgantes
    "é", "es", "foi", "fue", "era", "vai", "va", "vamos", "foram", "serão",
    "ser", "estar", "ir", "ter", "tener", "haver", "haber",
}


def clean_word_token(word: str) -> str:
    return re.sub(r"[^\wáéíóúâêîôûãõàèìòùäëïöüñçÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÄËÏÖÜÑÇ]", "", word).lower()


def is_dangling_word(word: str) -> bool:
    """Detecta si la palabra es un conector débil (preposición, artículo, conjunción o modificador incompleto) que no debe quedar suelto al final."""
    token = clean_word_token(word)
    return token in DANGLING_CONNECTORS


def has_major_punct(word: str) -> bool:
    """Verifica si la palabra termina en signo de fin de oración o pausa mayor (. ! ? ¡ ¿ ; :) excluyendo decimales y abreviaturas."""
    w = word.strip()
    if not w or w.lower() in ABBREVIATIONS:
        return False
    return bool(MAJOR_PUNCT.search(w))


def has_clause_punct(word: str) -> bool:
    """Verifica si la palabra termina en signo de cláusula intermedia (, - — ...) excluyendo abreviaturas."""
    w = word.strip()
    if not w or w.lower() in ABBREVIATIONS:
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
    target_duration: float | None = None,
    min_duration: float = 3.0,
    max_duration: float | None = None,
    hard_gap: float = 1.4,
    max_gap: float = 0.85,
    min_sentence_gap: float = 0.20,
    min_silence_gap: float = 0.48,
) -> list[dict]:
    """
    Agrupa palabras en segmentos prosódicos puramente acústicos y gramaticales (sin corte por comas).

    Reglas de cohesión y flujo:
    1. Cero límites artificiales de tiempo:
       - No se fuerza ningún corte por reloj (max_duration/target_duration son None por defecto).
       - Si el hablante expresa una idea continua sin respirar, se respeta intacta.
    2. Pausas acústicas duras:
       - Si gap > hard_gap (1.4s): Silencio de escena o pausa prolongada -> Corta siempre si no es conector.
    3. Detección de respiros y pausas naturales (>= min_duration 3.0s):
       - Si concluye una oración mayor (. ! ? ; :) con respiro (gap >= min_sentence_gap 0.20s), corta de inmediato.
       - Si el hablante toma un respiro acústico real (gap >= min_silence_gap 0.48s), corta de inmediato.
       - Si hay un silencio estándar (gap > max_gap 0.85s) sobre palabra léxica, corta de inmediato.
    4. Sin cortes artificiales por comas o guiones:
       - Las comas fluyen naturalmente dentro de las oraciones sin trocear frases compuestas.
    5. Absorción y sanado de micro-segmentos huérfanos (< 3.2s con pausas <= 0.45s).
    """

    if not assigned_segments:
        return []

    all_words = []
    for seg in assigned_segments:
        seg_speaker = seg["speaker"]
        for w in seg.get("words", []):
            word_copy = w.copy()
            word_copy["speaker"] = seg_speaker
            all_words.append(word_copy)

    if not all_words:
        return []

    def create_segment_from_words(words_list: list[dict]) -> dict | None:
        if not words_list:
            return None
        tokens = []
        internal_pause_time = 0.0
        for idx_w, w in enumerate(words_list):
            w_str = w["word"].strip()
            if idx_w > 0:
                gap = w["start"] - words_list[idx_w - 1]["end"]
                if gap >= 0.32:
                    internal_pause_time += gap
                    tokens.append("[break]")
            tokens.append(w_str)

        raw_text = " ".join(tokens)
        clean_text = re.sub(r"\s+([.,!?:;])", r"\1", raw_text)
        start_t = words_list[0]["start"]
        end_t = words_list[-1]["end"]
        dur = max(0.1, round(end_t - start_t, 3))
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

    grouped_segments = []
    n = len(all_words)
    start_idx = 0

    while start_idx < n:
        speaker = all_words[start_idx]["speaker"]
        seg_start = all_words[start_idx]["start"]
        chosen_cut_idx = None
        curr = start_idx

        while curr < n:
            # 1. Corte inmediato si cambia el interlocutor (diarización estricta)
            if curr > start_idx and all_words[curr]["speaker"] != speaker:
                chosen_cut_idx = curr - 1
                break

            # 2. Comprobaciones con la palabra anterior
            if curr > start_idx:
                prev_end = all_words[curr - 1]["end"]
                gap_before_curr = all_words[curr]["start"] - prev_end
                dur_up_to_prev = prev_end - seg_start
                prev_word = all_words[curr - 1]["word"]

                # A. Silencio duro (> hard_gap, ej. 2.2s):
                if gap_before_curr > hard_gap:
                    if is_dangling_word(prev_word):
                        # Retroceder buscando la última palabra no-dangling dentro del segmento actual
                        back = curr - 1
                        found_safe = False
                        while back > start_idx:
                            if not is_dangling_word(all_words[back - 1]["word"]):
                                chosen_cut_idx = back - 1
                                found_safe = True
                                break
                            back -= 1
                        if found_safe:
                            break
                        # Si no hay palabra segura previa, no cortar aquí sobre el conector huérfano
                    else:
                        chosen_cut_idx = curr - 1
                        break

                # B. Condiciones de corte tras alcanzar min_duration (>= 3.0s):
                if dur_up_to_prev >= min_duration and not is_dangling_word(prev_word):
                    # 1. Fin de oración mayor ([. ! ? ¡ ¿ ; :]) con respiro posterior
                    if has_major_punct(prev_word) and gap_before_curr >= min_sentence_gap:
                        chosen_cut_idx = curr - 1
                        break

                    # 2. Pausa acústica de respiración real (gap >= min_silence_gap, ej. 0.48s)
                    if gap_before_curr >= min_silence_gap:
                        chosen_cut_idx = curr - 1
                        break

                    # 3. Silencio estándar mayor que max_gap (ej. 0.85s)
                    if gap_before_curr > max_gap:
                        chosen_cut_idx = curr - 1
                        break


            # Duración acumulada incluyendo palabra curr
            dur_curr = all_words[curr]["end"] - seg_start

            # 3. Superado el target_duration (solo si fue configurado explícitamente): búsqueda prospectiva prosódica
            if target_duration is not None and dur_curr >= target_duration:
                fwd = curr
                best_major_idx = None
                best_clause_idx = None
                best_breath_idx = None
                largest_gap_val = -1.0
                largest_gap_idx = curr

                while fwd < n:
                    if all_words[fwd]["speaker"] != speaker:
                        break
                    if fwd > start_idx and (all_words[fwd]["start"] - all_words[fwd - 1]["end"]) > hard_gap:
                        break

                    f_dur = all_words[fwd]["end"] - seg_start
                    f_word = all_words[fwd]["word"]

                    if fwd + 1 < n and all_words[fwd + 1]["speaker"] == speaker:
                        next_g = all_words[fwd + 1]["start"] - all_words[fwd]["end"]
                    else:
                        next_g = min_silence_gap

                    if next_g > largest_gap_val:
                        largest_gap_val = next_g
                        largest_gap_idx = fwd

                    # Prioridad 1: Puntuación mayor
                    if has_major_punct(f_word) and next_g >= min_clause_gap:
                        best_major_idx = fwd
                        break

                    # Prioridad 2: Cláusula intermedia sin conector huérfano
                    if has_clause_punct(f_word) and next_g >= min_clause_gap and not is_dangling_word(f_word):
                        if best_clause_idx is None:
                            best_clause_idx = fwd

                    # Prioridad 3: Pausa acústica de respiro sin conector huérfano
                    if next_g >= min_silence_gap and not is_dangling_word(f_word):
                        if best_breath_idx is None:
                            best_breath_idx = fwd

                    if max_duration is not None and f_dur >= max_duration:
                        break

                    fwd += 1

                if best_major_idx is not None:
                    chosen_cut_idx = best_major_idx
                elif best_clause_idx is not None:
                    chosen_cut_idx = best_clause_idx
                elif best_breath_idx is not None:
                    chosen_cut_idx = best_breath_idx
                elif largest_gap_idx is not None and largest_gap_idx >= curr:
                    chosen_cut_idx = largest_gap_idx
                else:
                    chosen_cut_idx = curr
                break

            # 4. Tope máximo absoluto (solo si max_duration fue configurado explícitamente)
            if max_duration is not None and dur_curr >= max_duration:
                chosen_cut_idx = curr
                break

            if curr == n - 1:
                chosen_cut_idx = curr
                break

            curr += 1

        if chosen_cut_idx is None or chosen_cut_idx < start_idx:
            chosen_cut_idx = start_idx

        # 4. Prevención de colas huérfanas (Orphan Tail Absorption)
        if chosen_cut_idx + 1 < n and all_words[chosen_cut_idx + 1]["speaker"] == speaker:
            peek = chosen_cut_idx + 1
            peek_start = all_words[peek]["start"]
            gap_to_tail = peek_start - all_words[chosen_cut_idx]["end"]
            if gap_to_tail <= 0.50:
                while peek < n and all_words[peek]["speaker"] == speaker:
                    if peek > chosen_cut_idx + 1 and (all_words[peek]["start"] - all_words[peek - 1]["end"]) > hard_gap:
                        break
                    peek += 1
                remaining_words_count = peek - (chosen_cut_idx + 1)
                if remaining_words_count > 0:
                    remaining_dur = all_words[peek - 1]["end"] - peek_start
                    dur_if_merged = all_words[peek - 1]["end"] - seg_start
                    if remaining_dur < 2.0 and (max_duration is None or dur_if_merged <= (max_duration + 1.0)):
                        chosen_cut_idx = peek - 1

        seg_words = all_words[start_idx : chosen_cut_idx + 1]
        seg = create_segment_from_words(seg_words)
        if seg:
            grouped_segments.append(seg)
        start_idx = chosen_cut_idx + 1

    # 5. Pase 2: Fusión y sanado de micro-segmentos huérfanos (< 3.2s o <= 3 palabras) con pausas cortas (<= 0.45s)
    merged_segments = []
    i = 0
    while i < len(grouped_segments):
        cur_seg = grouped_segments[i]
        is_tiny = cur_seg["duration"] < 3.2 or cur_seg["word_count"] <= 3

        if is_tiny:
            # Opción A: Fusionar con el segmento previo solo si es del mismo speaker, pausa <= 0.45s y no excede max_duration
            if merged_segments and merged_segments[-1]["speaker"] == cur_seg["speaker"]:
                gap_prev = cur_seg["start"] - merged_segments[-1]["end"]
                if gap_prev <= 0.45 and (max_duration is None or (merged_segments[-1]["duration"] + cur_seg["duration"]) <= (max_duration + 1.5)):
                    prev_seg = merged_segments[-1]
                    comb_words = prev_seg["words"] + cur_seg["words"]
                    merged_segments[-1] = create_segment_from_words(comb_words)
                    i += 1
                    continue
            # Opción B: Fusionar con el segmento siguiente solo si es del mismo speaker, pausa <= 0.45s y no excede max_duration
            if i + 1 < len(grouped_segments) and grouped_segments[i + 1]["speaker"] == cur_seg["speaker"]:
                gap_next = grouped_segments[i + 1]["start"] - cur_seg["end"]
                if gap_next <= 0.45 and (max_duration is None or (cur_seg["duration"] + grouped_segments[i + 1]["duration"]) <= (max_duration + 1.5)):
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
    target_duration: float | None = None,
    min_duration: float = 3.0,
    max_gap: float = 0.85,
    hard_gap: float = 1.4,
    min_sentence_gap: float = 0.20,
    min_silence_gap: float = 0.48,
    max_duration: float | None = None,
) -> list[dict]:
    assigned_data = assign_speakers_by_word(whisper_result, diarization_result)
    if group_segments:
        assigned_data = smart_group_segments_strict(
            assigned_data,
            target_duration=target_duration,
            min_duration=min_duration,
            max_gap=max_gap,
            hard_gap=hard_gap,
            min_sentence_gap=min_sentence_gap,
            min_silence_gap=min_silence_gap,
            max_duration=max_duration,
        )
    if not include_words:
        for seg in assigned_data:
            seg.pop("words", None)
    return assigned_data

