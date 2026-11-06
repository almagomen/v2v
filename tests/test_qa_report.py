"""Formato legible del resumen de QA.

Comprueba que los valores ausentes no se muestren como ``—`` ambiguos: un
desborde inexistente es 0%, y la σ RMS solo falta cuando hay un único segmento.
"""
from __future__ import annotations

import unittest

from src.qa import format_report


def _report(**overrides) -> dict:
    metrics = {
        "speed_p95": 1.0,
        "tempo_p95": 1.0,
        "slow_ratio": 0.0,
        "length_dev_p95": 0.0,
        "length_dev_over_p95": None,
        "rms_std": None,
        "fallback": 0,
        "entity_fail": 0,
        "silent": 0,
        "overlap_count": 0,
        "overlap_secs": 0.0,
        "compaction_p95": None,
        "dead_air_ratio": 0.0,
        "dead_air_excess": 0.0,
        "dead_air_mid": 0.0,
        "chars_per_sec": 19.0,
    }
    metrics.update(overrides.pop("metrics", {}))
    report = {
        "segments": 1,
        "expected_segments": 1,
        "metrics": metrics,
        "passed": True,
        "failures": [],
        "warnings": [],
    }
    report.update(overrides)
    return report


class TestFormatReport(unittest.TestCase):
    def test_un_solo_segmento_no_muestra_guiones_huerfanos(self):
        text = "\n".join(format_report(_report()))

        self.assertIn("Desborde (p95): 0%", text)
        self.assertIn("Variación de volumen (σ RMS): sin datos", text)
        self.assertIn("se necesita más de un segmento", text)
        self.assertNotIn("— —", text)

    def test_fallo_explica_la_metrica_y_su_unidad(self):
        report = _report(
            segments=5,
            expected_segments=5,
            passed=False,
            metrics={"speed_p95": 1.174},
            failures=[{"metric": "speed_p95", "observed": 1.174, "limit": 1.12}],
        )
        text = "\n".join(format_report(report))

        self.assertIn("Velocidad de la voz (p95): 1.17x", text)
        self.assertIn("máximo 1.12x", text)
        self.assertIn("puede sonar apresurado", text)

    def test_recorte_solo_aparece_si_hay_recorte(self):
        sin_recorte = "\n".join(format_report(_report()))
        con_recorte = "\n".join(
            format_report(_report(metrics={"compaction_p95": 0.093}))
        )

        self.assertNotIn("recorte aplicado", sin_recorte)
        self.assertIn("recorte aplicado (p95) 9.3%", con_recorte)

    def test_aire_muerto_incluye_referencia(self):
        text = "\n".join(format_report(_report()))

        self.assertIn("aire muerto 0.0% del timeline", text)
        self.assertIn("doblaje de YouTube 25.0%", text)


if __name__ == "__main__":
    unittest.main()
