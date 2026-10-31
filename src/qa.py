"""
Gate de QA para el doblaje TTS.

Métricas medidas por segmento (no inventadas): tempo aplicado, desvío de duración
frente al original, nivel RMS, silencio digital, estado de traducción y resultado
del entity lock. Se agregan al final de `clone_voice_segments` y se persisten en
`result.json` bajo la clave `qa`, para que un build degradado sea visible en la UI
en lugar de pasar como bueno.

Umbrales calibrados contra el corpus de referencia (doblaje automático de YouTube:
su TTS no estira más de ~1.1x y no deja huecos de −83 dBFS donde había música).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Optional, Sequence

from src.pacing import gap_split

QA_VERSION = 2

# Silencio digital: por debajo de esto el clip no tiene señal audible.
SILENT_RMS_DBFS = -50.0

# Por debajo de este slot el desvío relativo no mide nada: un "Cursor" de una palabra
# no puede durar 0.24s por mucho que el original lo ocupe. Medido en un build real,
# esos slots de 0.2-0.5s empujaban el p95 al 51% sin que hubiera ningún defecto.
MIN_SLOT_FOR_LENGTH_DEV = 0.8

QA_THRESHOLDS: dict[str, float] = {
    "entity_fail_max": 0,
    "fallback_max": 0,
    "silent_max": 0,
    "error_max": 0,
    "tempo_p95_max": 1.12,
    "overlap_max": 0,
    "rms_std_max": 1.5,
    # El doblaje automático de YouTube deja 25.0% de silencio y el original 18.0%.
    # El listón es no empeorar al doblaje que se reemplaza y no añadir más de 3 puntos
    # de aire muerto sobre las pausas que ya existían en la fuente.
    "dead_air_ratio_max": 0.25,
    # Con la métrica corregida (el hueco de la fuente se mide con orig_start/orig_end,
    # sin los márgenes de split_audio_sequences) los dos videos largos quedan en 4.1%
    # y 2.2%. Sin ripple medían 4.9% y 5.8%, así que 4.5% separa "el ripple trabaja"
    # de "el ripple está apagado" sin forzar a la traducción a rellenar por rellenar.
    "dead_air_excess_max": 0.045,
}


def _to_db(amplitude: float) -> float:
    return 20.0 * math.log10(max(amplitude, 1e-9))


def levels_from_pcm(arr: Any) -> tuple[float, float]:
    """
    Peak y RMS en dBFS de un tensor torch o secuencia numérica, sin importar torch.
    Devuelve (-120.0, -120.0) si no hay señal.
    """
    if arr is None:
        return -120.0, -120.0
    try:
        if hasattr(arr, "detach"):
            a = arr.detach()
            if hasattr(a, "to"):
                a = a.to("cpu")
            a = a.float()
            peak = float(a.abs().max()) if a.numel() else 0.0
            rms = float((a * a).mean().sqrt()) if a.numel() else 0.0
        else:
            flat = [abs(float(v)) for v in arr]
            if not flat:
                return -120.0, -120.0
            peak = max(flat)
            rms = math.sqrt(sum(v * v for v in flat) / len(flat))
    except Exception:
        return -120.0, -120.0
    return round(_to_db(peak), 2), round(_to_db(rms), 2)


def evaluate_segment(
    *,
    seg: int,
    orig_duration: float,
    raw_duration: float,
    final_duration: float,
    arr: Any = None,
    levels: Optional[tuple[float, float]] = None,
    translation_status: Optional[str] = None,
    entity_problems: Optional[Sequence[str]] = None,
    chars: int = 0,
    start: float = 0.0,
    orig_start: Optional[float] = None,
    residue: Optional[Sequence[str]] = None,
    ends_phrase: bool = False,
) -> dict[str, Any]:
    """
    Métricas de un segmento ya sintetizado y sincronizado.

    `levels` permite pasar (peak, rms) ya medidos: el timeline se evalúa después de
    cerrar los huecos de ritmo, cuando el tensor del segmento ya se liberó.
    """
    tempo = round(raw_duration / final_duration, 3) if final_duration > 0 else None
    length_dev = round(final_duration / orig_duration - 1.0, 3) if orig_duration > 0 else None
    peak_dbfs, rms_dbfs = levels if levels is not None else levels_from_pcm(arr)
    problems = [str(p) for p in (entity_problems or [])]
    status = translation_status or "ok"
    leftover = [str(w) for w in (residue or [])]

    return {
        "seg": int(seg),
        "start": round(float(start), 3),
        "orig_start": round(float(orig_start if orig_start is not None else start), 3),
        "orig_duration": round(float(orig_duration), 3),
        "raw_duration": round(float(raw_duration), 3),
        "final_duration": round(float(final_duration), 3),
        "chars": int(chars),
        "tempo": tempo,
        "length_dev": length_dev,
        "peak_dbfs": peak_dbfs,
        "rms_dbfs": rms_dbfs,
        "silent": rms_dbfs < SILENT_RMS_DBFS,
        "translation_status": status,
        "fallback": status == "fallback",
        "entity_problems": problems,
        "entity_fail": bool(problems),
        "residue": leftover,
        "ends_phrase": bool(ends_phrase),
    }


def _p95(values: Sequence[float]) -> Optional[float]:
    clean = sorted(float(v) for v in values)
    if not clean:
        return None
    idx = max(0, min(len(clean) - 1, math.ceil(0.95 * len(clean)) - 1))
    return round(clean[idx], 3)


def _median(values: Sequence[float]) -> Optional[float]:
    clean = sorted(float(v) for v in values)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return round(clean[mid], 3)
    return round((clean[mid - 1] + clean[mid]) / 2.0, 3)


def _std(values: Sequence[float]) -> Optional[float]:
    clean = [float(v) for v in values]
    if len(clean) < 2:
        return None
    mean = sum(clean) / len(clean)
    var = sum((v - mean) ** 2 for v in clean) / len(clean)
    return round(math.sqrt(var), 3)


def _chars_per_sec(records: Sequence[dict[str, Any]]) -> Optional[float]:
    """
    Ritmo real del TTS a 1.0x (chars / raw_duration).

    Es la calibración empírica de `src.pacing.SPEECH_RATES`: si el motor habla más
    despacio que la tabla, los presupuestos quedan cortos y vuelve el aire muerto.
    Se mide sobre `raw_duration` porque `final_duration` ya incluye estiramientos.
    """
    chars = sum(int(r.get("chars") or 0) for r in records)
    secs = sum(float(r.get("raw_duration") or 0.0) for r in records if r.get("chars"))
    if chars <= 0 or secs <= 0:
        return None
    return round(chars / secs, 2)


def _gaps(records: Sequence[dict[str, Any]], key: str, start_key: str = "start") -> list[float]:
    """
    Huecos entre el final de un segmento y el arranque del siguiente.

    `start_key` permite medir sobre el timeline real (`start`) o sobre el original
    (`orig_start`): el cierre de huecos mueve `start`, así que comparar el exceso
    contra `start` daría siempre cero.
    """
    ordered = sorted(records, key=lambda r: float(r.get(start_key) or 0.0))
    gaps: list[float] = []
    for prev, cur in zip(ordered, ordered[1:]):
        gap = float(cur[start_key]) - (float(prev[start_key]) + float(prev[key]))
        gaps.append(gap)
    return gaps


def _timeline_span(records: Sequence[dict[str, Any]]) -> float:
    ordered = sorted(records, key=lambda r: float(r.get("start") or 0.0))
    if not ordered:
        return 0.0
    first, last = ordered[0], ordered[-1]
    return float(last["start"]) + float(last["final_duration"]) - float(first["start"])


def _dead_air(records: Sequence[dict[str, Any]]) -> tuple[Optional[float], Optional[float]]:
    """
    (aire muerto total, exceso atribuible al doblaje).

    `length_dev` compara contra un slot que ya incluye las pausas del original, así que
    un segmento 'corto' puede estar respetando una pausa que existía en la fuente. Lo
    que importa es cuánto creció el hueco respecto del original: eso es lo que el
    espectador percibe como aire muerto añadido.
    """
    if not records:
        return None, None
    span = _timeline_span(records)
    if span <= 0:
        return None, None
    final_gaps = _gaps(records, "final_duration")
    source_gaps = _gaps(records, "orig_duration", "orig_start")
    total = sum(g for g in final_gaps if g > 0) / span
    excess = sum(max(0.0, f - s) for f, s in zip(final_gaps, source_gaps)) / span
    return round(total, 3), round(excess, 3)


def _overlaps(records: Sequence[dict[str, Any]]) -> tuple[int, float, list[int]]:
    """
    (segmentos que invaden al siguiente, segundos totales, ids de los invasores).

    Es el único defecto de duración que rompe la fluidez: un clip más largo que su
    hueco se come la línea siguiente. Un clip más corto solo deja una pausa que el
    cierre de huecos reubica al final de frase.
    """
    ordered = sorted(records, key=lambda r: float(r.get("start") or 0.0))
    segs: list[int] = []
    total = 0.0
    for prev, cur in zip(ordered, ordered[1:]):
        end = float(prev.get("start") or 0.0) + float(prev.get("final_duration") or 0.0)
        overlap = end - float(cur.get("start") or 0.0)
        if overlap > 0.01:
            segs.append(int(prev.get("seg") or 0))
            total += overlap
    return len(segs), round(total, 3), segs


def _dead_air_mid(records: Sequence[dict[str, Any]]) -> Optional[float]:
    """
    Fracción del timeline que es silencio dentro de una frase.

    Es el aire muerto que suena a corte: el que cae después de un punto es una pausa
    legítima y no molesta. `close_ripple` no puede bajar el total (el video dura lo que
    dura), pero sí moverlo de aquí a los finales de frase, y esto es lo que lo mide.
    """
    if not records:
        return None
    span = _timeline_span(records)
    if span <= 0:
        return None
    ordered = sorted(records, key=lambda r: float(r.get("start") or 0.0))
    mid, _end = gap_split(
        [float(r.get("start") or 0.0) for r in ordered],
        [float(r.get("final_duration") or 0.0) for r in ordered],
        [bool(r.get("ends_phrase")) for r in ordered],
    )
    return round(mid / span, 3)


def summarize(
    records: Sequence[dict[str, Any]],
    *,
    expected_segments: Optional[int] = None,
    tts_errors: int = 0,
) -> dict[str, Any]:
    """Agrega las métricas por segmento y evalúa los umbrales."""
    recs = list(records)
    tempos = [r["tempo"] for r in recs if r.get("tempo") is not None]
    devs = [
        abs(r["length_dev"]) for r in recs
        if r.get("length_dev") is not None
        and float(r.get("orig_duration") or 0.0) >= MIN_SLOT_FOR_LENGTH_DEV
    ]
    devs_over = [
        r["length_dev"] for r in recs
        if r.get("length_dev") is not None
        and r["length_dev"] > 0
        and float(r.get("orig_duration") or 0.0) >= MIN_SLOT_FOR_LENGTH_DEV
    ]
    levels = [r["rms_dbfs"] for r in recs if r.get("rms_dbfs") is not None and not r.get("silent")]
    dead_air, dead_air_excess = _dead_air(recs)
    dead_air_mid = _dead_air_mid(recs)
    overlap_count, overlap_secs, overlap_segs = _overlaps(recs)

    entity_fail_segs = [r["seg"] for r in recs if r.get("entity_fail")]
    residue_segs = [r["seg"] for r in recs if r.get("residue")]
    fallback_segs = [r["seg"] for r in recs if r.get("fallback")]
    silent_segs = [r["seg"] for r in recs if r.get("silent")]
    missing = (
        max(0, int(expected_segments) - len(recs))
        if expected_segments is not None
        else 0
    )

    metrics = {
        "tempo_p95": _p95(tempos),
        "length_dev_p95": _p95(devs),
        "length_dev_over_p95": _p95(devs_over),
        "rms_std": _std(levels),
        "rms_median": _median(levels),
        "chars_per_sec": _chars_per_sec(recs),
        "dead_air_ratio": dead_air,
        "dead_air_excess": dead_air_excess,
        "dead_air_mid": dead_air_mid,
        "overlap_count": overlap_count,
        "overlap_secs": overlap_secs,
        "residue": len(residue_segs),
    }

    failures: list[dict[str, Any]] = []

    def _fail(metric: str, observed: Any, limit: Any, segs: Optional[list[int]] = None) -> None:
        failures.append({
            "metric": metric,
            "observed": observed,
            "limit": limit,
            "segments": (segs or [])[:50],
        })

    if len(entity_fail_segs) > QA_THRESHOLDS["entity_fail_max"]:
        _fail("entity_fail", len(entity_fail_segs), QA_THRESHOLDS["entity_fail_max"], entity_fail_segs)
    if len(fallback_segs) > QA_THRESHOLDS["fallback_max"]:
        _fail("fallback", len(fallback_segs), QA_THRESHOLDS["fallback_max"], fallback_segs)
    if len(silent_segs) > QA_THRESHOLDS["silent_max"]:
        _fail("silent", len(silent_segs), QA_THRESHOLDS["silent_max"], silent_segs)
    if tts_errors + missing > QA_THRESHOLDS["error_max"]:
        _fail("tts_error", tts_errors + missing, QA_THRESHOLDS["error_max"])
    if metrics["tempo_p95"] is not None and metrics["tempo_p95"] > QA_THRESHOLDS["tempo_p95_max"]:
        _fail("tempo_p95", metrics["tempo_p95"], QA_THRESHOLDS["tempo_p95_max"])
    if overlap_count > QA_THRESHOLDS["overlap_max"]:
        _fail("overlap", overlap_count, QA_THRESHOLDS["overlap_max"], overlap_segs)
    if metrics["rms_std"] is not None and metrics["rms_std"] > QA_THRESHOLDS["rms_std_max"]:
        _fail("rms_std", metrics["rms_std"], QA_THRESHOLDS["rms_std_max"])
    if metrics["dead_air_ratio"] is not None and metrics["dead_air_ratio"] > QA_THRESHOLDS["dead_air_ratio_max"]:
        _fail("dead_air_ratio", metrics["dead_air_ratio"], QA_THRESHOLDS["dead_air_ratio_max"])
    if metrics["dead_air_excess"] is not None and metrics["dead_air_excess"] > QA_THRESHOLDS["dead_air_excess_max"]:
        _fail("dead_air_excess", metrics["dead_air_excess"], QA_THRESHOLDS["dead_air_excess_max"])

    # El residuo no bloquea: `shared_tokens` compara formas idénticas y en pt→es casi
    # todas son cognados correctos (`estamos`, `funciona`, `usando`). En dos builds
    # reales el juicio marcó 10 segmentos y ninguno era una fuga de verdad. Queda
    # visible para escucharlo, pero no degrada el build.
    warnings: list[dict[str, Any]] = []
    if residue_segs:
        warnings.append({
            "metric": "residue",
            "observed": len(residue_segs),
            "segments": residue_segs[:50],
        })

    return {
        "version": QA_VERSION,
        "passed": not failures,
        "segments": len(recs),
        "expected_segments": expected_segments,
        "tts_errors": int(tts_errors),
        "thresholds": dict(QA_THRESHOLDS),
        "metrics": {
            **metrics,
            "entity_fail": len(entity_fail_segs),
            "fallback": len(fallback_segs),
            "silent": len(silent_segs),
        },
        "failures": failures,
        "warnings": warnings,
    }


def format_report(report: dict[str, Any]) -> list[str]:
    """Líneas para el log del job. Sin tablas ni sangrías de más de 3 espacios."""
    m = report.get("metrics") or {}
    rate = m.get("chars_per_sec")
    lines = [
        f"🩺 [QA] {report.get('segments', 0)}/{report.get('expected_segments') or '?'} segmentos | "
        f"tempo p95 {m.get('tempo_p95') or 0:.2f}x | "
        f"desvío p95 {(m.get('length_dev_p95') or 0) * 100:.0f}% "
        f"(desborde {(m.get('length_dev_over_p95') or 0) * 100:.0f}%) | "
        f"rms σ {m.get('rms_std') or 0:.2f} dB | "
        f"fallback {m.get('fallback', 0)} | entidades {m.get('entity_fail', 0)} | "
        f"silencios {m.get('silent', 0)} | solapes {m.get('overlap_count', 0)} ({(m.get('overlap_secs') or 0):.1f}s)"
    ]
    if rate:
        lines.append(f"   ritmo medido: {rate:.1f} chars/s a 1.0x (tabla de presupuesto: ajustar si difiere >10%)")
    dead = m.get("dead_air_ratio")
    excess = m.get("dead_air_excess")
    mid = m.get("dead_air_mid")
    if dead is not None:
        mid_txt = f" | a mitad de frase {(mid or 0) * 100:.1f}%" if mid is not None else ""
        lines.append(
            f"   aire muerto: {dead * 100:.1f}% del timeline | añadido sobre el original "
            f"{(excess or 0) * 100:.1f}%{mid_txt} | referencia: YouTube 25.0%, original 18.0%"
        )
    if report.get("passed"):
        lines.append("✅ [QA] pasa los umbrales")
    else:
        lines.append(f"❌ [QA] {len(report.get('failures') or [])} fallo(s)")
        for f in report.get("failures") or []:
            detail = f" → segs {f['segments']}" if f.get("segments") else ""
            lines.append(f"   • {f['metric']}: {f['observed']} (máx {f['limit']}){detail}")
    for w in report.get("warnings") or []:
        detail = f" → segs {w['segments']}" if w.get("segments") else ""
        lines.append(f"   ⚠️ {w['metric']}: {w['observed']} (aviso, no bloquea){detail}")
    return lines


def save_report(folder: Path, report: dict[str, Any]) -> None:
    """Persiste el bloque `qa` en result.json (import diferido para evitar ciclos)."""
    from src.result_store import update_result_qa

    update_result_qa(folder, report)
