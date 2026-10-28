"""
Integración de `translate_text_list` con el entity lock: placeholders, rescate y
estado por segmento. Sin red: el cliente de Google se sustituye por un doble.

Ejecutar desde la raíz del repo:
    python -m unittest tests.test_translation_entities -v
"""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from src.translation import translate_text_list
    _HAS_GENAI = True
except ImportError:  # google-genai vive en Colab, no en el entorno local
    translate_text_list = None
    _HAS_GENAI = False


class _FakeInteractions:
    """
    Devuelve las respuestas preparadas en orden y registra las llamadas.

    Los juicios (`palabras`, `fugas`) se responden aparte y no consumen la cola:
    así las aserciones de número de llamadas de traducción siguen midiendo lo suyo.
    """

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls = 0
        self.judge_calls = 0
        self.prompts: list[str] = []
        self.judge_words: list[str] = []
        self.judge_leaks: list[str] = []

    def create(self, **kwargs):
        prompt = str(kwargs.get("input", ""))
        self.prompts.append(prompt)
        if '"palabras"' in prompt:
            self.judge_calls += 1
            return SimpleNamespace(output_text=json.dumps({"palabras": self.judge_words}))
        if '"fugas"' in prompt:
            self.judge_calls += 1
            return SimpleNamespace(output_text=json.dumps({"fugas": self.judge_leaks}))
        text = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return SimpleNamespace(output_text=text)

    @property
    def translation_prompts(self) -> list[str]:
        """Prompts de traducción, sin los juicios de idioma."""
        return [p for p in self.prompts if '"palabras"' not in p and '"fugas"' not in p]


class _FakeClient:
    instances: list["_FakeClient"] = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.interactions = _FakeInteractions([])
        _FakeClient.instances.append(self)


def _run(
    responses: list[str],
    sentences: list[str],
    judge_leaks: list[str] | None = None,
    judge_words: list[str] | None = None,
) -> tuple[list[str], list[dict], _FakeClient]:
    _FakeClient.instances.clear()
    fake = _FakeClient("k")
    fake.interactions.responses = responses
    fake.interactions.judge_leaks = list(judge_leaks or [])
    fake.interactions.judge_words = list(judge_words or [])
    meta = [{"seg": i + 1} for i in range(len(sentences))]
    with patch("src.translation.get_google_api_keys", return_value=["test-key"]), \
         patch("src.translation.genai.Client", lambda api_key: fake):
        result = translate_text_list(
            sentences,
            target_lang="es",
            source_lang="pt",
            segments_meta=meta,
            return_details=True,
        )
    texts, _phonemes = result
    return texts, meta, fake


