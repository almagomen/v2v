"""
Módulo de manifiesto de activos V2V.

Cada carpeta de job tiene un `v2v_assets.json` que se actualiza
progresivamente durante el pipeline. El backend lo lee para
saber las rutas exactas sin ninguna búsqueda en disco.

Estructura del manifiesto:
{
    "merged":      "/path/video.mp4",           # video completo (video+audio)
    "video_only":  "/path/video.f137.mp4",      # solo video (sin audio), de yt-dlp
    "audio_only":  "/path/video.f251.webm",     # solo audio original, de yt-dlp
    "vocals":      "/path/vocals.wav",           # voz extraída por RoFormer
    "no_vocals":   "/path/no_vocals.wav",        # instrumental (sin voz)
    "segments": {                                # segmentos TTS generados
        "1": "/path/Seqs_trg/tts_SPEAKER_00_001.wav",
        "2": "/path/Seqs_trg/tts_SPEAKER_00_002.wav"
    }
}
"""

import json
from pathlib import Path
from typing import Any

ASSETS_FILENAME = "v2v_assets.json"


def load_assets(folder: Path) -> dict:
    """Lee el manifiesto de activos de la carpeta del job. Retorna {} si no existe."""
    manifest = folder / ASSETS_FILENAME
    if not manifest.exists():
        return {}
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_assets(folder: Path, assets: dict) -> None:
    """Guarda el manifiesto de activos en la carpeta del job."""
    manifest = folder / ASSETS_FILENAME
    manifest.write_text(json.dumps(assets, indent=2, ensure_ascii=False), encoding="utf-8")


def update_assets(folder: Path, **kwargs: Any) -> dict:
    """
    Actualiza claves individuales del manifiesto de activos.
    Crea el archivo si no existe. Retorna el manifiesto actualizado.
    """
    assets = load_assets(folder)
    for k, v in kwargs.items():
        if v is not None:
            assets[k] = v
    save_assets(folder, assets)
    return assets


def register_segment(folder: Path, seg_index: int, path: Path) -> None:
    """Registra la ruta de un segmento TTS en el manifiesto."""
    assets = load_assets(folder)
    segments = assets.setdefault("segments", {})
    segments[str(seg_index)] = str(path)
    save_assets(folder, assets)


def get_segment(folder: Path, seg_index: int) -> str | None:
    """Obtiene la ruta de un segmento TTS desde el manifiesto."""
    assets = load_assets(folder)
    return assets.get("segments", {}).get(str(seg_index))
