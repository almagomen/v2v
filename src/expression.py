from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# Catálogo canónico oficial de expresiones, modulaciones prosódicas y efectos (64+)
CANONICAL_EMOTIONS = {
    # 1. Emociones Básicas (24)
    "happy", "sad", "angry", "excited", "calm", "nervous", "confident",
    "surprised", "satisfied", "delighted", "scared", "worried", "upset",
    "frustrated", "depressed", "empathetic", "embarrassed", "disgusted",
    "moved", "proud", "relaxed", "grateful", "curious", "sarcastic",

    # 2. Emociones Avanzadas (25)
    "disdainful", "unhappy", "anxious", "hysterical", "indifferent",
    "uncertain", "doubtful", "confused", "disappointed", "regretful",
    "guilty", "ashamed", "jealous", "envious", "hopeful", "optimistic",
    "pessimistic", "nostalgic", "lonely", "bored", "contemptuous",
    "sympathetic", "compassionate", "determined", "resigned",

    # 3. Modulaciones de Tono y Entrega (6)
    "in a hurry tone", "shouting", "screaming", "whispering", "soft tone", "emphasis",

    # 4. Efectos Humanos de Audio (11)
    "laughing", "chuckling", "sobbing", "crying loudly", "sighing",
    "groaning", "panting", "gasping", "yawning", "snoring", "clear throat",

    # 5. Efectos Especiales y Pausas
    "break", "long-break", "audience laughing", "background laughter", "crowd laughing",
}

def normalize_emotion_tag(tag: str) -> Optional[str]:
    """Valida y limpia el tag contra el catálogo canónico oficial."""
    clean = re.sub(r"[\[\]]", "", tag).strip().lower()
    if clean in CANONICAL_EMOTIONS:
        return clean
    return None



def analyze_segments_expression(
    texts: list[dict],
    source_lang: str = "es",
    model_name: str = "gemini-flash-lite-latest",
    enable_emotions: bool = True,
) -> list[dict]:
    """
    Enriquece de forma contextual la prosodia de cada segmento delegando al motor
    canónico de adaptación en el mismo idioma en translation.py.
    Retorna: list[dict] con {"text": str, "emotion": Optional[str], "phonemes": dict}.
    """
    if not texts:
        return []

    from src.translation import translate_text_list

    sentences = [t.get("text", "").strip() for t in texts]
    times_list = [(float(t.get("start", 0.0)), float(t.get("end", 0.0))) for t in texts]
    has_valid_times = all(e > s for s, e in times_list)

    res = translate_text_list(
        sentences,
        target_lang=source_lang,
        source_lang=source_lang,
        model_name=model_name,
        times=times_list if has_valid_times else None,
        segments_meta=texts,
        enable_emotions=enable_emotions,
        return_details=True,
    )

    if not res or not res[0]:
        return []

    translated_texts, phonemes_list = res

    results = []
    for i, (orig, txt) in enumerate(zip(texts, translated_texts)):
        ph = phonemes_list[i] if phonemes_list and i < len(phonemes_list) else {}
        m_tag = re.match(r"^\[([a-zA-Z\s\-]+)\]", txt)
        detected_emo = normalize_emotion_tag(m_tag.group(1)) if m_tag else None
        results.append({
            "text": txt,
            "emotion": detected_emo,
            "phonemes": ph,
        })

    return results


def extract_acoustic_prosody(vocals_path: Path | str, segments: list[dict]) -> list[dict]:
    """
    Analiza vocals.wav para medir la energía RMS y el ritmo silábico de cada segmento
    únicamente para enriquecer la pista acústica del prompt de traducción.
    """
    p = Path(vocals_path)
    if not p.exists() or not segments:
        return segments
    try:
        import math
        import torch
        import torchaudio
        waveform, sr = torchaudio.load(str(p))
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)

        rms_values = []
        for seg in segments:
            s_frame = max(0, int(float(seg.get("start", 0.0)) * sr))
            e_frame = min(waveform.shape[-1], int(float(seg.get("end", 0.0)) * sr))
            chunk = waveform[:, s_frame:e_frame]
            if chunk.numel() > 0:
                rms = float(torch.sqrt(torch.mean(chunk ** 2)).item())
            else:
                rms = 1e-6
            rms_values.append(max(rms, 1e-6))

        mean_rms = sum(rms_values) / max(1, len(rms_values))

        for seg, rms in zip(segments, rms_values):
            rel_db = 20.0 * math.log10(rms / max(mean_rms, 1e-6))
            syl_rate = float(seg.get("syllable_rate") or (float(seg.get("speech_rate", 2.5)) * 1.6))

            if rel_db >= 3.2 and syl_rate >= 5.0:
                seg["acoustic_hint"] = "alta energía | ritmo acelerado"
            elif rel_db >= 2.8:
                seg["acoustic_hint"] = "voz firme y enfática | ritmo natural"
            elif rel_db <= -4.5:
                seg["acoustic_hint"] = "voz suave / baja | ritmo moderado"
            elif syl_rate >= 5.8:
                seg["acoustic_hint"] = "ritmo rápido y urgente | energía moderada"
            elif syl_rate <= 3.2:
                seg["acoustic_hint"] = "ritmo pausado y sereno | energía tranquila"
            else:
                seg["acoustic_hint"] = "tono natural fluido | energía moderada"
    except Exception as e:
        print(f"⚠️ [Prosodia Acústica] No se pudo analizar vocals.wav: {e}")

    return segments