@unittest.skipUnless(_HAS_GENAI, "google-genai no instalado en este entorno")
class TestEntityPipeline(unittest.TestCase):
    def test_restaura_entidades_y_no_marca_fallo(self):
        sentences = ["Instala o Ghidra 12.1 agora.", "Depois usa o REA."]
        good = {"1": {"text": "Instala el ⟦E1⟧ ⟦E2⟧ ahora."}, "2": {"text": "Luego usa el ⟦E1⟧."}}
        texts, meta, fake = _run([json.dumps(good)], sentences)

        self.assertEqual(texts[0], "Instala el Ghidra 12.1 ahora.")
        self.assertEqual(texts[1], "Luego usa el REA.")
        self.assertEqual(fake.interactions.calls, 1)
        self.assertNotIn("translation_status", meta[0])
        self.assertNotIn("⟦", texts[0])

    def test_rescate_recupera_token_perdido(self):
        sentences = ["Instala o Ghidra 12.1 agora."]
        bad = {"1": {"text": "Instala el Ghidra ahora."}}
        fixed = {"1": {"text": "Instala el ⟦E1⟧ ⟦E2⟧ ahora."}}
        texts, meta, fake = _run([json.dumps(bad), json.dumps(fixed)], sentences)

        self.assertEqual(fake.interactions.calls, 2)
        self.assertEqual(texts[0], "Instala el Ghidra 12.1 ahora.")
        self.assertNotIn("translation_status", meta[0])

    def test_fallo_persistente_marca_entity_fail(self):
        sentences = ["Instala o Ghidra 12.1 agora."]
        bad = {"1": {"text": "Instala la versión 2.1 ahora."}}
        texts, meta, fake = _run([json.dumps(bad), json.dumps(bad)], sentences)

        self.assertEqual(fake.interactions.calls, 2)
        self.assertEqual(meta[0]["translation_status"], "entity_fail")
        self.assertTrue(meta[0]["entity_fail"])
        self.assertEqual(texts[0], "Instala la versión 2.1 ahora.")

    def test_clave_ausente_marca_fallback_y_sin_rescate(self):
        sentences = ["Instala o Ghidra 12.1 agora.", "Depois usa o REA."]
        partial = {"1": {"text": "Instala el ⟦E1⟧ ⟦E2⟧ ahora."}}
        texts, meta, fake = _run([json.dumps(partial)], sentences)

        self.assertEqual(meta[0].get("translation_status"), None)
        self.assertEqual(meta[1]["translation_status"], "fallback")
        self.assertEqual(texts[1], "Depois usa o REA.")
        self.assertEqual(fake.interactions.calls, 1)

    def test_prompt_incluye_regla_de_tokens(self):
        sentences = ["Instala o Ghidra 12.1 agora."]
        good = {"1": {"text": "Instala el ⟦E1⟧ ⟦E2⟧ ahora."}}
        _texts, _meta, fake = _run([json.dumps(good)], sentences)
        self.assertIn("TOKENS PROTEGIDOS", fake.interactions.translation_prompts[0])
        self.assertIn("⟦E1⟧", fake.interactions.translation_prompts[0])

    def test_prompt_avisa_de_las_mayusculas_del_asr(self):
        """Whisper capitaliza tras cada pausa; el modelo no debe leerlo como nombre propio."""
        sentences = ["Instala o Ghidra 12.1 agora."]
        good = {"1": {"text": "Instala el ⟦E1⟧ ⟦E2⟧ ahora."}}
        _texts, _meta, fake = _run([json.dumps(good)], sentences)
        self.assertIn("MAYÚSCULAS DEL RECONOCIMIENTO DE VOZ", fake.interactions.translation_prompts[0])

    def test_residuo_de_idioma_dispara_reescritura(self):
        """Portugués dentro del español es el fallo más audible: se detecta y se corrige."""
        sentences = ["Ela não funciona Mais em outro lugar"]
        malo = {"1": {"text": "No funciona Mais en otro lugar"}}
        bueno = {"1": {"text": "No funciona más en ningún otro lado"}}
        texts, meta, fake = _run(
            [json.dumps(malo), json.dumps(bueno)],
            sentences,
            judge_leaks=["Mais"],
            judge_words=["Mais"],
        )

        self.assertEqual(fake.interactions.calls, 2)
        self.assertEqual(fake.interactions.judge_calls, 2)
        self.assertEqual(texts[0], "No funciona más en ningún otro lado")
        self.assertIn("residuo", fake.interactions.translation_prompts[1])
        self.assertNotIn("translation_status", meta[0])
        self.assertNotIn("untranslated", meta[0])

    def test_juicio_sin_fugas_no_reescribe(self):
        """El juicio es la única fuente de fugas: si no confirma ninguna, no se toca el texto."""
        sentences = ["Ela não funciona Mais em outro lugar"]
        malo = {"1": {"text": "No funciona Mais en otro lugar"}}
        texts, _meta, fake = _run(
            [json.dumps(malo)], sentences, judge_leaks=[], judge_words=["Mais"]
        )

        self.assertEqual(fake.interactions.calls, 1)
        self.assertEqual(texts[0], "No funciona Mais en otro lugar")

    def test_rescate_de_residuo_que_no_limpia_se_descarta(self):
        sentences = ["Ela não funciona Mais em outro lugar"]
        malo = {"1": {"text": "No funciona Mais en otro lugar"}}
        texts, meta, fake = _run(
            [json.dumps(malo), json.dumps(malo)],
            sentences,
            judge_leaks=["Mais"],
            judge_words=["Mais"],
        )

        self.assertEqual(fake.interactions.calls, 2)
        self.assertEqual(texts[0], "No funciona Mais en otro lugar")
        self.assertEqual(meta[0]["untranslated"], ["mais"])

    def test_sin_entidades_no_inyecta_regla_de_tokens(self):
        sentences = ["Hoje o dia está bonito."]
        good = {"1": {"text": "Hoy el día está bonito."}}
        _texts, _meta, fake = _run([json.dumps(good)], sentences)
        self.assertNotIn("TOKENS PROTEGIDOS", fake.interactions.translation_prompts[0])


