"""
Tests del diccionario de pronunciación: validación de la notación, una regla por
palabra en todo el lote y cobertura de los términos que el traductor no ve.

Ejecutar desde la raíz del repo:
    python -m unittest tests.test_pronunciation -v
"""
from __future__ import annotations

import unittest

from src.pronunciation import (
    apply_table,
    build_respelling_prompt,
    consolidate,
    missing_terms,
    validate_rule,
)


class TestValidateRule(unittest.TestCase):
    def test_respelling_romance_valido(self):
        rule = validate_rule("OpenCode", "open-coud", "es")
        self.assertIsNotNone(rule)
        self.assertEqual(rule["value"], "open-coud")
        self.assertFalse(rule["case_sensitive"])

    def test_sigla_queda_case_sensitive(self):
        rule = validate_rule("API", "a-pe-i", "es")
        self.assertTrue(rule["case_sensitive"])

    def test_respelling_en_otros_alfabetos(self):
        """La validación es de escritura, no de un alfabeto concreto."""
        self.assertIsNotNone(validate_rule("Москва", "масква", "ru"))
        self.assertIsNotNone(validate_rule("東京", "とうきょう", "ja"))
        self.assertIsNotNone(validate_rule("Αθήνα", "α-θί-να", "el"))

    def test_valor_con_numeros_o_signos_se_rechaza(self):
        self.assertIsNone(validate_rule("X", "a1", "es"))
        self.assertIsNone(validate_rule("X", "a+b", "es"))

    def test_valor_identico_a_la_clave_no_aporta(self):
        self.assertIsNone(validate_rule("desktop", "desktop", "es"))

    def test_caracteres_fuera_de_la_ortografia(self):
        # Letras de cualquier alfabeto valen; signos y números no.
        self.assertIsNone(validate_rule("SQL", "sɛk+wəl", "es"))
        self.assertIsNone(validate_rule("X", "a<b", "es"))

    def test_marcadores_de_fonema_prohibidos(self):
        self.assertIsNone(validate_rule("X", "<|phoneme_start|>a<|phoneme_end|>", "es"))

    def test_limites_de_la_api(self):
        self.assertIsNone(validate_rule("X", "a" * 1025, "es"))
        self.assertIsNone(validate_rule("X" * 257, "a", "es"))

    def test_ingles_exige_arpabet(self):
        self.assertIsNotNone(validate_rule("Kubernetes", "K UW2 B ER0 N EH1 T IY0 Z", "en"))
        self.assertIsNone(validate_rule("Kubernetes", "ku-ber-ne-tes", "en"))
        self.assertIsNone(validate_rule("Kubernetes", "K UX2 B ER0", "en"))

class TestConsolidate(unittest.TestCase):
    def test_una_sola_regla_por_palabra(self):
        """El modelo escribe segmento a segmento: la misma palabra no puede sonar distinto."""
        tables = [
            {"opencode": "open-coud"},
            {"opencode": "open-coud"},
            {"opencode": "opencod"},
        ]
        chosen, display, conflicts = consolidate(tables, "es")
        self.assertEqual(chosen["opencode"]["value"], "open-coud")
        self.assertEqual(display["opencode"], "opencode")
        self.assertEqual(len(conflicts), 1)
        self.assertIn("opencod", conflicts[0])

    def test_reglas_invalidas_no_votan(self):
        tables = [{"SQL": "e1"}, {"SQL": "ese-cu-ele"}]
        chosen, _display, _conflicts = consolidate(tables, "es")
        self.assertEqual(chosen["sql"]["value"], "ese-cu-ele")

    def test_sin_reglas_validas_devuelve_vacio(self):
        chosen, display, conflicts = consolidate([{"X": "a1"}], "es")
        self.assertEqual(chosen, {})
        self.assertEqual(display, {})
        self.assertEqual(conflicts, [])

    def test_empate_gana_la_primera_aparicion(self):
        tables = [{"Cursor": "cúr-sor"}, {"Cursor": "cur-sor"}]
        chosen, _display, _conflicts = consolidate(tables, "es")
        self.assertEqual(chosen["cursor"]["value"], "cúr-sor")


class TestApplyTable(unittest.TestCase):
    def test_solo_entra_lo_que_esta_en_el_texto(self):
        tables = [{"npm": "ene-pe-eme"}, {"clear": "clir"}]
        chosen, display, _ = consolidate(tables, "es")
        rules = apply_table("Instala con npm ahora.", tables[0], chosen, display)
        self.assertEqual(rules, {"npm": "ene-pe-eme"})

    def test_regla_muerta_no_entra(self):
        """'clear' traducido a 'limpiar': la regla nunca dispararía."""
        tables = [{"clear": "clir"}]
        chosen, display, _ = consolidate(tables, "es")
        self.assertEqual(apply_table("Vamos a limpiar y pegarlo.", tables[0], chosen, display), {})

    def test_cobertura_extra_entra_si_la_clave_esta_en_el_texto(self):
        extra = {"ghidra": validate_rule("Ghidra", "guidra", "es")}
        rules = apply_table("Abre el Ghidra ahora.", {}, {}, {}, extra)
        self.assertEqual(rules, {"Ghidra": "guidra"})

    def test_tope_por_segmento(self):
        tables = [{f"w{i}": f"w{i}-x" for i in range(60)}]
        chosen, display, _ = consolidate(tables, "es")
        text = " ".join(f"w{i}" for i in range(60))
        self.assertLessEqual(len(apply_table(text, tables[0], chosen, display)), 32)


class TestCoverage(unittest.TestCase):
    def test_entidad_bloqueada_sin_regla_se_pide(self):
        """El traductor nunca ve las entidades: son las que más necesitan respelling."""
        texts = ["Abre el Ghidra y usa el MCP."]
        pending = missing_terms(texts, ["Ghidra", "MCP", "Nemotron"], {})
        self.assertEqual(pending, ["Ghidra", "MCP"])

    def test_termino_con_regla_no_se_repite(self):
        chosen, _display, _ = consolidate([{"Ghidra": "guidra"}], "es")
        self.assertEqual(missing_terms(["Abre el Ghidra"], ["Ghidra"], chosen), [])

    def test_termino_ausente_del_guion_no_se_pide(self):
        self.assertEqual(missing_terms(["Nada que ver"], ["Nemotron"], {}), [])

    def test_prompt_declara_las_convenciones(self):
        prompt = build_respelling_prompt(["Ghidra", "MCP"], "Español")
        self.assertIn("Español", prompt)
        self.assertIn("null", prompt)
        self.assertIn("Ghidra", prompt)
        # No hay ejemplos en un idioma concreto que confundan a otros destinos.
        self.assertNotIn("guindous", prompt)
        self.assertNotIn("jota-de-ka", prompt)

    def test_ingles_pide_arpabet(self):
        """La validación de inglés exige Arpabet; el prompt tiene que pedirlo."""
        prompt = build_respelling_prompt(["Ghidra"], "Inglés", "en")
        self.assertIn("Arpabet", prompt)
        self.assertNotIn("solo letras de Inglés", prompt)


if __name__ == "__main__":
    unittest.main()
