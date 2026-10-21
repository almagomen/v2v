from __future__ import annotations

import json
import re
import time
from typing import Optional

from google import genai
from src.config import get_google_api_keys, rotate_google_api_key

# Catálogo canónico oficial de Fish Audio S2 / S2.1
CANONICAL_FISH_EMOTIONS = {
    # Básicas
    "happy", "sad", "angry", "excited", "calm", "nervous", "confident",
    "surprised", "satisfied", "delighted", "scared", "worried", "upset",
    "frustrated", "depressed", "empathetic", "embarrassed", "disgusted",
    "moved", "proud", "relaxed", "grateful", "curious", "sarcastic",
    # Modulaciones de tono / entrega
    "whispering", "laughing", "in a hurry tone", "soft tone", "shouting",
    # Avanzadas
    "hopeful", "optimistic", "determined", "nostalgic", "sympathetic"
}

# Mapeo de normalización para tags antiguos o no estándar
TAG_NORMALIZATION = {
    "whisper": "whispering",
    "laughter": "laughing",
    "laugh": "laughing",
    "cry": "crying",
    "sigh": "sighing",
    "yell": "shouting",
    "shout": "shouting",
    "fast": "in a hurry tone",
    "hurried": "in a hurry tone",
    "soft": "soft tone",
    "joy": "happy",
    "neutral": "calm",
}


def normalize_emotion_tag(tag: str) -> str:
    """Normaliza cualquier tag al catálogo canónico de Fish Audio S2."""
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

    # Signos fuertes
    if "¡" in txt or "!" in txt:
        # Si tiene signos exclamativos múltiples o palabras de urgencia
        if any(w in txt.lower() for w in ["cuidado", "rápido", "corre", "alerta", "urgente"]):
            return "in a hurry tone", 0.85
        if any(w in txt.lower() for w in ["genial", "increíble", "excelente", "vamos", "mira", "wow", "gratis", "hack"]):
            return "excited", 0.85
        return "excited", 0.75

    if "¿" in txt or "?" in txt:
        return "curious", 0.70

    # Risas textuales
    if re.search(r"\b(ja(ja)+|ha(ha)+|k(k)+)\b", txt, re.IGNORECASE):
        return "laughing", 0.90

    # Términos explicativos / técnicos tranquilos
    if any(w in txt.lower() for w in ["primero", "luego", "después", "configurar", "instalar", "código", "terminal"]):
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
Analiza la siguiente lista de {total} frases consecutivas de un video y determina la emoción y estilo de locución más natural y adecuado para cada una, dentro del catálogo oficial de Fish Audio S2.

Catálogo de emociones permitidas:
[excited, happy, calm, confident, curious, surprised, satisfied, delighted, nervous, worried, frustrated, angry, whispering, laughing, in a hurry tone, soft tone]

Directrices:
1. Responde ÚNICAMENTE con un JSON con exactamente {total} claves numéricas del "1" al "{total}".
2. Para cada clave asigna un objeto con:
   - "emotion": uno de los valores del catálogo (o "calm" para explicaciones neutras).
   - "intensity": valor float de 0.5 a 1.0.
3. Si el orador está explicando tutoriales o código con fluidez, usa "confident" o "calm".
4. Si está llamando la atención, festejando o mostrando algo sorprendente, usa "excited".
5. Si hace preguntas o busca algo, usa "curious".

Frases indexadas:
---
{json.dumps(input_dict, indent=2, ensure_ascii=False)}
---

Devuelve ÚNICAMENTE el JSON:
{{
  "1": {{"emotion": "excited", "intensity": 0.8}},
  ...
  "{total}": {{"emotion": "confident", "intensity": 0.7}}
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
