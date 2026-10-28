"""Tests del presupuesto de duración (isocronía) — módulo puro, sin red ni torch."""

import json
import unittest

from src.pacing import (
    DEFAULT_RATE,
    FIT_MAX,
    FIT_MIN,
    REWRITE_LONG,
    REWRITE_SHORT,
    SPEECH_RATES,
    budget_for,
    build_fit_prompt,
    estimate_seconds,
    fit_deviation,
    needs_rewrite,
    primary_lang,
    speech_rate,
    visible_text,
)


class TestTasas(unittest.TestCase):
    def test_codigo_regional_usa_la_tasa_del_idioma(self):
        self.assertEqual(primary_lang("pt-BR"), "pt")
        self.assertEqual(speech_rate("pt-BR"), SPEECH_RATES["pt"])
        self.assertEqual(speech_rate("ES-es"), SPEECH_RATES["es"])

    def test_idioma_desconocido_cae_al_promedio(self):
        self.assertEqual(speech_rate("ko"), DEFAULT_RATE)
        self.assertEqual(speech_rate(""), DEFAULT_RATE)

    def test_tasas_calibradas_en_rango_plausible(self):
        """Regresión: se calibraron con audio real (16.0 chars/s en es y pt)."""
        for lang, (syl, chars) in SPEECH_RATES.items():
            with self.subTest(lang=lang):
                self.assertGreater(chars, 12.0, "tasa absurda: el doblaje quedaría corto")
                self.assertLess(chars, 22.0, "tasa absurda: el doblaje se aceleraría")
                self.assertGreater(syl, 3.0)
                self.assertLess(syl, 8.0)


class TestTextoVisible(unittest.TestCase):
    def test_quita_etiquetas_de_emocion(self):
        self.assertEqual(visible_text("[excited] Hola mundo"), "Hola mundo")
        self.assertEqual(visible_text("[a][b]  dos   espacios"), "dos espacios")

    def test_marcador_cuenta_el_termino_real(self):
        texto = "Instala ⟦E1⟧ en el servidor"
        mapa = {1: "Malwarebytes.exe"}
        self.assertIn("Malwarebytes.exe", visible_text(texto, mapa))
        self.assertEqual(len(visible_text(texto, mapa)), len("Instala Malwarebytes.exe en el servidor"))

    def test_marcador_sin_mapa_usa_longitud_neutra(self):
        self.assertEqual(visible_text("usa ⟦E7⟧ ya"), "usa xxxxxx ya")


class TestEstimacion(unittest.TestCase):
    def test_160_chars_en_es_son_10_segundos(self):
        texto = "a" * 160
        self.assertAlmostEqual(estimate_seconds(texto, "es"), 10.0, places=3)

    def test_duracion_crece_con_el_texto(self):
        corto = estimate_seconds("hola mundo", "es")
        largo = estimate_seconds("hola mundo " * 10, "es")
        self.assertLess(corto, largo)

    def test_slot_invalido_no_divide_por_cero(self):
        self.assertEqual(fit_deviation("hola", "es", 0.0), 0.0)
        self.assertEqual(budget_for("es", 0.0)["chars_max"], 0)


class TestPresupuesto(unittest.TestCase):
    def test_rango_rodea_el_objetivo(self):
        b = budget_for("es", 10.0)
        objetivo = 10.0 * SPEECH_RATES["es"][1]
        self.assertLess(b["chars_min"], objetivo)
        self.assertGreater(b["chars_max"], objetivo)
        self.assertAlmostEqual(b["chars_min"], objetivo * FIT_MIN, delta=2)
        self.assertAlmostEqual(b["chars_max"], objetivo * FIT_MAX, delta=2)
        # El objetivo único corrige la tendencia a quedarse corto (medido: -6%).
        self.assertAlmostEqual(b["chars_target"], objetivo, delta=1)
        self.assertGreaterEqual(b["chars_target"], b["chars_min"])
        self.assertLessEqual(b["chars_target"], b["chars_max"])

    def test_rango_ordenado_y_positivo(self):
        for sec in (0.4, 1.0, 3.5, 12.0):
            with self.subTest(sec=sec):
                b = budget_for("es", sec)
                self.assertLess(b["chars_min"], b["chars_max"])
                self.assertLess(b["syl_min"], b["syl_max"])
                self.assertGreater(b["syl_min"], 0)


class TestNecesitaReescritura(unittest.TestCase):
    def test_texto_muy_corto_dispara(self):
        """Caso real de aire muerto: 16 chars en un slot de 10 s."""
        self.assertTrue(needs_rewrite("Ahora vamos allá", "es", 10.0))

    def test_texto_muy_largo_dispara(self):
        self.assertTrue(needs_rewrite("palabra " * 60, "es", 3.0))

    def test_texto_encajado_no_dispara(self):
        justo = "a" * int(10.0 * SPEECH_RATES["es"][1])
        self.assertFalse(needs_rewrite(justo, "es", 10.0))

    def test_frase_de_dos_palabras_no_se_toca(self):
        self.assertFalse(needs_rewrite("Sí, claro", "es", 10.0))

    def test_sin_tiempos_no_hay_reescritura(self):
        self.assertFalse(needs_rewrite("texto cualquiera", "es", 0.0))

    def test_umbrales_son_asimetricos(self):
        """Corto dispara antes que largo: el silencio muerto se nota más que la compresión."""
        objetivo = int(10.0 * SPEECH_RATES["es"][1])
        casi_corto = "a" * int(objetivo * (1 - REWRITE_SHORT + 0.03)) + " bb"
        casi_largo = "a" * int(objetivo * (1 + REWRITE_LONG - 0.05)) + " bb"
        self.assertFalse(needs_rewrite(casi_corto, "es", 10.0))
        self.assertFalse(needs_rewrite(casi_largo, "es", 10.0))
        self.assertLess(REWRITE_SHORT, REWRITE_LONG)


class TestPromptDeEncaje(unittest.TestCase):
    def test_incluye_objetivo_y_reglas(self):
        items = {"1": {"texto": "Hola", "objetivo": "150-176 caracteres", "estado": "corto"}}
        prompt = build_fit_prompt(items, "español")
        self.assertIn("150-176 caracteres", prompt)
        self.assertIn("⟦E1⟧", prompt)
        self.assertIn("español", prompt)

    def test_entrada_es_json_valido(self):
        items = {"1": {"texto": "Hola", "objetivo": "10-12 caracteres", "estado": "corto"}}
        prompt = build_fit_prompt(items, "español")
        bloque = prompt.split("Entrada:\n", 1)[1].split("\n\nDevuelve", 1)[0]
        self.assertEqual(json.loads(bloque), items)


if __name__ == "__main__":
    unittest.main()
