"""Tests de normalización de códigos de idioma."""

import unittest

from src.lang_utils import same_language


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


if __name__ == "__main__":
    unittest.main()
