"""
Tests del entity lock y del gate de QA (stdlib, sin pytest).

Ejecutar desde la raíz del repo:
    python -m unittest tests.test_entities_qa -v
"""
from __future__ import annotations

import re
import unittest

from src.entities import (
    PLACEHOLDER_TMPL,
    check_entities,
    collect_known_terms,
    lock_text,
    normalize_asr_casing,
    restore_text,
)
from src.lang_utils import shared_tokens
from src.qa import evaluate_segment, summarize


class TestEntityLock(unittest.TestCase):
    def test_roundtrip_preserva_original(self):
        src = "Vou instalar o Ghidra 12.1 e usar o REA com OpenCode."
        locked, mapping = lock_text(src)
        self.assertNotEqual(locked, src)
        self.assertEqual(restore_text(locked, mapping), src)
        # Nombre y versión viajan como dos unidades protegidas: el MT no puede
        # separar una de la otra sin que el chequeo lo detecte.
        self.assertIn("Ghidra", mapping.values())
        self.assertIn("12.1", mapping.values())
        self.assertIn("REA", mapping.values())
        self.assertIn("OpenCode", mapping.values())

    def test_no_fusiona_tokens_contiguos(self):
        """Unir tokens contiguos congelaba 'Hermes Porém' y metía portugués en el español."""
        src = "Configura no Hermes hoje"
        _locked, mapping = lock_text(src)
        self.assertIn("Hermes", mapping.values())
        glued = [v for v in mapping.values() if " " in v]
        self.assertEqual(glued, [], f"términos pegados: {glued}")

    def test_palabra_escrita_en_minuscula_en_el_lote_no_se_bloquea(self):
        """Una palabra que el ASR escribe alguna vez en minúscula es habla, no una marca."""
        sentences = [
            "Configura no Hermes Porém Você tem que reiniciar",
            "Mas porém você pode usar o Hermes depois.",
        ]
        known = collect_known_terms(sentences)
        self.assertIn("Hermes", known)
        self.assertNotIn("Porém", known)
        self.assertNotIn("Você", known)

    def test_formas_estructurales_se_bloquean_sin_estadistica(self):
        """Versiones, camelCase y archivos no existen en el habla corriente."""
        sentences = ["Instala o OpenCode 12.1 hoje", "opencode roda o node.js e o 12.1"]
        known = collect_known_terms(sentences)
        self.assertIn("OpenCode", known)
        self.assertIn("12.1", known)
        self.assertIn("node.js", known)

    def test_normaliza_mayusculas_de_pausa_del_asr(self):
        """Whisper capitaliza tras cada pausa; el MT lee eso como nombre propio."""
        raw = "Ela não funciona Mais em outro lugar Porém"
        self.assertEqual(
            normalize_asr_casing(raw),
            "Ela não funciona mais em outro lugar porém",
        )

    def test_normalizacion_conserva_entidades_y_siglas(self):
        raw = "Usa o OpenCode e a API Key no Ghidra"
        out = normalize_asr_casing(raw, keep={"OpenCode", "Ghidra"})
        self.assertIn("OpenCode", out)
        self.assertIn("Ghidra", out)
        self.assertIn("API", out)

    def test_solapamiento_marca_las_palabras_sin_traducir(self):
        """Los tokens idénticos en origen y salida son el candidato que juzga el modelo."""
        shared = shared_tokens("No sirve Mais em outro lugar", "No sirve Mais en otro lugar")
        self.assertIn("mais", shared)

    def test_solapamiento_ignora_las_entidades_bloqueadas(self):
        shared = shared_tokens("Abre o Ghidra agora", "Abre el Ghidra ahora", ignore=["Ghidra"])
        self.assertNotIn("ghidra", shared)

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

    def test_sigla_que_es_palabra_corriente_no_se_bloquea(self):
        sentences = ["ELE não sabe, MAS eu sei.", "ele acha que mas não é assim."]
        known = collect_known_terms(sentences)
        self.assertNotIn("ELE", known)
        self.assertNotIn("MAS", known)

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
        locked, mapping = lock_text("Instala o Ghidra 12.1 hoje.")
        self.assertEqual(len(mapping), 2)
        markers = [PLACEHOLDER_TMPL.format(i) for i in sorted(mapping)]
        verdict = check_entities(locked, "Instala el " + " ".join(markers) + " hoy.")
        self.assertTrue(verdict["ok"], verdict["reasons"])

    def test_detecta_entidad_perdida(self):
        locked, _mapping = lock_text("Instala o Ghidra 12.1 hoje.")
        verdict = check_entities(locked, re.sub(re.escape(PLACEHOLDER_TMPL.format(1)) + r"\s*", "", locked))
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
            start=float(seg - 1) * 2.4,
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
            evaluate_segment(seg=1, start=0.0, orig_duration=5.0, raw_duration=5.0,
                             final_duration=5.0, arr=[0.3, -0.3] * 50, chars=80),
            evaluate_segment(seg=2, start=6.0, orig_duration=5.0, raw_duration=5.0,
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

    def _timed(self, seg, start, final, orig, residue=None, ends_phrase=False):
        return evaluate_segment(
            seg=seg, start=start, orig_duration=orig, raw_duration=final,
            final_duration=final, arr=[0.3, -0.3] * 50, chars=40, residue=residue,
            ends_phrase=ends_phrase,
        )

    def test_aire_muerto_no_cuenta_las_pausas_del_original(self):
        """Si el hueco final iguala el de la fuente, no se añadió nada."""
        recs = [
            self._timed(1, 0.0, final=4.0, orig=4.0),
            self._timed(2, 6.0, final=4.0, orig=4.0),
        ]
        report = summarize(recs, expected_segments=2)
        self.assertEqual(report["metrics"]["dead_air_excess"], 0.0)
        self.assertAlmostEqual(report["metrics"]["dead_air_ratio"], 2.0 / 10.0, places=3)

    def test_aire_muerto_detecta_el_hueco_crecido(self):
        recs = [
            self._timed(1, 0.0, final=2.0, orig=4.0),
            self._timed(2, 6.0, final=2.0, orig=4.0),
        ]
        report = summarize(recs, expected_segments=2)
        # hueco final 4.0s vs 2.0s de la fuente → 2.0s añadidos sobre un span de 8.0s
        self.assertAlmostEqual(report["metrics"]["dead_air_excess"], 0.25, places=3)
        self.assertFalse(report["passed"])
        self.assertIn("dead_air_excess", [f["metric"] for f in report["failures"]])

    def test_desvio_ignora_slots_imposibles(self):
        """Un slot de 0.3s no puede medirse: ninguna palabra cabe ahí."""
        recs = [self._timed(i, i * 3.0, final=3.0, orig=3.0) for i in range(1, 10)]
        recs.append(self._timed(10, 27.0, final=0.9, orig=0.3))
        report = summarize(recs, expected_segments=10)
        self.assertNotIn("length_dev_p95", [f["metric"] for f in report["failures"]])

    def test_residuo_de_idioma_falla_el_gate(self):
        recs = [self._timed(1, 0.0, final=3.0, orig=3.0, residue=["Mais"])]
        report = summarize(recs, expected_segments=1)
        self.assertFalse(report["passed"])
        self.assertIn("residue", [f["metric"] for f in report["failures"]])

    def test_aire_muerto_interno_ignora_las_pausas_de_fin_de_frase(self):
        """Tras un punto el silencio es pausa; dentro de la frase es un corte."""
        recs = [
            self._timed(1, 0.0, final=2.0, orig=2.0, ends_phrase=False),
            self._timed(2, 4.0, final=2.0, orig=2.0, ends_phrase=True),
            self._timed(3, 10.0, final=2.0, orig=2.0, ends_phrase=False),
        ]
        report = summarize(recs, expected_segments=3)
        # span 12s: 2s internos (seg 1→2) + 4s de pausa legítima (seg 2→3)
        self.assertAlmostEqual(report["metrics"]["dead_air_mid"], 2.0 / 12.0, places=3)
        self.assertAlmostEqual(report["metrics"]["dead_air_ratio"], 6.0 / 12.0, places=3)

    def test_aire_muerto_interno_es_informativo(self):
        """Un build con silencio interno alto no debe fallar el gate por esta métrica."""
        recs = [
            self._timed(1, 0.0, final=1.0, orig=1.0, ends_phrase=False),
            self._timed(2, 5.0, final=1.0, orig=1.0, ends_phrase=False),
        ]
        report = summarize(recs, expected_segments=2)
        self.assertIn("dead_air_mid", report["metrics"])
        self.assertNotIn("dead_air_mid", [f["metric"] for f in report["failures"]])


    def test_exceso_se_mide_contra_el_arranque_original(self):
        """Adelantar un clip no puede falsear el hueco que añadió el doblaje."""
        recs = [
            evaluate_segment(seg=1, start=0.0, orig_start=0.0, orig_duration=2.0,
                             raw_duration=1.0, final_duration=1.0, arr=[0.3, -0.3] * 50),
            evaluate_segment(seg=2, start=2.55, orig_start=3.0, orig_duration=1.0,
                             raw_duration=1.0, final_duration=1.0, arr=[0.3, -0.3] * 50),
        ]
        report = summarize(recs, expected_segments=2)
        # hueco final 1.55s contra 1.0s de la fuente, sobre un span de 3.55s
        self.assertAlmostEqual(report["metrics"]["dead_air_excess"], 0.55 / 3.55, places=3)

    def test_solape_con_el_siguiente_bloquea(self):
        """Un clip que invade la línea siguiente rompe la fluidez; eso sí bloquea."""
        recs = [
            evaluate_segment(seg=1, start=0.0, orig_duration=2.0, raw_duration=2.5,
                             final_duration=2.5, arr=[0.3, -0.3] * 50),
            evaluate_segment(seg=2, start=2.0, orig_duration=2.0, raw_duration=2.0,
                             final_duration=2.0, arr=[0.3, -0.3] * 50),
        ]
        report = summarize(recs, expected_segments=2)
        self.assertEqual(report["metrics"]["overlap_count"], 1)
        self.assertAlmostEqual(report["metrics"]["overlap_secs"], 0.5, places=3)
        self.assertIn("overlap", [f["metric"] for f in report["failures"]])
        self.assertFalse(report["passed"])

    def test_desborde_absorbido_por_la_pausa_no_bloquea(self):
        recs = [
            evaluate_segment(seg=1, start=0.0, orig_duration=1.0, raw_duration=1.4,
                             final_duration=1.4, arr=[0.3, -0.3] * 50),
            evaluate_segment(seg=2, start=2.0, orig_duration=1.0, raw_duration=1.0,
                             final_duration=1.0, arr=[0.3, -0.3] * 50),
        ]
        report = summarize(recs, expected_segments=2)
        self.assertEqual(report["metrics"]["overlap_count"], 0)
        self.assertNotIn("overlap", [f["metric"] for f in report["failures"]])


if __name__ == "__main__":
    unittest.main()
