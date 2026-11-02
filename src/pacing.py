"""
Presupuesto de duración para doblaje (isocronía).

La única tasa que se mide es caracteres por segundo, porque es lo que el modelo puede
contar y lo que el TTS entrega de verdad. Las sílabas quedaron fuera: no están
definidas igual en todos los idiomas (un ideograma chino no es una sílaba, el japonés
cuenta moras) y el modelo no las cuenta de forma fiable. El carácter sí es una unidad
universal y medible en cualquier escritura.

La referencia humana se midió sobre el doblaje español de YouTube y su original
portugués separando voz de silencio con ffmpeg: ambos rondan 16.0 chars/s. El TTS no
habla a esa velocidad: la QA de un render real (Fish Audio, 144 segmentos) midió
17.2 chars/s a 1.0x. El presupuesto usa la tasa del TTS porque es la que decide si el
clip llena su slot o si el sincronizador tiene que estirarlo.

La tasa depende de la escritura, no solo del idioma: los idiomas con alfabeto rondan
15-17 chars/s, mientras que una escritura logográfica entrega muchos menos caracteres
por segundo con la misma información. Por eso un idioma nuevo se calibra con una
medición real (`src.qa` ya reporta los chars/s del render) y mientras tanto usa
`DEFAULT_RATE`.

El módulo es puro: sin red, sin torch, sin genai. Se testea con `unittest` solo.
"""

import json
import re
from collections import Counter
from typing import Mapping, Optional, Sequence

from src.lang_utils import SENTENCE_END_CHARS

# Caracteres por segundo en locución, medidos sobre audio real.
# `es` sale de la QA de un render con Fish Audio (17.2 chars/s a 1.0x); el resto
# conserva la referencia de doblaje humano (16.0) hasta tener medición propia.
SPEECH_RATES: dict[str, float] = {
    "es": 17.2,
    "pt": 16.0,
    "en": 15.0,
    "it": 15.8,
    "fr": 15.5,
    "de": 15.0,
}
DEFAULT_RATE: float = 15.5

# Banda de encaje aceptable: por debajo del 94% del slot el clip no lo llena
# (aire muerto), por encima del 110% el TTS tendrá que acelerarse de forma audible.
FIT_MIN = 0.94
FIT_MAX = 1.10

# Desviación que dispara la reescritura acotada del texto. Asimétrica a propósito:
# quedarse corto deja silencio muerto (el defecto que el espectador nota) mientras que
# pasarse solo obliga a comprimir un poco, que es mucho menos audible. El umbral corto
# se ajusta a `SYNC_TOLERANCE` de audio_utils (0.94): por debajo de -10% el clip ya se
# estira de forma audible, así que merece otra pasada de texto.
REWRITE_SHORT = 0.10
REWRITE_LONG = 0.25
MIN_WORDS_TO_REWRITE = 3

# Mejora mínima de desviación para aceptar un texto reescrito. Sin este margen, un
# ajuste de 0.01 contaba como avance y dejaba pasar textos que seguían sin caber.
FIT_MIN_GAIN = 0.02

# ─── Margen del clip de origen ───────────────────────────────────────────────────
# Whisper no escribe muletillas, respiraciones ni titubeos: el segmento termina en la
# última palabra transcrita y el resto de habla quedaba como aire muerto al final del
# clip. El margen recupera ese tramo del silencio vecino sin invadir al segmento de al
# lado: entre ataque y cola nunca se toma más del 80% del hueco disponible.
SOURCE_LEAD_MAX = 0.150
SOURCE_TAIL_MAX = 0.400
SOURCE_MARGIN_SHARE = 0.40


def source_margins(gap_before: float, gap_after: float) -> tuple[float, float]:
    """
    Segundos que el clip de origen toma del silencio anterior y posterior.

    Los dos márgenes salen del mismo hueco y cada uno se queda con el 40%, así que
    nunca se cruzan aunque el segmento vecino también esté recortado.
    """
    gb = max(0.0, float(gap_before))
    ga = max(0.0, float(gap_after))
    return (
        min(SOURCE_LEAD_MAX, gb * SOURCE_MARGIN_SHARE),
        min(SOURCE_TAIL_MAX, ga * SOURCE_MARGIN_SHARE),
    )


def source_bounds(
    times: Sequence[tuple[float, float]],
    index: int,
    total_duration: float,
) -> tuple[float, float]:
    """
    Arranque y fin del clip de origen de un segmento, márgenes incluidos.

    Es la única fuente de verdad del tramo que ocupa un segmento en el audio. El
    presupuesto de traducción, el corte de `vocals.wav` y la sincronía del TTS tienen
    que medir exactamente lo mismo: si la traducción se presupuesta contra el habla de
    Whisper pero el TTS se sincroniza contra el clip recortado (que recupera
    muletillas y respiraciones), el texto sale corto por construcción y el
    sincronizador lo estira hasta 0.80x.

    Args:
        times: (inicio, fin) del habla transcrita de cada segmento, en segundos.
        index: posición del segmento dentro de `times`.
        total_duration: duración total del audio de voces.

    Returns:
        (src_start, src_end) redondeados al milisegundo.
    """
    n = len(times)
    if not 0 <= index < n:
        raise IndexError(f"índice {index} fuera de rango para {n} segmentos")

    s_sec = float(times[index][0])
    e_sec = float(times[index][1])
    prev_end = float(times[index - 1][1]) if index > 0 else 0.0
    next_start = float(times[index + 1][0]) if index + 1 < n else float(total_duration)

    lead, tail = source_margins(s_sec - prev_end, next_start - e_sec)
    start = max(0.0, s_sec - lead)
    end = min(float(total_duration), e_sec + tail)
    return round(start, 3), round(end, 3)