@unittest.skipUnless(_HAS_GENAI, "google-genai no instalado en este entorno")
class TestChunking(unittest.TestCase):
    def _sentences(self, n: int) -> list[str]:
        return [f"Frase numero {i + 1} com o Ghidra 2.1 aberto." for i in range(n)]

    def _payload(self, count: int, start: int = 0) -> str:
        return json.dumps({
            str(i + 1): {"text": f"Frase {start + i + 1} con el ⟦E1⟧ ⟦E2⟧ abierto."}
            for i in range(count)
        })

    def test_parte_en_bloques_y_conserva_orden(self):
        sentences = self._sentences(10)
        with patch.dict("os.environ", {"TRANSLATION_CHUNK_SEGMENTS": "4"}):
            texts, meta, fake = _run(
                [self._payload(4), self._payload(4, 4), self._payload(2, 8)], sentences
            )
        self.assertEqual(fake.interactions.calls, 3)
        for i in range(4):
            self.assertEqual(texts[i], f"Frase {i + 1} con el Ghidra 2.1 abierto.")
        self.assertEqual(texts[9], "Frase 10 con el Ghidra 2.1 abierto.")
        self.assertNotIn("translation_status", meta[9])

    def test_bloque_invalido_se_reintenta_partido(self):
        sentences = self._sentences(8)
        with patch.dict("os.environ", {"TRANSLATION_CHUNK_SEGMENTS": "8"}):
            texts, meta, fake = _run(
                ["respuesta basura", self._payload(4), self._payload(4, 4)], sentences
            )
        self.assertEqual(fake.interactions.calls, 3)
        self.assertEqual(texts[0], "Frase 1 con el Ghidra 2.1 abierto.")
        self.assertEqual(texts[7], "Frase 8 con el Ghidra 2.1 abierto.")
        self.assertNotIn("translation_status", meta[7])

    def test_bloque_incluye_contexto_previo(self):
        sentences = self._sentences(6)
        with patch.dict("os.environ", {"TRANSLATION_CHUNK_SEGMENTS": "3"}):
            _texts, _meta, fake = _run([self._payload(3), self._payload(3, 3)], sentences)
        self.assertIn("Contexto previo", fake.interactions.translation_prompts[1])


