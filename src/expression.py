from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from google import genai
from src.config import get_google_api_keys, rotate_google_api_key

# Catálogo canónico oficial de Fish Audio S2 / S2.1 (64+ expresiones y efectos)
CANONICAL_FISH_EMOTIONS = {
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
    """Valida y limpia el tag contra el catálogo canónico oficial de Fish Audio S2."""
    clean = re.sub(r"[\[\]]", "", tag).strip().lower()
    if clean in CANONICAL_FISH_EMOTIONS:
        return clean
    return None



def analyze_segments_expression(
    texts: list[dict],
    source_lang: str = "es",
    model_name: str = "gemini-flash-lite-latest",
    enable_emotions: bool = True,
) -> list[dict]:
    """
    Enriquece de forma contextual la prosodia de cada segmento usando Gemini
    en una sola llamada indexada por lote (1 a N).
    Retorna: list[dict] con {"text": str, "emotion": Optional[str], "phonemes": dict}.
    Si no hay API disponible o falla la llamada, retorna lista vacía sin inventar prosodia offline.
    """
    total = len(texts)
    if total == 0:
        return []

    available_keys = get_google_api_keys()
    if not available_keys:
        return []

    input_dict = {str(i + 1): t.get("text", "").strip() for i, t in enumerate(texts)}

    active_emotions_list = sorted([e for e in CANONICAL_FISH_EMOTIONS if not ("break" in e or "laughing" in e and "crowd" in e)])
    catalog_display = ", ".join(f"[{e}]" for e in active_emotions_list)

    if enable_emotions:
        emotion_rule = f"""- MODULACIÓN PROSÓDICA Y EXPRESIONES: Puedes integrar marcadores del catálogo canónico oficial de Fish Audio:
     {catalog_display}
     * Ubicación: Colócalos ya sea al inicio de la frase para guiar la entonación general, o en cualquier punto natural de la frase donde ocurra una inflexión, énfasis o reacción dramática.
     * Tono neutro: Si la frase es neutra, informativa o puramente descriptiva, déjala limpia sin ninguna etiqueta de emoción (no fuerces "calm" ni etiquetas artificiales)."""
    else:
        emotion_rule = """- MODULACIÓN PROSÓDICA: Mantén entonación neutra y natural, sin etiquetas de emoción."""

    prompt = f"""Eres un director de voz y especialista en adaptación prosódica para modelos de síntesis de voz (TTS).
Tu misión es ENRIQUECER cada frase de diálogo con modulaciones prosódicas, pausas naturales y énfasis vocal orgánico, para que suene 100% convincente y humana al ser leída por un motor de voz.

Directrices de prosodia y adaptación oral:
1. Responde ÚNICAMENTE con un objeto JSON con exactamente {total} claves numéricas del "1" al "{total}".
2. Para cada clave entrega un objeto con:
   - "text": la frase con las modulaciones, pausas y énfasis integrados en el punto natural del discurso:
{emotion_rule}
     * Pausas internas: `[break]` para pausas breves o respiros naturales entre dos cláusulas; `[long-break]` para pausas prolongadas o reflexiones (nunca al inicio ni final absoluto).
     * Énfasis vocal: `[emphasis]` inmediatamente antes de una palabra clave con especial fuerza de entonación.
     * Reacciones vocales: si el orador ríe o suspira en medio de una frase, puedes incluir `[laughing]` o `[sighing]`.
     * Preserva la entonación interrogativa (¿?) y exclamativa (¡!).
   - "phonemes": diccionario {{"Palabra": "Pronunciación"}} para nombres propios, siglas, extranjerismos o tecnicismos cuya lectura literal pueda inducir a error fonético en la voz sintética (o {{}} si no hay).

Frases indexadas:
---
{json.dumps(input_dict, indent=2, ensure_ascii=False)}
---

Devuelve ÚNICAMENTE el JSON:
{{
  "1": {{
    "text": "frase con modulaciones o pausas naturales",
    "phonemes": {{}}
  }},
  ...
  "{total}": {{
    "text": "frase final adaptada",
    "phonemes": {{}}
  }}
}}"""

    for attempt in range(len(available_keys)):
        key = available_keys[0]
        try:
            client = genai.Client(api_key=key)
            resp = client.interactions.create(
                model=model_name,
                input=prompt,
                response_format=[{"type": "text", "mime_type": "application/json"}],
            )
            raw = getattr(resp, "output_text", "") or ""
            clean = raw.strip()
            m_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if m_block:
                clean = m_block.group(1)

            parsed = json.loads(clean)
            results = []
            for i in range(1, total + 1):
                entry = parsed.get(str(i)) or parsed.get(i)
                txt = ""
                ph = {}
                detected_emo = None

                if isinstance(entry, dict):
                    txt = str(entry.get("text", "")).strip()
                    ph_raw = entry.get("phonemes")
                    if isinstance(ph_raw, dict):
                        ph = {str(k).strip(): str(v).strip() for k, v in ph_raw.items() if k and v}
                    if "emotion" in entry and entry["emotion"]:
                        detected_emo = normalize_emotion_tag(str(entry["emotion"]))
                elif isinstance(entry, str):
                    txt = entry.strip()

                if not txt:
                    txt = texts[i - 1].get("text", "")

                # Extraer emoción inicial si el texto trae tag entre corchetes
                m_tag = re.match(r"^\[([a-zA-Z\s\-]+)\]", txt)
                if m_tag:
                    norm = normalize_emotion_tag(m_tag.group(1))
                    if norm:
                        detected_emo = norm

                results.append({
                    "text": txt,
                    "emotion": detected_emo,
                    "phonemes": ph,
                })

            if len(results) == total:
                return results

        except Exception as e:
            err_str = str(e).lower()
            if any(c in err_str for c in ("429", "quota", "resource_exhausted")):
                rotate_google_api_key()
                continue
            break

    # Cero inventos offline: si no hay respuesta de la IA, no se inyectan emociones
    return []


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

