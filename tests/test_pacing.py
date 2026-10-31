"""Tests del presupuesto de duración (isocronía) — módulo puro, sin red ni torch."""

import json
import unittest

from src.pacing import (
    DEFAULT_RATE,
    FIT_MAX,
    FIT_MIN,
    RIPPLE_GAP,
    RIPPLE_PAYBACK_MAX,
    RIPPLE_KEEP,
    RIPPLE_SHIFT_MAX,
    RIPPLE_STEP_MAX,
    REWRITE_LONG,
    REWRITE_SHORT,
    SPEECH_RATES,
    budget_for,
    build_fit_prompt,
    close_ripple,
    echoed_texts,
    ends_sentence,
    estimate_seconds,
    fit_deviation,
    gap_split,
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
    def test_no_ofrece_un_ejemplo_literal(self):
        """Un ejemplo literal en el prompt se colaba como texto en el TTS."""
        prompt = build_fit_prompt({"1": {"texto": "Hola", "objetivo": "10-12 caracteres"}}, "español")
        self.assertNotIn("texto ajustado", prompt)

    def test_descarta_el_texto_repetido_entre_segmentos(self):
        """Misma cadena para claves distintas = eco de la plantilla, no traducción."""
        fitted = {"1": "texto ajustado", "2": "texto ajustado", "3": "Otra cosa distinta."}
        self.assertEqual(echoed_texts(fitted), {"texto ajustado"})

    def test_no_descarta_textos_distintos(self):
        self.assertEqual(echoed_texts({"1": "Uno.", "2": "Dos."}), set())


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


class TestFinDeFrase(unittest.TestCase):
    def test_puntuacion_terminal_cierra_frase(self):
        for texto in ("Ya está.", "¿Vamos?", "¡Claro!", "Bueno…", "Dijo: «sí.»"):
            with self.subTest(texto=texto):
                self.assertTrue(ends_sentence(texto))

    def test_coma_y_dos_puntos_no_cierran(self):
        for texto in ("Primero, abre el panel", "Haz esto:", "y después"):
            with self.subTest(texto=texto):
                self.assertFalse(ends_sentence(texto))

    def test_etiqueta_de_emocion_no_tapa_el_punto(self):
        self.assertTrue(ends_sentence("[excited] Listo."))
        self.assertFalse(ends_sentence("[excited] Listo"))


class TestCierreDeRipple(unittest.TestCase):
    def test_hueco_anadido_por_el_doblaje_se_cierra(self):
        """El clip salió corto: la fuente habló hasta 2.2s y el TTS acabó en 1.0s."""
        nuevos = close_ripple([0.0, 3.0], [1.0, 1.0], [2.2, 4.0])
        self.assertAlmostEqual(nuevos[1], 3.0 - RIPPLE_STEP_MAX, places=3)

    def test_pausa_del_original_se_respeta(self):
        """Si la fuente ya callaba 0.8s, no hay silencio añadido que quitar."""
        nuevos = close_ripple([0.0, 3.0], [2.2, 1.0], [2.2, 4.0])
        self.assertEqual(nuevos[1], 3.0)

    def test_respiro_minimo_conservado(self):
        """Con 0.5s de exceso se conserva el respiro de 0.12s entre palabras."""
        nuevos = close_ripple([0.0, 3.0], [2.5, 1.0], [2.95, 4.0])
        self.assertAlmostEqual(nuevos[1] - 2.5, RIPPLE_KEEP, places=3)

    def test_hueco_pequeno_no_se_toca(self):
        nuevos = close_ripple([0.0, 2.3], [2.2, 1.0], [2.0, 3.0])
        self.assertEqual(nuevos[1], 2.3)

    def test_solape_no_se_toca(self):
        nuevos = close_ripple([0.0, 2.0], [2.4, 1.0], [2.2, 3.0])
        self.assertEqual(nuevos[1], 2.0)

    def test_corrimiento_acumulado_tiene_tope(self):
        """Diez segmentos cortos en cadena no pueden desincronizar la voz 4 segundos."""
        starts = [i * 2.0 for i in range(11)]
        durations = [0.5] * 11
        source_ends = [i * 2.0 + 1.8 for i in range(11)]
        nuevos = close_ripple(starts, durations, source_ends)
        for original, nuevo in zip(starts, nuevos):
            self.assertLessEqual(original - nuevo, RIPPLE_SHIFT_MAX + 1e-6)

    def test_el_corrimiento_se_arrastra_al_siguiente_hueco(self):
        """Cerrar un hueco mueve también el resto: el silencio no reaparece al lado."""
        starts = [0.0, 3.0, 6.0]
        durations = [1.0, 1.0, 1.0]
        source_ends = [2.2, 5.2, 7.0]
        nuevos = close_ripple(starts, durations, source_ends)
        self.assertAlmostEqual(nuevos[1], 3.0 - RIPPLE_STEP_MAX, places=3)
        self.assertAlmostEqual(nuevos[2], 6.0 - 0.55, places=3)

    def test_pausa_de_la_fuente_devuelve_parte_del_corrimiento(self):
        """Donde la fuente sí pausaba, parte del corrimiento vuelve: la pausa es real."""
        starts = [0.0, 3.0, 6.0]
        durations = [1.0, 2.6, 1.0]
        source_ends = [2.2, 5.3, 7.0]
        nuevos = close_ripple(starts, durations, source_ends)
        self.assertAlmostEqual(nuevos[1], 3.0 - RIPPLE_STEP_MAX, places=3)
        self.assertAlmostEqual(nuevos[2], 6.0 - (RIPPLE_STEP_MAX - RIPPLE_PAYBACK_MAX), places=3)

    def test_la_pausa_crece_como_mucho_el_pago(self):
        starts = [0.0, 3.0, 6.0, 9.0]
        durations = [1.0] * 4
        source_ends = [2.2, 5.2, 8.2, 10.0]
        nuevos = close_ripple(starts, durations, source_ends)
        for i in (1, 2):
            antes = starts[i + 1] - (starts[i] + durations[i])
            despues = nuevos[i + 1] - (nuevos[i] + durations[i])
            self.assertLessEqual(despues - antes, RIPPLE_PAYBACK_MAX + 1e-6)

    def test_longitudes_incoherentes_fallan(self):
        with self.assertRaises(ValueError):
            close_ripple([0.0, 3.0], [1.0], [2.2, 4.0])


class TestRepartoDeSilencio(unittest.TestCase):
    def test_separa_interno_de_fin_de_frase(self):
        mid, end = gap_split([0.0, 3.0, 7.0], [2.2, 2.2, 1.0], [False, True, False])
        self.assertAlmostEqual(mid, 0.8, places=3)
        self.assertAlmostEqual(end, 1.8, places=3)

    def test_solape_no_cuenta_como_silencio(self):
        self.assertEqual(gap_split([0.0, 1.0], [2.0, 1.0], [False, False]), (0.0, 0.0))

    def test_longitudes_incoherentes_fallan(self):
        with self.assertRaises(ValueError):
            gap_split([0.0, 1.0], [1.0], [False, False])


if __name__ == "__main__":
    unittest.main()
