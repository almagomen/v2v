"""Resolución de alias ``*-latest`` de Gemini sin red.

La API de Interactions rechaza algunos alias que sí existen en el playground
(``gemini-flash-lite-latest`` → 404). En vez de fijar una versión concreta, el
cliente resuelve el alias al modelo más reciente de la misma familia. Estas
pruebas cubren esa resolución y el reintento único.

El módulo probado no importa ``google-genai``, así que corre en el entorno local.
"""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from src import gemini_models


class _FakeModels:
    def __init__(self, items: list[SimpleNamespace]):
        self.items = items
        self.calls = 0

    def list(self):
        self.calls += 1
        return list(self.items)


class _FakeInteractions:
    def __init__(self, missing: tuple[str, ...] = ()):
        self.missing = set(missing)
        self.created: list[dict] = []

    def create(self, **kwargs):
        self.created.append(dict(kwargs))
        model = str(kwargs.get("model"))
        if model in self.missing:
            raise RuntimeError(
                f"Error code: 404 - {{'error': {{'message': \"Model '{model}' not found\"}}}}"
            )
        return SimpleNamespace(output_text="ok")


class _FakeClient:
    def __init__(self, models: list[SimpleNamespace], missing: tuple[str, ...] = ()):
        self.models = _FakeModels(models)
        self.interactions = _FakeInteractions(missing)


def _model(name: str, create_time: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, create_time=create_time)


class TestAliasFamily(unittest.TestCase):
    def test_alias_latest_se_descompone_en_familia(self):
        self.assertEqual(
            gemini_models.model_alias_family("gemini-flash-lite-latest"),
            ("gemini", "flash-lite"),
        )

    def test_version_concreta_no_es_alias(self):
        self.assertIsNone(gemini_models.model_alias_family("gemini-3.5-flash-lite"))

    def test_404_se_reconoce_en_varios_formatos(self):
        for message in (
            "Error code: 404 - not found",
            "model not_found",
            "NOT FOUND: model",
        ):
            self.assertTrue(gemini_models.is_model_not_found(RuntimeError(message)))

    def test_429_no_se_confunde_con_404(self):
        self.assertFalse(
            gemini_models.is_model_not_found(RuntimeError("Error code: 429 - rate limit"))
        )


class TestResolveLatestAlias(unittest.TestCase):
    def setUp(self):
        gemini_models._MODEL_ALIAS_CACHE.clear()

    def test_elige_el_modelo_concreto_mas_reciente_de_la_familia(self):
        client = _FakeClient(
            [
                _model("models/gemini-3.4-flash-lite", "2025-01-01T00:00:00Z"),
                _model("models/gemini-3.5-flash-lite", "2025-06-01T00:00:00Z"),
                _model("models/gemini-flash-lite-latest", "2025-07-01T00:00:00Z"),
                _model("models/gemini-3.5-flash", "2025-08-01T00:00:00Z"),
                _model("models/gemini-3.5-flash-lite-preview", "2025-09-01T00:00:00Z"),
                _model("models/gemma-4-26b-a4b-it", "2025-09-01T00:00:00Z"),
            ]
        )

        resolved = gemini_models.resolve_latest_alias(client, "gemini-flash-lite-latest")

        self.assertEqual(resolved, "gemini-3.5-flash-lite")
        self.assertEqual(client.models.calls, 1)

    def test_flash_no_captura_flash_lite(self):
        """``flash`` y ``flash-lite`` son modelos distintos: el alias no debe cruzarlos."""
        client = _FakeClient(
            [
                _model("gemini-3.5-flash", "2025-06-01T00:00:00Z"),
                _model("gemini-3.6-flash-lite", "2025-09-01T00:00:00Z"),
            ]
        )

        resolved = gemini_models.resolve_latest_alias(client, "gemini-flash-latest")

        self.assertEqual(resolved, "gemini-3.5-flash")

    def test_sufijo_de_version_numerico_no_cambia_la_familia(self):
        client = _FakeClient(
            [
                _model("gemini-3.5-flash-lite-001", "2025-06-01T00:00:00Z"),
                _model("gemini-3.4-flash-lite", "2025-01-01T00:00:00Z"),
            ]
        )

        resolved = gemini_models.resolve_latest_alias(client, "gemini-flash-lite-latest")

        self.assertEqual(resolved, "gemini-3.5-flash-lite-001")

    def test_cachea_la_resolucion(self):
        client = _FakeClient([_model("gemini-3.5-flash-lite", "2025-06-01T00:00:00Z")])

        first = gemini_models.resolve_latest_alias(client, "gemini-flash-lite-latest")
        second = gemini_models.resolve_latest_alias(client, "gemini-flash-lite-latest")

        self.assertEqual(first, second)
        self.assertEqual(client.models.calls, 1)

    def test_sin_candidatos_devuelve_none(self):
        client = _FakeClient([_model("gemini-flash-lite-latest", "2025-07-01T00:00:00Z")])

        self.assertIsNone(
            gemini_models.resolve_latest_alias(client, "gemini-flash-lite-latest")
        )

    def test_fallo_al_listar_modelos_no_rompe_la_llamada(self):
        client = _FakeClient([])

        def _boom():
            raise RuntimeError("network down")

        client.models.list = _boom  # type: ignore[assignment]

        self.assertIsNone(
            gemini_models.resolve_latest_alias(client, "gemini-flash-lite-latest")
        )


class TestCreateInteraction(unittest.TestCase):
    def setUp(self):
        gemini_models._MODEL_ALIAS_CACHE.clear()

    def test_alias_404_se_reintenta_una_vez_con_el_concreto(self):
        client = _FakeClient(
            [_model("gemini-3.5-flash-lite", "2025-06-01T00:00:00Z")],
            missing=("gemini-flash-lite-latest",),
        )

        with redirect_stdout(io.StringIO()) as log:
            result = gemini_models.create_interaction(
                client, {"model": "gemini-flash-lite-latest", "input": "hola"}
            )

        self.assertEqual(result.output_text, "ok")
        self.assertIn("gemini-3.5-flash-lite", log.getvalue())
        self.assertEqual(len(client.interactions.created), 2)
        self.assertEqual(client.interactions.created[0]["model"], "gemini-flash-lite-latest")
        self.assertEqual(client.interactions.created[1]["model"], "gemini-3.5-flash-lite")

    def test_error_distinto_de_404_no_reintenta(self):
        client = _FakeClient(
            [_model("gemini-3.5-flash-lite", "2025-06-01T00:00:00Z")],
            missing=(),
        )

        def _rate_limited(**kwargs):
            client.interactions.created.append(dict(kwargs))
            raise RuntimeError("Error code: 429 - rate limit")

        client.interactions.create = _rate_limited  # type: ignore[assignment]

        with self.assertRaises(RuntimeError):
            gemini_models.create_interaction(
                client, {"model": "gemini-flash-lite-latest", "input": "hola"}
            )

        self.assertEqual(len(client.interactions.created), 1)
        self.assertEqual(client.models.calls, 0)

    def test_sin_resolucion_posible_propaga_el_404(self):
        client = _FakeClient([], missing=("gemini-flash-lite-latest",))

        with self.assertRaises(RuntimeError):
            gemini_models.create_interaction(
                client, {"model": "gemini-flash-lite-latest", "input": "hola"}
            )


if __name__ == "__main__":
    unittest.main()