_TERMINAL_RE = re.compile(rf"[{re.escape(SENTENCE_END_CHARS)}]+[\"'»)\]]*\s*$")

_TAG_RE = re.compile(r"\[[^\]]*\]")
_MARKER_RE = re.compile(r"⟦E\d+⟧")
_SPACE_RE = re.compile(r"\s+")

# Longitud media de un término técnico bloqueado ("Ghidra", "Malwarebytes.exe").
_MARKER_FALLBACK_LEN = 6


def primary_lang(lang: str) -> str:
    """'pt-BR' -> 'pt'. Evita depender de src.lang_utils para no arrastrar imports."""
    return str(lang or "").strip().lower().replace("_", "-").split("-")[0]


def speech_rate(lang: str) -> float:
    """Caracteres por segundo del idioma objetivo; cae al promedio si no está medido."""
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
    return len(visible_text(text, lock_map)) / speech_rate(lang)


def budget_for(lang: str, seconds: float) -> dict[str, int]:
    """
    Rango y objetivo de caracteres que caben en `seconds` de locución.

    `target` existe porque un rango solo se incumple por abajo: medido sobre un
    doblaje real, el modelo entregaba un 6% menos de lo que cabía en cada slot, y el
    sincronizador rellenaba ese hueco estirando la voz hasta 0.85x. Un número único
    al que apuntar corrige la tendencia mejor que dos extremos.
    """
    if seconds <= 0:
        return {"chars_min": 0, "chars_max": 0, "chars_target": 0}
    target_chars = seconds * speech_rate(lang)
    chars_min = max(4, int(round(target_chars * FIT_MIN)))
    return {
        "chars_min": chars_min,
        "chars_max": max(chars_min + 4, int(round(target_chars * FIT_MAX))),
        "chars_target": max(chars_min, int(round(target_chars))),
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


def ends_sentence(text: str) -> bool:
    """True si el texto cierra frase: tras un punto la pausa es intencional."""
    return bool(_TERMINAL_RE.search(visible_text(text)))


def gap_split(
    starts: list[float],
    durations: list[float],
    closed: list[bool],
) -> tuple[float, float]:
    """
    (silencio dentro de frase, silencio en pausas de fin de frase), en segundos.

    Es la medida que importa para el ritmo: el total no cambia al mover clips, pero
    el reparto sí. El silencio interno suena a corte; el de fin de frase, a pausa.
    """
    if not (len(durations) == len(starts) and len(closed) == len(starts)):
        raise ValueError("starts, durations y closed deben tener la misma longitud")
    mid = 0.0
    end = 0.0
    for i in range(len(starts) - 1):
        gap = float(starts[i + 1]) - (float(starts[i]) + float(durations[i]))
        if gap <= 0:
            continue
        if closed[i]:
            end += gap
        else:
            mid += gap
    return round(mid, 3), round(end, 3)


def echoed_texts(fitted: Mapping[str, str]) -> set[str]:
    """
    Valores que la pasada de encaje repitió para claves distintas.

    El modelo devuelve a veces la misma cadena en todas las entradas (eco de la
    plantilla del prompt). Un texto idéntico para originales distintos no es una
    traducción, así que se descarta antes de llegar al TTS.
    """
    counts = Counter(v.strip() for v in fitted.values())
    return {text for text, n in counts.items() if n > 1 and text}


def build_fit_prompt(items: dict[str, dict[str, str]], lang_name: str) -> str:
    """
    Prompt de la pasada de encaje.

    `items` = {"1": {"texto": ..., "actual": ..., "objetivo": ..., "estado": ...}}.
    El objetivo se expresa en caracteres porque es lo que el modelo puede contar sin
    alucinar. Los textos cortos llevan además `faltan`, el déficit exacto que hay que
    cubrir: sin ese número el modelo devolvía una mejora mínima y el clip seguía
    quedando corto.
    """
    return f"""Eres un ajustador de duración para doblaje al {lang_name}.

Cada entrada trae `texto` (la traducción actual), `actual` (sus caracteres),
`objetivo` (rango de caracteres que cabe en el tiempo disponible del video) y, cuando
está corta, `faltan` (los caracteres que le faltan para llegar al mínimo). Reescribe
cada `texto` para que quede dentro de su rango, sin excepciones:

1. Conserva el significado, el tono y la persona gramatical. No agregues datos nuevos
   ni elimines información del original.
2. Si el texto es LARGO: quita redundancias, contrae perífrasis, usa sinónimos más
   cortos. No recortes el final de la idea.
3. Si el texto es CORTO: no resumas ni recortes nada. Primero restituye la información
   del original que la traducción haya omitido (una idea, un matiz, un sujeto); si ya
   está toda, desarrolla la MISMA idea con más palabras hasta cubrir `faltan`, con
   recursos del habla natural de {lang_name} (conectores, refuerzos, vocativos). No
   repitas el mismo conector en dos entradas del bloque y no añadas relleno vacío ni
   contenido inventado: la muletilla se oye y no arregla el hueco.
4. Cuenta los caracteres de tu resultado antes de responder: debe quedar dentro de
   `objetivo`. Quedarse por debajo del mínimo deja silencio muerto en el video.
5. Los marcadores ⟦E1⟧, ⟦E2⟧... son intocables: mismos, una sola vez, mismo orden.
6. No incluyas el rango ni comentarios en la salida. Solo el texto final.

Entrada:
{json.dumps(items, indent=2, ensure_ascii=False)}

Devuelve únicamente un objeto JSON con las mismas claves de entrada y, como valor,
el texto final ya ajustado en {lang_name}. No repitas esta instrucción como valor."""

