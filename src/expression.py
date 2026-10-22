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

# Mapeo de normalización para tags no canónicos o sinónimos comunes
TAG_NORMALIZATION = {
    "whisper": "whispering",
    "laughter": "laughing",
    "laugh": "laughing",
    "chuckle": "chuckling",
    "sob": "sobbing",
    "cry": "crying loudly",
    "crying": "crying loudly",
    "sigh": "sighing",
    "groan": "groaning",
    "pant": "panting",
    "gasp": "gasping",
    "yawn": "yawning",
    "snore": "snoring",
    "throat": "clear throat",
    "yell": "shouting",
    "shout": "shouting",
    "scream": "screaming",
    "fast": "in a hurry tone",
    "hurried": "in a hurry tone",
    "hurry": "in a hurry tone",
    "urgent": "in a hurry tone",
    "soft": "soft tone",
    "gentle": "soft tone",
    "joy": "happy",
    "neutral": "calm",
    "peaceful": "calm",
    "anxiety": "anxious",
    "doubt": "doubtful",
    "confusion": "confused",
}


def normalize_emotion_tag(tag: str) -> str:
    """Normaliza cualquier tag al catálogo canónico oficial de Fish Audio S2."""
    clean = re.sub(r"[\[\]]", "", tag).strip().lower()
    if clean in TAG_NORMALIZATION:
        clean = TAG_NORMALIZATION[clean]
    if clean in CANONICAL_FISH_EMOTIONS:
        return clean
    return "calm"


def heuristic_detect_emotion(text: str) -> tuple[str, float]:
    """
    Detector heurístico offline basado en puntuación, marcadores léxicos y signos de entonación.
    Garantiza cero dependencia de red en caso de fallo de API.
    """
    txt = text.strip()
    if not txt:
        return "calm", 0.5

    # Si ya contiene un tag entre corchetes
    m = re.match(r"^\[([a-zA-Z\s]+)\]", txt)
    if m:
        return normalize_emotion_tag(m.group(1)), 0.8

    low = txt.lower()

    # Risas textuales
    if re.search(r"\b(ja(ja)+|ha(ha)+|k(k)+|je(je)+)\b", low):
        return "laughing", 0.90

    # Suspiros o expresiones de cansancio / alivio
    if any(w in low for w in ["uf", "uff", "ay dios", "por fin", "phew", "sigh"]):
        return "sighing", 0.80

    # Signos fuertes de exclamación o urgencia
    if "¡" in txt or "!" in txt:
        if any(w in low for w in ["cuidado", "rápido", "corre", "alerta", "urgente", "ya mismo"]):
            return "in a hurry tone", 0.85
        if any(w in low for w in ["socorro", "ayuda", "peligro", "nooo"]):
            return "shouting", 0.85
        if any(w in low for w in ["genial", "increíble", "excelente", "vamos", "mira", "wow", "gratis", "hack", "espectacular"]):
            return "excited", 0.85
        return "excited", 0.75

    # Preguntas o dudas
    if "¿" in txt or "?" in txt:
        if any(w in low for w in ["cómo", "dónde", "por qué", "qué es", "cuál"]):
            return "curious", 0.75
        if any(w in low for w in ["seguro", "será", "acaso", "dudas"]):
            return "doubtful", 0.70
        return "curious", 0.70

    # Indecisión o confusión
    if any(w in low for w in ["no entiendo", "no sé", "espera un momento", "qué raro", "extraño"]):
        return "confused", 0.70

    # Términos explicativos / técnicos de seguridad y confianza
    if any(w in low for w in ["primero", "luego", "después", "configurar", "instalar", "código", "terminal", "paso a paso", "vamos a"]):
        return "confident", 0.65

    return "calm", 0.60