@unittest.skipUnless(_HAS_GENAI, "google-genai no instalado en este entorno")
class TestFitBudget(unittest.TestCase):
    """Encaje temporal: el presupuesto entra en el prompt y la pasada de ajuste se acota."""

    SLOT = 10.0  # 10 s de habla en es -> 150-176 chars

    def _run_timed(self, responses: list[str], sentences: list[str], slot: float = SLOT):
        _FakeClient.instances.clear()
        fake = _FakeClient("k")
        fake.interactions.responses = responses
        times = [(0.0, slot + i * 0.0) for i in range(len(sentences))]
        meta = [{"seg": i + 1} for i in range(len(sentences))]
        with patch("src.translation.get_google_api_keys", return_value=["test-key"]), \
             patch("src.translation.genai.Client", lambda api_key: fake):
            result = translate_text_list(
                sentences,
                target_lang="es",
                source_lang="pt",
                times=times,
                segments_meta=meta,
                return_details=True,
            )
        texts, _phonemes = result
        return texts, meta, fake

    def test_prompt_lleva_el_rango_calibrado(self):
        from src.pacing import budget_for

        b = budget_for("es", self.SLOT)
        sentences = ["Hoje o dia está bonito."]
        good = {"1": {"text": "a" * 160}}
        _texts, _meta, fake = self._run_timed([json.dumps(good)], sentences)
        prompt = fake.interactions.translation_prompts[0]
        self.assertIn(f"~{b['chars_min']}-{b['chars_max']} chars", prompt)
        self.assertIn(f"~{b['syl_min']}-{b['syl_max']} sílabas", prompt)
        self.assertIn("16 caracteres por segundo", prompt)
        # El ejemplo de salida no repite la última clave (bloque de 1 segmento).
        self.assertEqual(prompt.count('"1": {'), 1)

    def test_texto_corto_dispara_ajuste_y_se_acepta_el_mejor(self):
        """Caso de aire muerto: 16 chars en 10 s. El ajuste debe alargarlo."""
        sentences = ["Hoje o dia está bonito."]
        corto = {"1": {"text": "Ahora vamos allá"}}
        ajustado = {"1": {"text": "Ahora vamos a ver cómo funciona esto en la práctica"}}
        texts, meta, fake = self._run_timed([json.dumps(corto), json.dumps(ajustado)], sentences)

        self.assertEqual(fake.interactions.calls, 2)
        self.assertEqual(texts[0], ajustado["1"]["text"])
        self.assertIn("ajustador de duración", fake.interactions.translation_prompts[1])

    def test_texto_encajado_no_gasta_una_llamada_extra(self):
        sentences = ["Hoje o dia está bonito."]
        justo = {"1": {"text": "a" * 160}}
        _texts, _meta, fake = self._run_timed([json.dumps(justo)], sentences)
        self.assertEqual(fake.interactions.calls, 1)

    def test_ajuste_que_rompe_entidad_se_descarta(self):
        sentences = ["Instala o Ghidra 12.1 agora no servidor."]
        corto = {"1": {"text": "Instala ⟦E1⟧ ⟦E2⟧ ya"}}
        roto = {"1": {"text": "Instala la herramienta ya en el servidor de pruebas ahora"}}
        texts, _meta, fake = self._run_timed([json.dumps(corto), json.dumps(roto)], sentences)

        self.assertEqual(fake.interactions.calls, 2)
        self.assertEqual(texts[0], "Instala Ghidra 12.1 ya")
        self.assertNotIn("herramienta", texts[0])

    def test_ajuste_peor_que_el_original_se_descarta(self):
        sentences = ["Hoje o dia está bonito."]
        corto = {"1": {"text": "Ahora vamos allá"}}
        peor = {"1": {"text": "Sí"}}
        texts, _meta, _fake = self._run_timed([json.dumps(corto), json.dumps(peor)], sentences)
        self.assertEqual(texts[0], "Ahora vamos allá")

    def test_flag_de_entorno_apaga_la_pasada(self):
        sentences = ["Hoje o dia está bonito."]
        corto = {"1": {"text": "Ahora vamos allá"}}
        with patch.dict("os.environ", {"TRANSLATION_FIT_BUDGET": "0"}):
            _texts, _meta, fake = self._run_timed([json.dumps(corto)], sentences)
        self.assertEqual(fake.interactions.calls, 1)

    def test_sin_tiempos_no_hay_presupuesto_ni_ajuste(self):
        sentences = ["Hoje o dia está bonito."]
        corto = {"1": {"text": "Ahora vamos allá"}}
        _texts, _meta, fake = _run([json.dumps(corto)], sentences)
        self.assertEqual(fake.interactions.calls, 1)
        self.assertNotIn("slot |", fake.interactions.translation_prompts[0])


if __name__ == "__main__":
    unittest.main()
