"""
Tests de la revisión pre-TTS (stdlib, sin pytest).

Ejecutar desde la raíz del repo:
    python -m unittest tests.test_review -v
"""
from __future__ import annotations

import unittest

from src.review import (
    apply_term_map,
    audit_summary,
    build_term_prompt,
    collect_term_variants,
    levenshtein,
    parse_review_map,
    parse_term_groups,
)


class TestVariantesAsr(unittest.TestCase):
    def test_encuentra_variantes_a_mitad_de_frase(self):
        texts = [
            "Uso Guidra para analizar el binario.",
            "Ghidra es la herramienta correcta.",
            "Entre Guidra y Ghidra hay una letra.",
        ]
        terms = {c["term"] for c in collect_term_variants(texts)}
        self.assertIn("Guidra", terms)
        self.assertIn("Ghidra", terms)
        # 'Uso' solo abre frase: no es una marca.
        self.assertNotIn("Uso", terms)

    def test_ignora_palabras_que_tambien_van_en_minuscula(self):
        texts = ["Mira Guidra.", "Después guidra otra vez."]
        terms = {c["term"] for c in collect_term_variants(texts)}
        self.assertNotIn("Guidra", terms)

    def test_ignora_capitalizadas_solo_de_inicio_de_frase(self):
        texts = ["Central funciona bien.", "Central no falla."]
        terms = {c["term"] for c in collect_term_variants(texts)}
        self.assertNotIn("Central", terms)

    def test_no_se_come_la_puntuacion_final(self):
        texts = ["Uso Guidra. Y también Ghidra.", "Guidra y Ghidra."]
        terms = {c["term"] for c in collect_term_variants(texts)}
        self.assertIn("Guidra", terms)
        self.assertIn("Ghidra", terms)
        self.assertNotIn("Guidra.", terms)

    def test_respeta_la_lista_de_ignorados(self):
        texts = ["Uso Guidra.", "Uso Ghidra."]
        terms = {
            c["term"] for c in collect_term_variants(texts, ignore=["Guidra"])
        }
        self.assertNotIn("Guidra", terms)
        self.assertIn("Ghidra", terms)


class TestParseTermGroups(unittest.TestCase):
    def test_agrupa_variantes_conocidas(self):
        raw = {
            "grupos": [
                {"variantes": ["Guidra", "Ghidra"], "canonica": "Ghidra"},
                {"variantes": ["DeepSeq", "DeepSeek"], "canonica": "DeepSeek"},
            ]
        }
        mapping = parse_term_groups(raw, ["Guidra", "Ghidra", "DeepSeq", "DeepSeek"])
        self.assertEqual(mapping["Guidra"], "Ghidra")
        self.assertEqual(mapping["DeepSeq"], "DeepSeek")

    def test_descarta_canonica_inventada(self):
        raw = {"grupos": [{"variantes": ["Guidra", "Ghidra"], "canonica": "Ghidra Pro"}]}
        self.assertEqual(parse_term_groups(raw, ["Guidra", "Ghidra"]), {})

    def test_descarta_grupo_con_una_sola_variante_real(self):
        raw = {"grupos": [{"variantes": ["Guidra", "Inventada"], "canonica": "Ghidra"}]}
        self.assertEqual(parse_term_groups(raw, ["Guidra", "Ghidra"]), {})

    def test_descarta_canonica_en_minuscula(self):
        raw = {"grupos": [{"variantes": ["Guidra", "Ghidra"], "canonica": "ghidra"}]}
        self.assertEqual(parse_term_groups(raw, ["Guidra", "Ghidra"]), {})

    def test_respuesta_invalida_no_rompe(self):
        self.assertEqual(parse_term_groups("nada", ["Guidra"]), {})
        self.assertEqual(parse_term_groups({"grupos": "x"}, ["Guidra"]), {})

    def test_no_unifica_singular_y_plural(self):
        # Una variación de número no es una variante de grafía: unificarla
        # reescribiría el guion y rompería la concordancia.
        raw = {"grupos": [{"variantes": ["Zorbal", "Zorbals"], "canonica": "Zorbals"}]}
        self.assertEqual(parse_term_groups(raw, ["Zorbal", "Zorbals"]), {})

    def test_no_unifica_plural_con_es(self):
        raw = {"grupos": [{"variantes": ["Trepix", "Trepixes"], "canonica": "Trepixes"}]}
        self.assertEqual(parse_term_groups(raw, ["Trepix", "Trepixes"]), {})

    def test_sigue_unificando_erratas_reales(self):
        raw = {"grupos": [{"variantes": ["Guidra", "Ghidra"], "canonica": "Ghidra"}]}
        self.assertEqual(
            parse_term_groups(raw, ["Guidra", "Ghidra"]), {"Guidra": "Ghidra"}
        )


class TestTermPrompt(unittest.TestCase):
    def test_no_sesga_con_ejemplos_de_pares_de_palabras(self):
        prompt = build_term_prompt(
            [{"term": "Alpha", "count": 2, "context": "Alpha aparece aquí."}],
            "English",
        )
        for example in (
            "Guidra",
            "Ghidra",
            "DeepSeq",
            "DeepSeek",
            "America",
            "Empire",
        ):
            self.assertNotIn(example, prompt)
        self.assertIn("variación gramatical", prompt)


class TestApplyTermMap(unittest.TestCase):
    def test_reemplaza_solo_palabra_completa(self):
        texts = ["Uso Guidra 12.1.", "GuidraX no se toca."]
        out, changed = apply_term_map(texts, {"Guidra": "Ghidra"})
        self.assertEqual(out[0], "Uso Ghidra 12.1.")
        self.assertEqual(out[1], "GuidraX no se toca.")
        self.assertEqual(changed, 1)

    def test_sin_mapa_devuelve_copia(self):
        texts = ["Uso Guidra."]
        out, changed = apply_term_map(texts, {})
        self.assertEqual(out, texts)
        self.assertEqual(changed, 0)
        self.assertIsNot(out, texts)

    def test_escapa_caracteres_de_regex(self):
        out, changed = apply_term_map(["C++ y C#"], {"C++": "Cpp"})
        self.assertEqual(out[0], "Cpp y C#")
        self.assertEqual(changed, 1)


class TestParseReviewMap(unittest.TestCase):
    def test_filtra_claves_y_valores_vacios(self):
        raw = {"1": "texto", "2": "", "3": 5, "9": "sobra"}
        out = parse_review_map(raw, ["1", "2", "3"])
        self.assertEqual(out, {"1": "texto"})

    def test_respuesta_no_dict(self):
        self.assertEqual(parse_review_map(["x"], ["1"]), {})


class TestLevenshtein(unittest.TestCase):
    def test_distancias_basicas(self):
        self.assertEqual(levenshtein("Guidra", "Ghidra"), 1)
        self.assertEqual(levenshtein("", "abc"), 3)
        self.assertEqual(levenshtein("igual", "igual"), 0)


class TestAuditSummary(unittest.TestCase):
    def test_resume_por_motivo(self):
        flagged = [
            {"motivo": "residuo: central"},
            {"motivo": "duración: desvío +30%"},
            {"motivo": "residuo: vertical | duración: desvío -40%"},
        ]
        summary = audit_summary(flagged)
        self.assertIn("3 segmento(s)", summary)
        self.assertIn("duración 2", summary)
        self.assertIn("residuo 2", summary)

    def test_sin_marcas_devuelve_vacio(self):
        self.assertEqual(audit_summary([]), "")


if __name__ == "__main__":
    unittest.main()