def analyze_segments_expression(
    texts: list[dict],
    source_lang: str = "es",
    model_name: str = "gemini-flash-lite-latest",
) -> list[dict]:
    """
    Clasifica de forma multimodal y contextual la emoción de cada segmento usando Gemini
    en una sola llamada indexada por lote (1 a N), con fallback heurístico automático.
    Retorna: list[dict] con {"emotion": str, "intensity": float, "style": str}
    """
    total = len(texts)
    if total == 0:
        return []

    available_keys = get_google_api_keys()
    if not available_keys:
        return [{"emotion": heuristic_detect_emotion(t.get("text", ""))[0],
                 "intensity": heuristic_detect_emotion(t.get("text", ""))[1],
                 "style": "natural"} for t in texts]

    input_dict = {str(i + 1): t.get("text", "").strip() for i, t in enumerate(texts)}

    prompt = f"""Eres un director de voz y experto en prosodia audiovisual para doblaje profesional.
Analiza la siguiente lista de {total} frases consecutivas de un video y determina la emoción y estilo de locución más natural y adecuado para cada una, dentro del catálogo oficial de Fish Audio S2 (64+ emociones).

Catálogo oficial Fish Audio S2:
- BÁSICAS: happy, sad, angry, excited, calm, nervous, confident, surprised, satisfied, delighted, scared, worried, upset, frustrated, depressed, empathetic, embarrassed, disgusted, moved, proud, relaxed, grateful, curious, sarcastic
- AVANZADAS: hopeful, optimistic, determined, nostalgic, sympathetic, compassionate, anxious, confused, doubtful, uncertain, disappointed, regretful, guilty, bored, resigned
- TONOS / ENTREGA: in a hurry tone, soft tone, whispering, shouting, screaming
- EFECTOS: laughing, chuckling, sighing, groaning, panting, gasping

Directrices de dirección de doblaje:
1. Responde ÚNICAMENTE con un JSON con exactamente {total} claves numéricas del "1" al "{total}".
2. Para cada clave asigna:
   - "emotion": un valor exacto del catálogo oficial.
   - "intensity": float de 0.5 a 1.0 (0.6 neutro, 0.8 enérgico, 0.95 intenso).
3. Si el orador está explicando tutoriales, comandos o código con soltura: usa "confident" o "calm".
4. Si está llamando la atención, festejando o mostrando un logro importante: usa "excited" o "delighted".
5. Si hace preguntas o reflexiones: usa "curious", "doubtful" o "confused".
6. Si describe prisas o acciones rápidas: usa "in a hurry tone".
7. Si expresa alivio o desahogo: usa "sighing" o "relaxed".
8. Si expresa ironía o broma: usa "sarcastic" o "laughing".

Frases indexadas:
---
{json.dumps(input_dict, indent=2, ensure_ascii=False)}
---

Devuelve ÚNICAMENTE el JSON:
{{
  "1": {{"emotion": "excited", "intensity": 0.85}},
  ...
  "{total}": {{"emotion": "confident", "intensity": 0.70}}
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
                if isinstance(entry, dict) and "emotion" in entry:
                    emo = normalize_emotion_tag(str(entry.get("emotion", "calm")))
                    inten = float(entry.get("intensity", 0.7))
                    results.append({"emotion": emo, "intensity": inten, "style": "natural"})
                elif isinstance(entry, str):
                    results.append({"emotion": normalize_emotion_tag(entry), "intensity": 0.7, "style": "natural"})
                else:
                    h_emo, h_inten = heuristic_detect_emotion(texts[i - 1].get("text", ""))
                    results.append({"emotion": h_emo, "intensity": h_inten, "style": "natural"})

            if len(results) == total:
                return results

        except Exception as e:
            err_str = str(e).lower()
            if any(c in err_str for c in ("429", "quota", "resource_exhausted")):
                rotate_google_api_key()
                continue
            break

    # Fallback heurístico 100% offline si la API no está disponible
    return [{"emotion": heuristic_detect_emotion(t.get("text", ""))[0],
             "intensity": heuristic_detect_emotion(t.get("text", ""))[1],
             "style": "natural"} for t in texts]


def extract_acoustic_prosody(vocals_path: Path | str, segments: list[dict]) -> list[dict]:
    """
    Analiza vocals.wav para medir la energía RMS real (en dB relativos a la media del hablante)
    y el ritmo silábico de cada segmento antes de traducir.
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
            seg["energy_db"] = round(rel_db, 1)
            syl_rate = float(seg.get("syllable_rate") or (float(seg.get("speech_rate", 2.5)) * 1.6))

            if rel_db >= 3.2 and syl_rate >= 5.0:
                seg["acoustic_hint"] = "alta energía y entusiasmo ([excited])"
                seg["suggested_emotion"] = "excited"
            elif rel_db >= 2.8:
                seg["acoustic_hint"] = "voz firme y enfática ([confident])"
                seg["suggested_emotion"] = "confident"
            elif rel_db <= -4.5:
                seg["acoustic_hint"] = "voz baja o suave ([soft tone])"
                seg["suggested_emotion"] = "soft tone"
            elif syl_rate >= 5.8:
                seg["acoustic_hint"] = "ritmo rápido y urgente ([in a hurry tone])"
                seg["suggested_emotion"] = "in a hurry tone"
            elif syl_rate <= 3.2:
                seg["acoustic_hint"] = "ritmo pausado y sereno ([calm])"
                seg["suggested_emotion"] = "calm"
            else:
                seg["acoustic_hint"] = "tono natural fluido ([calm])"
                seg["suggested_emotion"] = "calm"
    except Exception as e:
        print(f"⚠️ [Prosodia Acústica] No se pudo analizar vocals.wav: {e}")

    return segments

