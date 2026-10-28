"""
Tests del entity lock y del gate de QA (stdlib, sin pytest).

Ejecutar desde la raíz del repo:
    python -m unittest tests.test_entities_qa -v
"""
from __future__ import annotations

import unittest

from src.entities import (
    check_entities,
    collect_known_terms,
    lock_text,
    restore_text,
)
from src.qa import evaluate_segment, summarize


class TestEntityLock(unittest.TestCase):
    def test_roundtrip_preserva_original(self):
        src = "Vou instalar o Ghidra 12.1 e usar o REA com OpenCode."
        locked, mapping = lock_text(src)
        self.assertNotEqual(locked, src)
        self.assertEqual(restore_text(locked, mapping), src)
        # `Ghidra 12.1` viaja como una sola unidad: el MT no puede separar nombre y versión.
        self.assertIn("Ghidra 12.1", mapping.values())
        self.assertIn("REA", mapping.values())
        self.assertIn("OpenCode", mapping.values())

    def test_une_nombres_de_dos_palabras(self):
        src = "Instalei o Open Code e o REA Agent hoje."
        _locked, mapping = lock_text(src)
        self.assertIn("Open Code", mapping.values())
        self.assertIn("REA Agent", mapping.values())

    def test_nombre_propio_al_inicio_no_se_bloquea_sin_contexto(self):
        src = "Ghidra é a ferramenta que vamos usar."
        _locked, mapping = lock_text(src)
        self.assertNotIn("Ghidra", mapping.values())

    def test_nombre_propio_conocido_se_bloquea_en_todo_el_lote(self):
        sentences = [
            "Hoje eu abro o Ghidra no Windows.",
            "Ghidra mostra o grafo de funções.",
        ]
        known = collect_known_terms(sentences)
        self.assertIn("Ghidra", known)
        _locked, mapping = lock_text(sentences[1], known=known)
        self.assertIn("Ghidra", mapping.values())

    def test_stopword_en_mayusculas_no_se_bloquea(self):
        _locked, mapping = lock_text("EU não sei, mas ELE sabe.")
        self.assertNotIn("EU", mapping.values())
        self.assertNotIn("ELE", mapping.values())

    def test_archivo_y_ruta(self):
        src = r"Roda o install_ghidra.ps1 dentro de C:\tools\ghidra."
        locked, mapping = lock_text(src)
        self.assertIn("install_ghidra.ps1", mapping.values())
        self.assertTrue(any("C:\\tools" in v for v in mapping.values()), mapping)
        self.assertEqual(restore_text(locked, mapping), src)

    def test_restore_tolera_espacios_del_modelo(self):
        locked, mapping = lock_text("Usa o Ghidra aqui.")
        mangled = locked.replace("⟦", "⟦ ").replace("⟧", " ⟧")
        self.assertEqual(restore_text(mangled, mapping), "Usa o Ghidra aqui.")


class TestEntityCheck(unittest.TestCase):
    def test_ok_si_conserva_tokens_y_numeros(self):
        locked, _ = lock_text("Instala o Ghidra 12.1 hoje.")
        verdict = check_entities(locked, "Instala el ⟦E1⟧ hoy.")
        self.assertTrue(verdict["ok"], verdict["reasons"])

    def test_detecta_entidad_perdida(self):
        locked, _ = lock_text("Instala o Ghidra 12.1 hoje.")
        verdict = check_entities(locked, "Instala el Ghidra 12.1 hoy.")
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["missing"], [1])

    def test_detecta_numero_alterado(self):
        verdict = check_entities("Baja a versão 12.1 agora.", "Baja la versión 2.1 ahora.")
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("números" in r for r in verdict["reasons"]))

    def test_detecta_entidad_inventada(self):
        locked, _ = lock_text("Abre o Ghidra.")
        verdict = check_entities(locked, "Abre el ⟦E1⟧ y el ⟦E2⟧.")
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["extra"], [2])


class TestQaGate(unittest.TestCase):
    def _rec(self, seg=1, tempo=1.0, silent=False, status=None, problems=None):
        arr = [0.0] * 100 if silent else [0.3, -0.3] * 50
        rec = evaluate_segment(
            seg=seg,
            orig_duration=2.0,
            raw_duration=2.0 * tempo,
            final_duration=2.0,
            arr=arr,
            translation_status=status,
            entity_problems=problems,
        )
        return rec

    def test_reporte_limpio_pasa(self):
        report = summarize([self._rec(seg=i) for i in range(1, 21)], expected_segments=20)
        self.assertTrue(report["passed"], report["failures"])
        self.assertAlmostEqual(report["metrics"]["tempo_p95"], 1.0, places=2)

    def test_detecta_silencio(self):
        recs = [self._rec(seg=i) for i in range(1, 20)] + [self._rec(seg=20, silent=True)]
        report = summarize(recs, expected_segments=20)
        self.assertFalse(report["passed"])
        self.assertEqual(report["metrics"]["silent"], 1)
        self.assertIn("silent", [f["metric"] for f in report["failures"]])

    def test_detecta_fallback_y_entidades(self):
        recs = [
            self._rec(seg=1, status="fallback"),
            self._rec(seg=2, status="entity_fail", problems=["números [12] -> [2]"]),
        ]
        report = summarize(recs, expected_segments=2)
        metrics = report["metrics"]
        self.assertEqual(metrics["fallback"], 1)
        self.assertEqual(metrics["entity_fail"], 1)
        self.assertFalse(report["passed"])

    def test_detecta_tempo_excesivo(self):
        recs = [self._rec(seg=i, tempo=1.25) for i in range(1, 21)]
        report = summarize(recs, expected_segments=20)
        self.assertFalse(report["passed"])
        self.assertIn("tempo_p95", [f["metric"] for f in report["failures"]])

    def test_detecta_segmentos_faltantes(self):
        report = summarize([self._rec(seg=i) for i in range(1, 10)], expected_segments=12)
        self.assertFalse(report["passed"])
        self.assertIn("tts_error", [f["metric"] for f in report["failures"]])

    def test_ritmo_medido_calibra_la_tabla(self):
        """chars/raw_duration: la señal para corregir SPEECH_RATES tras un render real."""
        recs = [
            evaluate_segment(seg=1, orig_duration=5.0, raw_duration=5.0,
                             final_duration=5.0, arr=[0.3, -0.3] * 50, chars=80),
            evaluate_segment(seg=2, orig_duration=5.0, raw_duration=5.0,
                             final_duration=5.0, arr=[0.3, -0.3] * 50, chars=80),
        ]
        report = summarize(recs, expected_segments=2)
        self.assertAlmostEqual(report["metrics"]["chars_per_sec"], 16.0, places=2)

    def test_ritmo_sin_chars_es_none(self):
        report = summarize([self._rec(seg=1)], expected_segments=1)
        self.assertIsNone(report["metrics"]["chars_per_sec"])

    def test_ritmo_no_penaliza_el_gate(self):
        """El ritmo es informativo: no debe convertir un build limpio en fallido."""
        recs = [self._rec(seg=i) for i in range(1, 6)]
        report = summarize(recs, expected_segments=5)
        self.assertTrue(report["passed"], report["failures"])


if __name__ == "__main__":
    unittest.main()
