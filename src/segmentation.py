"""
Parámetros de segmentación del doblaje y comparación de dos cortes.

Dónde se corta el audio lo deciden dos niveles:

1. **Agrupación de palabras en segmentos** (`smart_group_segments_strict`): una
   pausa suficientemente larga separa dos segmentos; una cola corta se absorbe
   en el vecino para no dejar clips de una palabra.
2. **Margen del clip de origen** (`source_margins`): cuánto silencio toma cada
   clip de sus vecinos. Fija el tramo real que ocupa en el audio y, por tanto,
   el hueco que debe llenar el TTS.

Los valores por defecto son exactamente los que usa el pipeline en producción,
así que construir `SegmentationParams()` sin argumentos reproduce el
comportamiento actual. El módulo es puro: no importa torch, red ni el resto del
pipeline, y se puede simular cualquier variación sin cargar modelos.

Solo nueve umbrales deciden algo. Los que había antes y no aportaban se
retiraron midiendo: cinco no cambiaban ni un borde con los valores de
producción (uno estaba sombreado por otro, dos los cubría la regla de duración,
uno nunca llegaba a dispararse y otro no era un umbral sino una garantía) y dos
medían lo mismo que otro umbral con distinto nombre. La cuota del margen
(`margin_share`) no es un ajuste de estilo —por encima de 0.5 los clips vecinos
se solapan— y vive como constante en `src.pacing`.
"""

from dataclasses import dataclass, fields, replace
from typing import Any, Mapping

# El respiro que se exige cuando el ASR capitaliza sin puntuar es mayor que el
# de una puntuación explícita: la mayúscula es un indicio más débil que un
# punto, así que necesita más aire para justificar un corte. Es una relación
# fija, no un ajuste: los dos umbrales miden lo mismo con distinta fiabilidad.
UPPERCASE_GAP_RATIO = 1.78

# Parámetros que un ajuste normal mueve: la pausa que corta, la duración mínima
# y los dos márgenes del clip.
BASIC_FIELDS: tuple[str, ...] = (
    "hard_gap",
    "min_duration",
    "lead_max",
    "tail_max",
)

# Reglas finas: respiro de frase, tolerancia a la diarización, absorción de
# colas huérfanas y fusión de micro-segmentos.
ADVANCED_FIELDS: tuple[str, ...] = (
    "min_sentence_gap",
    "jitter_max_gap",
    "orphan_absorb_gap",
    "orphan_absorb_max_dur",
    "merge_max_gap",
)


@dataclass(frozen=True)
class SegmentationParams:
    """
    Valores que deciden dónde se corta el audio y cuánto ocupa cada clip.

    `hard_gap` vale 0.85 s y no el 1.3 s que declara `smart_group_segments_strict`
    como default: el pipeline siempre lo llama con `gap=0.85`. El default del
    dataclass debe ser el efectivo, no el de la función, o la simulación no
    reproduciría los cortes reales.
    """

    # ─── Nivel 1: agrupación de palabras ───
    # Pausa que siempre separa, sin exigir duración previa: es el corte de
    # escena. Antes había un segundo umbral (`min_silence_gap`) para la pausa
    # que solo corta tras `min_duration`; con los dos en 0.85 el segundo era
    # inalcanzable, porque el primero ya había cortado.
    hard_gap: float = 0.85
    # Antes de esta duración no se aplican las reglas de corte (salvo el silencio
    # duro) y, después, un segmento más corto se considera micro y se fusiona
    # con su vecino. Un solo número para las dos ideas: antes eran dos campos
    # con el mismo valor que se estorbaban al moverlos por separado.
    min_duration: float = 2.8
    min_sentence_gap: float = 0.18
    # Tolerancia al ruido de pyannote: corrige una palabra aislada etiquetada
    # con otro hablante si los huecos a ambos lados son menores que esto.
    jitter_max_gap: float = 0.40
    orphan_absorb_gap: float = 0.60
    orphan_absorb_max_dur: float = 2.2
    merge_max_gap: float = 0.55

    # ─── Nivel 2: márgenes del clip de origen ───
    lead_max: float = 0.150
    tail_max: float = 0.400

    @property
    def uppercase_gap(self) -> float:
        """Respiro exigido cuando la palabra siguiente abre oración en mayúscula."""
        return round(self.min_sentence_gap * UPPERCASE_GAP_RATIO, 3)

    def with_overrides(self, overrides: Mapping[str, Any] | None) -> "SegmentationParams":
        """
        Copia los parámetros aplicando solo claves conocidas y del tipo correcto.

        Un valor inválido se ignora en vez de romper la simulación: la UI puede
        mandar un campo vacío mientras el usuario escribe.
        """
        if not overrides:
            return self

        clean: dict[str, Any] = {}
        for field in fields(self):
            if field.name not in overrides:
                continue
            raw = overrides[field.name]
            if raw is None:
                continue
            wants_int = field.type is int or field.type == "int"
            try:
                clean[field.name] = int(raw) if wants_int else float(raw)
            except (TypeError, ValueError):
                continue
        return replace(self, **clean)

    def as_dict(self) -> dict[str, float | int]:
        """Representación plana para la API y la persistencia."""
        return {field.name: getattr(self, field.name) for field in fields(self)}


