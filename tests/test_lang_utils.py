"""Tests de normalización de códigos de idioma."""

import unittest

from src.lang_utils import language_name, same_language


class TestSameLanguage(unittest.TestCase):
    def test_codigos_identicos(self):
        self.assertTrue(same_language("pt", "pt"))
        self.assertTrue(same_language("EN", "en"))

    def test_regional_contra_base(self):
        """El caso real: pedir 'pt-BR' sobre un audio 'pt' no debe traducir pt→pt."""
        self.assertTrue(same_language("pt-BR", "pt"))
        self.assertTrue(same_language("pt", "pt-BR"))

    def test_separadores_distintos(self):
        self.assertTrue(same_language("pt_BR", "pt-br"))
        self.assertTrue(same_language("zh_Hans", "zh"))

    def test_idiomas_distintos(self):
        self.assertFalse(same_language("pt", "es"))
        self.assertFalse(same_language("pt-BR", "es-ES"))
        self.assertFalse(same_language("en", "pt-BR"))

    def test_espacios_alrededor(self):
        self.assertTrue(same_language(" pt ", "pt-BR"))


class TestLanguageName(unittest.TestCase):
    def test_nombre_conocido_y_regional(self):
        self.assertEqual(language_name("es"), "Español")
        self.assertEqual(language_name("pt-BR"), "Portugués")

    def test_codigo_desconocido_no_cae_a_espanol(self):
        """Un fallback silencioso a español traduciría al idioma equivocado."""
        self.assertEqual(language_name("xx"), "xx")
        self.assertEqual(language_name("tlh"), "tlh")

    def test_codigo_vacio(self):
        self.assertEqual(language_name(""), "el idioma original")

    def test_none_textual_no_se_usa_como_idioma(self):
        self.assertEqual(language_name("None"), "el idioma original")
        self.assertEqual(language_name(None), "el idioma original")


if __name__ == "__main__":
    unittest.main()
