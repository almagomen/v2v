"""Pruebas del etiquetado automático de emociones de Fish Audio."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from src import audio_utils, fish_enhance
from src.config import (
    get_fish_auto_emotions,
    get_fish_enhance_version,
    set_fish_auto_emotions,
    set_fish_enhance_version,
)


class FakeResponse:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class TestFishEnhance(unittest.TestCase):
    def setUp(self):
        self._old_enabled = os.environ.get("V2V_FISH_AUTO_EMOTIONS")
        self._old_version = os.environ.get("V2V_FISH_ENHANCE_VERSION")
        os.environ.pop("V2V_FISH_AUTO_EMOTIONS", None)
        os.environ.pop("V2V_FISH_ENHANCE_VERSION", None)
        fish_enhance.reset_disable_state()

    def tearDown(self):
        for key, value in (
            ("V2V_FISH_AUTO_EMOTIONS", self._old_enabled),
            ("V2V_FISH_ENHANCE_VERSION", self._old_version),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _enhance(self, text, script, version="s2.1-pro", log_fn=None):
        with patch("src.config.get_fish_api_key", return_value="test-key"), patch(
            "src.fish_enhance.requests.post",
            return_value=FakeResponse(200, {"enhanced_script": script}),
        ):
            return fish_enhance.enhance_text(
                text,
                version=version,
                max_retries=0,
                log_fn=log_fn,
            )

    def test_usa_la_respuesta_de_fish_tal_cual(self):
        script = "[angry] No funciona nada [short pause] y estoy muy frustrado."
        out = self._enhance("No funciona nada y estoy muy frustrado.", script)
        self.assertEqual(out, script)

    def test_no_separa_etiquetas_pegadas_a_la_palabra(self):
        script = "Los marineros lanzan un [emphasis]cable hasta el barco."
        out = self._enhance("Los marineros lanzan un cable hasta el barco.", script)
        self.assertEqual(out, script)

    def test_conserva_la_emocion_inicial_del_usuario(self):
        out = self._enhance(
            "[excited] Pero el proceso es igual de complejo.",
            "[excited] [happy] Pero el proceso es igual de complejo.",
        )
        self.assertTrue(out.startswith("[excited] Pero el proceso"))
        self.assertNotIn("[happy]", out)

    def test_no_valida_reescrituras(self):
        script = "[happy] Un texto completamente distinto que no tiene nada que ver."
        out = self._enhance(
            "Los marineros lanzan un cable hasta el barco receptor.",
            script,
        )
        self.assertEqual(out, script)

    def test_siempre_llama_a_fish_sin_cache(self):
        with patch("src.config.get_fish_api_key", return_value="test-key"), patch(
            "src.fish_enhance.requests.post",
            return_value=FakeResponse(200, {"enhanced_script": "[calm] Hola mundo."}),
        ) as post:
            first = fish_enhance.enhance_text("Hola mundo.", max_retries=0)
            second = fish_enhance.enhance_text("Hola mundo.", max_retries=0)

        self.assertEqual(first, "[calm] Hola mundo.")
        self.assertEqual(second, "[calm] Hola mundo.")
        self.assertEqual(post.call_count, 2)

    def test_registra_el_fallo_en_el_log(self):
        logs: list[str] = []
        with patch("src.config.get_fish_api_key", return_value="test-key"), patch(
            "src.fish_enhance.requests.post",
            return_value=FakeResponse(500),
        ):
            out = fish_enhance.enhance_text(
                "Hola mundo.", max_retries=0, log_fn=logs.append
            )
        self.assertIsNone(out)
        self.assertTrue(any("Falló /enhance/text" in msg for msg in logs))

    def test_401_desactiva_el_endpoint_una_sola_vez(self):
        logs: list[str] = []
        with patch("src.config.get_fish_api_key", return_value="test-key"), patch(
            "src.fish_enhance.requests.post",
            return_value=FakeResponse(401, text="Invalid token"),
        ) as post:
            first = fish_enhance.enhance_text(
                "Hola mundo.", max_retries=2, log_fn=logs.append
            )
            second = fish_enhance.enhance_text(
                "Otra frase.", max_retries=2, log_fn=logs.append
            )

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(post.call_count, 1)
        disabled_logs = [msg for msg in logs if "desactivado" in msg]
        self.assertEqual(len(disabled_logs), 1)
        self.assertTrue(any("HTTP 401" in msg for msg in logs))

    def test_403_y_404_tambien_desactivan(self):
        for status in (403, 404):
            fish_enhance.reset_disable_state()
            with patch("src.config.get_fish_api_key", return_value="test-key"), patch(
                "src.fish_enhance.requests.post",
                return_value=FakeResponse(status),
            ) as post:
                fish_enhance.enhance_text("Hola mundo.", max_retries=2)
                fish_enhance.enhance_text("Otra frase.", max_retries=2)
            self.assertEqual(post.call_count, 1, f"status {status}")

    def test_400_no_reintenta_ni_desactiva(self):
        logs: list[str] = []
        with patch("src.config.get_fish_api_key", return_value="test-key"), patch(
            "src.fish_enhance.requests.post",
            return_value=FakeResponse(400, text="bad payload"),
        ) as post:
            first = fish_enhance.enhance_text(
                "Hola mundo.", max_retries=2, log_fn=logs.append
            )
        self.assertIsNone(first)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(any("HTTP 400" in msg for msg in logs))

        with patch("src.config.get_fish_api_key", return_value="test-key"), patch(
            "src.fish_enhance.requests.post",
            return_value=FakeResponse(200, {"enhanced_script": "[calm] Hola."}),
        ) as post_ok:
            out = fish_enhance.enhance_text("Hola mundo.", max_retries=0)
        self.assertEqual(out, "[calm] Hola.")
        self.assertEqual(post_ok.call_count, 1)

    def test_registra_el_fallo_sin_api_key(self):
        logs: list[str] = []
        with patch("src.config.get_fish_api_key", return_value=None):
            out = fish_enhance.enhance_text(
                "Hola mundo.", max_retries=0, log_fn=logs.append
            )
        self.assertIsNone(out)
        self.assertTrue(any("FISH_API_KEY" in msg for msg in logs))

    def test_no_llama_a_fish_si_solo_hay_etiquetas(self):
        with patch("src.fish_enhance.requests.post") as post:
            out = fish_enhance.enhance_text("[UH] [lipsmack]")
        self.assertIsNone(out)
        post.assert_not_called()

    def test_interruptor_activado_por_defecto_y_version_drama_3(self):
        self.assertTrue(get_fish_auto_emotions())
        set_fish_auto_emotions(False)
        self.assertFalse(get_fish_auto_emotions())
        set_fish_auto_emotions(True)
        self.assertTrue(get_fish_auto_emotions())

        set_fish_enhance_version("drama-3")
        self.assertEqual(get_fish_enhance_version(), "drama-3")
        with self.assertRaises(ValueError):
            set_fish_enhance_version("s2-pro")
        with self.assertRaises(ValueError):
            set_fish_enhance_version("s1")

    def test_apply_auto_emotions_actualiza_el_texto_del_segmento(self):
        segments = [{"text": "Hola mundo."}, {"text": "Otra frase."}]
        with patch(
            "src.fish_enhance.enhance_texts",
            return_value=["[happy] Hola mundo.", None],
        ):
            audio_utils.apply_auto_emotions_to_segments(segments, enabled=True)

        self.assertEqual(segments[0]["text"], "[happy] Hola mundo.")
        self.assertEqual(segments[1]["text"], "Otra frase.")

    def test_las_etiquetas_se_persisten_en_result_json(self):
        from src.result_store import load_result, save_result, update_result_segments

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            save_result(
                folder,
                {
                    "output_name": "demo",
                    "segments": [
                        {"seg": 1, "text": "Hola mundo.", "start": 0.0, "end": 1.0}
                    ],
                },
            )

            segments = load_result(folder)["segments"]
            with patch(
                "src.fish_enhance.enhance_texts",
                return_value=["[happy] Hola mundo."],
            ):
                audio_utils.apply_auto_emotions_to_segments(segments, enabled=True)
            update_result_segments(folder, segments)

            saved = load_result(folder)
            self.assertEqual(saved["segments"][0]["text"], "[happy] Hola mundo.")


if __name__ == "__main__":
    unittest.main()
