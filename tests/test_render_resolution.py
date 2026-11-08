"""Regresión: resolución de medios del render (batch y single).

El frontend importa cada corte de audio original como `vocals_<NNN>.(wav|m4a)` y
envía ese nombre lógico al render. Esos cortes se generan en `Seqs_src/` y no
están registrados en `result.json['assets']`, así que `_resolve_media_path` debe
buscarlos en disco. Sin esto, la exportación por lotes fallaba con
`404: Archivo no encontrado en el manifiesto del job: vocals_001.m4a`.
"""

import json
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from api.routes.render import _resolve_media_path


class TestResolveMediaPath(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

        # Manifiesto mínimo con los activos "globales"
        (self.folder / "video_only.mp4").write_bytes(b"video")
        (self.folder / "vocals.wav").write_bytes(b"vocals")
        (self.folder / "instrumental.m4a").write_bytes(b"inst")
        (self.folder / "result.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "assets": {
                        "video_only": "video_only.mp4",
                        "vocals": "vocals.wav",
                        "no_vocals": "instrumental.m4a",
                    },
                    "segments": [
                        {"seg": 1, "orig_start": 0.0, "orig_end": 1.0},
                        {"seg": 2, "orig_start": 1.0, "orig_end": 2.0},
                    ],
                }
            ),
            encoding="utf-8",
        )

        # Cortes originales (Seqs_src) y sintetizados (Seqs_trg)
        src = self.folder / "Seqs_src"
        src.mkdir()
        (src / "vocals_001.m4a").write_bytes(b"src1")
        (src / "vocals_002.wav").write_bytes(b"src2")

        trg = self.folder / "Seqs_trg"
        trg.mkdir()
        (trg / "tts_mrbeast_003.m4a").write_bytes(b"tts3")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_resuelve_corte_original_m4a(self) -> None:
        """El nombre exacto que envía el frontend debe resolver a Seqs_src."""
        path = _resolve_media_path(self.folder, "vocals_001.m4a")
        self.assertEqual(path.name, "vocals_001.m4a")
        self.assertEqual(path.parent.name, "Seqs_src")

    def test_resuelve_corte_original_wav_con_ruta(self) -> None:
        path = _resolve_media_path(self.folder, "Seqs_src/vocals_002.wav")
        self.assertEqual(path.name, "vocals_002.wav")
        self.assertEqual(path.parent.name, "Seqs_src")

    def test_resuelve_corte_original_sin_extension(self) -> None:
        path = _resolve_media_path(self.folder, "vocals_002")
        self.assertEqual(path.name, "vocals_002.wav")

    def test_prefiere_m4a_sobre_wav(self) -> None:
        (self.folder / "Seqs_src" / "vocals_002.m4a").write_bytes(b"src2-m4a")
        path = _resolve_media_path(self.folder, "vocals_002.m4a")
        self.assertEqual(path.suffix, ".m4a")

    def test_prefiere_el_prefijo_solicitado(self) -> None:
        """Con varios cortes del mismo índice, gana el prefijo del nombre pedido."""
        (self.folder / "Seqs_src" / "speaker_004.m4a").write_bytes(b"other")
        (self.folder / "Seqs_src" / "vocals_004.m4a").write_bytes(b"src4")
        path = _resolve_media_path(self.folder, "vocals_004.m4a")
        self.assertEqual(path.name, "vocals_004.m4a")

    def test_acepta_separador_con_guion(self) -> None:
        (self.folder / "Seqs_src" / "vocals-005.m4a").write_bytes(b"src5")
        path = _resolve_media_path(self.folder, "vocals-005.m4a")
        self.assertEqual(path.name, "vocals-005.m4a")

    def test_no_rompe_segmentos_tts(self) -> None:
        """`tts_*` sigue resolviéndose en Seqs_trg, no en Seqs_src."""
        path = _resolve_media_path(self.folder, "tts_mrbeast_003.m4a")
        self.assertEqual(path.name, "tts_mrbeast_003.m4a")
        self.assertEqual(path.parent.name, "Seqs_trg")

    def test_no_rompe_activos_del_manifiesto(self) -> None:
        self.assertEqual(_resolve_media_path(self.folder, "video.mp4").name, "video_only.mp4")
        self.assertEqual(_resolve_media_path(self.folder, "vocals.wav").name, "vocals.wav")
        self.assertEqual(_resolve_media_path(self.folder, "instrumental.wav").name, "instrumental.m4a")

    def test_error_claro_si_no_existe(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _resolve_media_path(self.folder, "vocals_099.m4a")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("vocals_099.m4a", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
