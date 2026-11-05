"""Pruebas del etiquetado automático de emociones de Fish Audio."""
import os
import unittest
from unittest.mock import patch

import requests

from src import fish_enhance
from src.config import (
    get_fish_auto_emotions,
    get_fish_enhance_version,
    set_fish_auto_emotions,
    set_fish_enhance_version,
)


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class TestFishEnhance(unittest.TestCase):
    def setUp(self):
        fish_enhance.clear_cache()

    def _enhance(self, text, script, version="s2.1-pro"):
        with patch("src.config.get_fish_api_key", return_value="test-key"), patch(
            "src.fish_enhance.requests.post",
            return_value=FakeResponse(200, {"enhanced_script": script}),
        ):
            return fish_enhance.enhance_text(text, version=version, max_retries=0)

    def test_anade_etiquetas_y_normaliza_pausas(self):
        out = self._enhance(
            "No funciona nada y estoy muy frustrado.",
            "[angry] No funciona nada [short pause] y estoy muy frustrado.",
        )
        self.assertEqual(
            out,
            "[angry] No funciona nada [break] y estoy muy frustrado.",
        )

    def test_separa_etiqueta_pegada_a_la_palabra(self):
        out = self._enhance(
            "Los marineros lanzan un cable.",
            "Los marineros lanzan un [emphasis]cable.",
        )
        self.assertEqual(out, "Los marineros lanzan un [emphasis] cable.")

    def test_conserva_la_emocion_del_usuario(self):
        out = self._enhance(
            "[excited] Pero el proceso es igual de complejo.",
            "[excited] [happy] Pero el proceso es igual de complejo.",
        )
        self.assertTrue(out.startswith("[excited] Pero el proceso"))
        self.assertNotIn("[happy]", out)

    def test_acepta_separar_siglas_sin_reescribir(self):
        out = self._enhance(
            "TLOUS dos tiene la memoria a tope.",
            "[emphasis] T L O U S dos tiene la memoria a tope.",
        )
        self.assertIsNotNone(out)
        self.assertIn("T L O U S", out)

    def test_descarta_reescrituras_destructivas(self):
        out = self._enhance(
            "Los marineros lanzan un cable hasta el barco receptor.",
            "[happy] Un texto completamente distinto que no tiene nada que ver.",
        )
        self.assertIsNone(out)

    def test_cache_evita_una_segunda_llamada(self):
        with patch("src.config.get_fish_api_key", return_value="test-key"), patch(
            "src.fish_enhance.requests.post",
            return_value=FakeResponse(200, {"enhanced_script": "[calm] Hola mundo."}),
        ) as post:
            first = fish_enhance.enhance_text("Hola mundo.", max_retries=0)
            second = fish_enhance.enhance_text("Hola mundo.", max_retries=0)

        self.assertEqual(first, second)
        self.assertEqual(post.call_count, 1)

    def test_devuelve_none_si_la_api_falla(self):
        with patch("src.config.get_fish_api_key", return_value="test-key"), patch(
            "src.fish_enhance.requests.post",
            return_value=FakeResponse(500),
        ):
            out = fish_enhance.enhance_text("Hola mundo.", max_retries=0)
        self.assertIsNone(out)

    def test_devuelve_none_sin_api_key(self):
        with patch("src.config.get_fish_api_key", return_value=None):
            out = fish_enhance.enhance_text("Hola mundo.")
        self.assertIsNone(out)

    def test_no_llama_a_fish_si_solo_hay_etiquetas(self):
        with patch("src.fish_enhance.requests.post") as post:
            out = fish_enhance.enhance_text("[UH] [lipsmack]")
        self.assertIsNone(out)
        post.assert_not_called()

    def test_interruptor_y_version_desde_entorno(self):
        old_enabled = os.environ.get("V2V_FISH_AUTO_EMOTIONS")
        old_version = os.environ.get("V2V_FISH_ENHANCE_VERSION")
        try:
            set_fish_auto_emotions(True)
            self.assertTrue(get_fish_auto_emotions())
            set_fish_auto_emotions(False)
            self.assertFalse(get_fish_auto_emotions())

            set_fish_enhance_version("s2-pro")
            self.assertEqual(get_fish_enhance_version(), "s2-pro")
            with self.assertRaises(ValueError):
                set_fish_enhance_version("s1")
        finally:
            if old_enabled is None:
                os.environ.pop("V2V_FISH_AUTO_EMOTIONS", None)
            else:
                os.environ["V2V_FISH_AUTO_EMOTIONS"] = old_enabled
            if old_version is None:
                os.environ.pop("V2V_FISH_ENHANCE_VERSION", None)
            else:
                os.environ["V2V_FISH_ENHANCE_VERSION"] = old_version


if __name__ == "__main__":
    unittest.main()
