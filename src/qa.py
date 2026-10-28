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

QA_VERSION = 1

# Silencio digital: por debajo de esto el clip no tiene señal audible.
SILENT_RMS_DBFS = -50.0

QA_THRESHOLDS: dict[str, float] = {
    "entity_fail_max": 0,
    "fallback_max": 0,
    "silent_max": 0,
    "error_max": 0,
    "tempo_p95_max": 1.12,
    "length_dev_p95_max": 0.20,
    "rms_std_max": 1.5,
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
    translation_status: Optional[str] = None,
    entity_problems: Optional[Sequence[str]] = None,
    chars: int = 0,
) -> dict[str, Any]:
    """Métricas de un segmento ya sintetizado y sincronizado."""
    tempo = round(raw_duration / final_duration, 3) if final_duration > 0 else None
    length_dev = round(final_duration / orig_duration - 1.0, 3) if orig_duration > 0 else None
    peak_dbfs, rms_dbfs = levels_from_pcm(arr)
    problems = [str(p) for p in (entity_problems or [])]
    status = translation_status or "ok"

    return {
        "seg": int(seg),
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


def summarize(
    records: Sequence[dict[str, Any]],
    *,
    expected_segments: Optional[int] = None,
    tts_errors: int = 0,
) -> dict[str, Any]:
    """Agrega las métricas por segmento y evalúa los umbrales."""
    recs = list(records)
    tempos = [r["tempo"] for r in recs if r.get("tempo") is not None]
    devs = [abs(r["length_dev"]) for r in recs if r.get("length_dev") is not None]
    levels = [r["rms_dbfs"] for r in recs if r.get("rms_dbfs") is not None and not r.get("silent")]

    entity_fail_segs = [r["seg"] for r in recs if r.get("entity_fail")]
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
        "rms_std": _std(levels),
        "rms_median": _median(levels),
        "chars_per_sec": _chars_per_sec(recs),
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
    if metrics["length_dev_p95"] is not None and metrics["length_dev_p95"] > QA_THRESHOLDS["length_dev_p95_max"]:
        _fail("length_dev_p95", metrics["length_dev_p95"], QA_THRESHOLDS["length_dev_p95_max"])
    if metrics["rms_std"] is not None and metrics["rms_std"] > QA_THRESHOLDS["rms_std_max"]:
        _fail("rms_std", metrics["rms_std"], QA_THRESHOLDS["rms_std_max"])

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
    }


def format_report(report: dict[str, Any]) -> list[str]:
    """Líneas para el log del job. Sin tablas ni sangrías de más de 3 espacios."""
    m = report.get("metrics") or {}
    rate = m.get("chars_per_sec")
    lines = [
        f"🩺 [QA] {report.get('segments', 0)}/{report.get('expected_segments') or '?'} segmentos | "
        f"tempo p95 {m.get('tempo_p95') or 0:.2f}x | "
        f"desvío p95 {(m.get('length_dev_p95') or 0) * 100:.0f}% | "
        f"rms σ {m.get('rms_std') or 0:.2f} dB | "
        f"fallback {m.get('fallback', 0)} | entidades {m.get('entity_fail', 0)} | "
        f"silencios {m.get('silent', 0)}"
    ]
    if rate:
        lines.append(f"   ritmo medido: {rate:.1f} chars/s a 1.0x (tabla de presupuesto: ajustar si difiere >10%)")
    if report.get("passed"):
        lines.append("✅ [QA] pasa los umbrales")
        return lines

    lines.append(f"❌ [QA] {len(report.get('failures') or [])} fallo(s)")
    for f in report.get("failures") or []:
        detail = f" → segs {f['segments']}" if f.get("segments") else ""
        lines.append(f"   • {f['metric']}: {f['observed']} (máx {f['limit']}){detail}")
    return lines


def save_report(folder: Path, report: dict[str, Any]) -> None:
    """Persiste el bloque `qa` en result.json (import diferido para evitar ciclos)."""
    from src.result_store import update_result_qa

    update_result_qa(folder, report)
