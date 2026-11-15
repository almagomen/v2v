"""
Simulación de cortes del doblaje sin GPU, sin Gemini y sin Fish.

Toma las palabras ya transcritas (con su hablante) y vuelve a agruparlas con un
juego de parámetros candidato, recalculando el tramo que ocuparía cada clip. El
resultado se compara con la segmentación que hay hoy en `result.json` para que
la UI pueda enseñar qué cambiaría antes de tocar nada.

De dónde salen las palabras, por orden de precisión:

1. ``words_assigned.json`` — palabra, tiempos y hablante exactos (lo escribe el
   pipeline desde esta versión). Es la fuente exacta.
2. ``whisper_raw.json`` — palabra y tiempos, sin hablante. El hablante se
   aproxima por solape con los segmentos actuales.
3. ``result.json`` — un «palabra» por segmento. La re-agrupación apenas puede
   moverse, pero permite enseñar los márgenes y avisar de la baja precisión.

El módulo no escribe nada: solo lee y devuelve la propuesta.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.diarization import smart_group_segments_strict
from src.pacing import source_bounds
from src.result_store import load_result
from src.segmentation import SegmentationParams, diff_segments

WORDS_ASSIGNED_FILENAME = "words_assigned.json"
WHISPER_RAW_FILENAME = "whisper_raw.json"

# Un clip por debajo de este slot se considera corto: el TTS apenas tiene sitio
# para una frase y el habla se acelera o se solapa con el vecino.
SHORT_CLIP_SEC = 2.0

# Estados en los que las palabras del segmento nuevo siguen dentro del viejo, así
# que un diccionario de pronunciación manual puede viajar sin ambigüedad.
PHONEME_CARRY_STATUSES = frozenset({"igual", "ajustado", "partido"})


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _current_segments(result: Mapping[str, Any]) -> list[dict]:
    """Segmentos actuales con su tramo de habla y su tramo de clip."""
    out: list[dict] = []
    for idx, seg in enumerate(result.get("segments") or []):
        orig_start = float(seg.get("orig_start", seg.get("start", 0.0)))
        orig_end = float(seg.get("orig_end", seg.get("end", 0.0)))
        out.append(
            {
                "index": idx + 1,
                "orig_start": orig_start,
                "orig_end": orig_end,
                "src_start": seg.get("src_start"),
                "src_end": seg.get("src_end"),
                "text": str(seg.get("original_text") or seg.get("text") or ""),
                "speaker": str(seg.get("original_speaker") or seg.get("speaker") or ""),
                "phonemes": seg.get("phonemes") or {},
            }
        )
    return out


def _assign_speakers_by_overlap(
    words: list[dict],
    current: list[dict],
) -> list[dict]:
    """
    Etiqueta cada palabra con el hablante del segmento actual que más la cubre.

    Solo se usa cuando falta ``words_assigned.json``. Una palabra que no cae en
    ningún segmento actual hereda el hablante de la palabra anterior (o el
    primero del video) en vez de quedar sin etiqueta.
    """
    if not current:
        return words

    fallback = current[0]["speaker"]
    enriched: list[dict] = []
    last_speaker = fallback
    for word in words:
        w_start = float(word.get("start", 0.0))
        w_end = float(word.get("end", 0.0))
        best_speaker = ""
        best_overlap = 0.0
        for seg in current:
            overlap = _overlap(w_start, w_end, seg["orig_start"], seg["orig_end"])
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = seg["speaker"]
        if not best_speaker:
            best_speaker = last_speaker
        last_speaker = best_speaker
        item = dict(word)
        item["speaker"] = best_speaker
        enriched.append(item)
    return enriched


def load_words(folder: Path) -> tuple[list[dict], str]:
    """
    Devuelve ``(palabras, origen)`` donde origen es ``assigned``, ``raw`` o
    ``segments``. Cada palabra trae ``word``, ``start``, ``end`` y ``speaker``.
    """
    result = load_result(folder) or {}
    current = _current_segments(result)

    assigned = _read_json(folder / WORDS_ASSIGNED_FILENAME)
    if isinstance(assigned, dict):
        words = [
            w
            for w in assigned.get("words") or []
            if isinstance(w, dict) and w.get("word")
        ]
        if words:
            return words, "assigned"

    raw = _read_json(folder / WHISPER_RAW_FILENAME)
    if isinstance(raw, dict):
        words: list[dict] = []
        for seg in raw.get("segments") or []:
            for w in seg.get("words") or []:
                if not isinstance(w, dict) or not w.get("word"):
                    continue
                words.append(
                    {
                        "word": str(w.get("word", "")),
                        "start": float(w.get("start", 0.0)),
                        "end": float(w.get("end", 0.0)),
                    }
                )
        if words:
            return _assign_speakers_by_overlap(words, current), "raw"

    # Último recurso: una unidad por segmento. No puede re-agrupar, pero sí
    # recalcular márgenes y avisar de que la precisión es baja.
    words = [
        {
            "word": seg["text"],
            "start": seg["orig_start"],
            "end": seg["orig_end"],
            "speaker": seg["speaker"],
        }
        for seg in current
        if seg["text"].strip()
    ]
    return words, "segments"


def resolve_total_duration(
    result: Mapping[str, Any],
    words: Iterable[dict],
    current: list[dict],
) -> float:
    """
    Duración total del audio de voces para cerrar el margen del último clip.

    Toma el mayor de los tres datos disponibles: la duración declarada del video,
    el final de la última palabra y el final del último clip. Cualquiera de los
    tres puede faltar en un `result.json` antiguo.
    """
    info = result.get("info") or {}
    candidates = [
        float(info.get("duration") or 0.0),
        max((float(w.get("end", 0.0)) for w in words), default=0.0),
        max((float(s.get("src_end") or s["orig_end"]) for s in current), default=0.0),
    ]
    total = max(candidates)
    return total if total > 0 else 1.0


def _clip(
    *,
    start: float,
    end: float,
    text: str,
    speaker: str,
) -> dict:
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "text": text,
        "speaker": speaker,
    }


def _current_clips(
    current: list[dict],
    total_duration: float,
    params: SegmentationParams,
) -> list[dict]:
    """
    Clips que hay hoy en el timeline.

    Si ``result.json`` guarda ``src_start``/``src_end`` se usan tal cual: son el
    tramo real que ocupa el clip. Si no, se recalculan con los parámetros
    actuales para no comparar contra un hueco inexistente.
    """
    times = [(seg["orig_start"], seg["orig_end"]) for seg in current]
    clips: list[dict] = []
    for idx, seg in enumerate(current):
        src_start = seg.get("src_start")
        src_end = seg.get("src_end")
        if src_start is None or src_end is None:
            calc_start, calc_end = source_bounds(times, idx, total_duration, params)
        else:
            calc_start, calc_end = float(src_start), float(src_end)
        clips.append(
            _clip(
                start=calc_start,
                end=calc_end,
                text=seg["text"],
                speaker=seg["speaker"],
            )
        )
    return clips


def _proposed_clips(
    grouped: list[dict],
    total_duration: float,
    params: SegmentationParams,
) -> list[dict]:
    times = [(float(seg["start"]), float(seg["end"])) for seg in grouped]
    clips: list[dict] = []
    for idx, seg in enumerate(grouped):
        src_start, src_end = source_bounds(times, idx, total_duration, params)
        clips.append(
            _clip(
                start=src_start,
                end=src_end,
                text=str(seg.get("text", "")),
                speaker=str(seg.get("speaker", "")),
            )
        )
    return clips


def _metrics(clips: list[dict]) -> dict[str, float | int]:
    """Resumen de una segmentación: cuántos clips, qué tamaño y cuánto aire."""
    if not clips:
        return {
            "count": 0,
            "avg_slot": 0.0,
            "short_ratio": 0.0,
            "dead_air": 0.0,
        }
    ordered = sorted(clips, key=lambda c: float(c["start"]))
    slots = [max(0.0, float(c["end"]) - float(c["start"])) for c in ordered]
    dead_air = 0.0
    for prev, cur in zip(ordered, ordered[1:]):
        dead_air += max(0.0, float(cur["start"]) - float(prev["end"]))
    short = sum(1 for slot in slots if slot < SHORT_CLIP_SEC)
    return {
        "count": len(ordered),
        "avg_slot": round(sum(slots) / len(slots), 3),
        "short_ratio": round(short / len(slots), 3),
        "dead_air": round(dead_air, 3),
    }


def simulate(folder: Path, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """
    Calcula la segmentación que produciría `overrides` y la compara con la actual.

    Devuelve un dict serializable listo para la API: parámetros efectivos,
    clips actuales y propuestos, filas de diff, métricas de ambos lados y
    cuántos clips habría que retraducir, resintetizar o re-sincronizar.
    """
    params = SegmentationParams().with_overrides(overrides)
    result = load_result(folder) or {}
    current = _current_segments(result)
    words, words_source = load_words(folder)
    total_duration = resolve_total_duration(result, words, current)

    grouped = smart_group_segments_strict(
        [{"speaker": words[0].get("speaker", ""), "words": words}],
        params=params,
    ) if words else []

    current_clips = _current_clips(current, total_duration, SegmentationParams())
    proposed_clips = _proposed_clips(grouped, total_duration, params)
    rows = diff_segments(current_clips, proposed_clips)

    phonemes_by_current = {seg["index"]: seg["phonemes"] for seg in current}
    carried_phonemes: set[int] = set()
    retranslate = 0
    resynthesize = 0
    resync = 0
    for row in rows:
        status = row["status"]
        current_index = row.get("current_index")
        has_phonemes = bool(
            current_index is not None and phonemes_by_current.get(current_index)
        )
        carry = status in PHONEME_CARRY_STATUSES and has_phonemes
        row["phonemes_carry"] = carry
        if carry:
            carried_phonemes.add(int(current_index))

        if status == "igual":
            continue
        if status == "ajustado":
            # Mismas palabras, otro slot: el máster sintetizado se re-sincroniza.
            resync += 1
            continue
        resynthesize += 1
        if row["needs_retranslation"]:
            retranslate += 1

    phonemes_dropped = sum(
        1
        for index, phonemes in phonemes_by_current.items()
        if phonemes and index not in carried_phonemes
    )

    return {
        "params": params.as_dict(),
        "words_source": words_source,
        "total_duration": round(total_duration, 3),
        "current": {
            "clips": current_clips,
            "metrics": _metrics(current_clips),
        },
        "proposed": {
            "clips": proposed_clips,
            "metrics": _metrics(proposed_clips),
        },
        "rows": rows,
        "summary": {
            "changed": sum(1 for row in rows if row["status"] != "igual"),
            "retranslate": retranslate,
            "resynthesize": resynthesize,
            "resync": resync,
            "phonemes_dropped": phonemes_dropped,
        },
    }