def _norm_text(text: Any) -> str:
    """Texto comparable: sin espacios repetidos ni extremos."""
    return " ".join(str(text or "").split())


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Segundos compartidos por dos tramos."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _clip_dict(clip: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Copia serializable de un clip para la respuesta."""
    if clip is None:
        return None
    return {
        "start": round(float(clip.get("start", 0.0)), 3),
        "end": round(float(clip.get("end", 0.0)), 3),
        "slot": round(float(clip.get("end", 0.0)) - float(clip.get("start", 0.0)), 3),
        "text": str(clip.get("text", "")),
        "speaker": str(clip.get("speaker", "")),
    }


def diff_segments(
    current: list[Mapping[str, Any]],
    proposed: list[Mapping[str, Any]],
    min_overlap: float = 0.05,
) -> list[dict[str, Any]]:
    """
    Empareja dos segmentaciones y etiqueta cada fila.

    El emparejamiento es por solape temporal, no por índice: una variación puede
    cambiar el número de segmentos y desplazar todos los índices.

    Estados:
      - ``igual``: mismo tramo y mismo texto.
      - ``ajustado``: mismo texto, bordes distintos (solo cambió el margen).
      - ``partido``: el tramo propuesto está dentro de uno actual.
      - ``ampliado``: el tramo propuesto contiene uno actual y añade vecinos.
      - ``fusionado``: el tramo propuesto cubre varios segmentos actuales.
      - ``modificado``: se solapan, pero ninguno contiene al otro.
      - ``nuevo``: no se solapa con ningún segmento actual.
      - ``eliminado``: segmento actual que la propuesta no cubre.
    """
    rows: list[dict[str, Any]] = []
    matched_current: set[int] = set()

    for prop_index, prop in enumerate(proposed):
        p_start = float(prop.get("start", 0.0))
        p_end = float(prop.get("end", 0.0))
        p_text = _norm_text(prop.get("text"))

        hits = [
            j
            for j, cur in enumerate(current)
            if _overlap(p_start, p_end, float(cur.get("start", 0.0)), float(cur.get("end", 0.0)))
            > min_overlap
        ]
        matched_current.update(hits)

        if not hits:
            status = "nuevo"
            needs_retranslation = True
        elif len(hits) > 1:
            status = "fusionado"
            needs_retranslation = True
        else:
            cur = current[hits[0]]
            c_start = float(cur.get("start", 0.0))
            c_end = float(cur.get("end", 0.0))
            same_text = _norm_text(cur.get("text")) == p_text
            same_bounds = abs(p_start - c_start) <= 0.001 and abs(p_end - c_end) <= 0.001
            if same_text and same_bounds:
                status = "igual"
            elif same_text:
                status = "ajustado"
            elif p_start >= c_start - 0.001 and p_end <= c_end + 0.001:
                status = "partido"
            elif p_start <= c_start + 0.001 and p_end >= c_end - 0.001:
                status = "ampliado"
            else:
                status = "modificado"
            needs_retranslation = not same_text

        rows.append(
            {
                "index": prop_index + 1,
                "status": status,
                "current_index": hits[0] + 1 if len(hits) == 1 else None,
                "current": _clip_dict(current[hits[0]]) if len(hits) == 1 else None,
                "proposed": _clip_dict(prop),
                "needs_retranslation": needs_retranslation,
            }
        )

    for cur_index, cur in enumerate(current):
        if cur_index in matched_current:
            continue
        rows.append(
            {
                "index": None,
                "status": "eliminado",
                "current_index": cur_index + 1,
                "current": _clip_dict(cur),
                "proposed": None,
                "needs_retranslation": False,
            }
        )

    rows.sort(
        key=lambda row: float(
            (row["proposed"] or row["current"] or {}).get("start", 0.0)
        )
    )
    return rows
