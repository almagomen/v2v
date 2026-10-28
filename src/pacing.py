"""
Presupuesto de duración para doblaje (isocronía).

Las tasas están calibradas con audio real, no con intuición: se midió el doblaje
español de YouTube y su original portugués separando voz de silencio con ffmpeg.
Ambos rondan 16.0 chars/s y ~5.35 sílabas/s, y el doblaje deja 25% de silencio
frente al 18% del original — ese excedente es el aire muerto que hay que evitar.

El módulo es puro: sin red, sin torch, sin genai. Se testea con `unittest` solo.
"""

import json
import re
from typing import Optional

# (sílabas por segundo, caracteres por segundo) en locución de doblaje.
SPEECH_RATES: dict[str, tuple[float, float]] = {
    "es": (5.35, 16.0),
    "pt": (5.33, 16.0),
    "en": (5.50, 15.0),
    "it": (5.40, 15.8),
    "fr": (5.30, 15.5),
    "de": (4.90, 15.0),
}
DEFAULT_RATE: tuple[float, float] = (5.20, 15.5)

# Banda de encaje aceptable: por debajo del 94% del slot el clip no lo llena
# (aire muerto), por encima del 110% el TTS tendrá que acelerarse de forma audible.
FIT_MIN = 0.94
FIT_MAX = 1.10

# Desviación que dispara la reescritura acotada del texto. Asimétrica a propósito:
# quedarse corto deja silencio muerto (el defecto que el espectador nota), mientras que
# pasarse solo obliga a comprimir un poco, que es mucho menos audible.
REWRITE_SHORT = 0.15
REWRITE_LONG = 0.25
MIN_WORDS_TO_REWRITE = 3

_TAG_RE = re.compile(r"\[[^\]]*\]")
_MARKER_RE = re.compile(r"⟦E\d+⟧")
_SPACE_RE = re.compile(r"\s+")

# Longitud media de un término técnico bloqueado ("Ghidra", "Malwarebytes.exe").
_MARKER_FALLBACK_LEN = 6


def primary_lang(lang: str) -> str:
    """'pt-BR' -> 'pt'. Evita depender de src.lang_utils para no arrastrar imports."""
    return str(lang or "").strip().lower().replace("_", "-").split("-")[0]


def speech_rate(lang: str) -> tuple[float, float]:
    """(sílabas/s, chars/s) del idioma objetivo; cae al promedio si no está en la tabla."""
    return SPEECH_RATES.get(primary_lang(lang), DEFAULT_RATE)


def visible_text(text: str, lock_map: Optional[dict[int, str]] = None) -> str:
    """
    Texto que efectivamente se pronuncia: sin etiquetas de emoción y con cada
    marcador ⟦E#⟧ sustituido por el término real que representa (su longitud sí se habla).
    """
    clean = _TAG_RE.sub(" ", str(text or ""))
    if lock_map:
        clean = _MARKER_RE.sub(
            lambda m: str(lock_map.get(int(m.group(0)[2:-1]), "x" * _MARKER_FALLBACK_LEN)),
            clean,
        )
    else:
        clean = _MARKER_RE.sub("x" * _MARKER_FALLBACK_LEN, clean)
    return _SPACE_RE.sub(" ", clean).strip()


def estimate_seconds(text: str, lang: str, lock_map: Optional[dict[int, str]] = None) -> float:
    """Duración hablada estimada del texto en el idioma objetivo."""
    _, chars_per_sec = speech_rate(lang)
    return len(visible_text(text, lock_map)) / chars_per_sec


def budget_for(lang: str, seconds: float) -> dict[str, int]:
    """Rango de caracteres y sílabas que cabe en `seconds` de locución."""
    if seconds <= 0:
        return {"chars_min": 0, "chars_max": 0, "syl_min": 0, "syl_max": 0}
    syl_per_sec, chars_per_sec = speech_rate(lang)
    target_chars = seconds * chars_per_sec
    target_syl = seconds * syl_per_sec
    chars_min = max(4, int(round(target_chars * FIT_MIN)))
    syl_min = max(1, int(round(target_syl * FIT_MIN)))
    return {
        "chars_min": chars_min,
        "chars_max": max(chars_min + 4, int(round(target_chars * FIT_MAX))),
        "syl_min": syl_min,
        "syl_max": max(syl_min + 1, int(round(target_syl * FIT_MAX))),
    }


def fit_deviation(text: str, lang: str, seconds: float, lock_map: Optional[dict[int, str]] = None) -> float:
    """
    Cuánto se desvía el texto del slot: -0.30 = 30% corto (dejaría aire muerto),
    +0.20 = 20% largo (forzaría acelerar la voz).
    """
    if seconds <= 0:
        return 0.0
    return estimate_seconds(text, lang, lock_map) / seconds - 1.0


def needs_rewrite(text: str, lang: str, seconds: float, lock_map: Optional[dict[int, str]] = None) -> bool:
    """
    Decide si vale la pena una segunda pasada de texto.

    Los segmentos de una o dos palabras no se tocan: reescribirlos suele costar
    fidelidad más de lo que gana en encaje (el estudio de dubbing humano muestra
    que la naturalidad pesa más que la isometría estricta).
    """
    if seconds <= 0:
        return False
    if len(visible_text(text, lock_map).split()) < MIN_WORDS_TO_REWRITE:
        return False
    dev = fit_deviation(text, lang, seconds, lock_map)
    return dev < -REWRITE_SHORT or dev > REWRITE_LONG


def build_fit_prompt(items: dict[str, dict[str, str]], lang_name: str) -> str:
    """
    Prompt de la pasada de encaje. `items` = {"1": {"texto": ..., "objetivo": ...}}.
    El objetivo se expresa en caracteres porque es lo que el modelo puede contar sin
    alucinar; las sílabas se reservan para el prompt principal.
    """
    return f"""Eres un ajustador de duración para doblaje al {lang_name}.

Cada entrada trae `texto` (la traducción actual) y `objetivo` (rango de caracteres que
cabe en el tiempo disponible del video). Reescribe cada `texto` para que caiga dentro
de su rango, sin excepciones:

1. Conserva el significado, el tono y la persona gramatical. No agregues datos nuevos
   ni elimines información del original.
2. Si el texto es LARGO: quita redundancias, contrae perífrasis, usa sinónimos más
   cortos. No recortes el final de la idea.
3. Si el texto es CORTO: agrega matices naturales del habla (conectores, refuerzos,
   vocativos) sin inventar contenido.
4. Los marcadores ⟦E1⟧, ⟦E2⟧... son intocables: mismos, una sola vez, mismo orden.
5. No incluyas el rango ni comentarios en la salida. Solo el texto final.

Entrada:
{json.dumps(items, indent=2, ensure_ascii=False)}

Devuelve únicamente un JSON con las mismas claves:
{{"1": "texto ajustado", "2": "texto ajustado"}}"""

