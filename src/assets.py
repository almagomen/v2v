"""
Gestión de activos (assets) de Video2Video centralizada exclusivamente en result.json.
Almacena referencias relativas a la carpeta del proyecto para máxima portabilidad.
Los segmentos de audio TTS se resuelven dinámicamente desde Seqs_trg/.
"""

from pathlib import Path
from typing import Any
from src.result_store import load_result, save_result


def _to_relative_asset_path(folder: Path, val: Any) -> Any:
    """Convierte rutas absolutas que residan dentro de folder en nombres o rutas relativas."""
    if not isinstance(val, (str, Path)):
        return val
    p = Path(val)
    try:
        f_res = folder.resolve()
        p_res = p.resolve()
        if f_res in p_res.parents:
            return p_res.relative_to(f_res).as_posix()
    except Exception:
        pass
    return p.name if p.is_absolute() else str(val)


def load_assets(folder: Path) -> dict:
    """Lee el diccionario 'assets' directamente desde result.json."""
    data = load_result(folder)
    if isinstance(data, dict):
        assets = data.get("assets") or {}
        # Filtrar campos redundantes si existieran
        assets.pop("segments", None)
        assets.pop("output_name", None)
        assets.pop("viral_title", None)
        return assets
    return {}


def save_assets(folder: Path, assets: dict) -> None:
    """Guarda o actualiza la sección 'assets' limpiamente dentro de result.json."""
    data = load_result(folder) or {"version": 2}
    clean_assets = {}
    for k, v in assets.items():
        if k in ("segments", "output_name", "viral_title") or v is None:
            continue
        clean_assets[k] = _to_relative_asset_path(folder, v)
    data["assets"] = clean_assets
    save_result(folder, data)


def update_assets(folder: Path, **kwargs: Any) -> dict:
    """Actualiza campos específicos dentro de result.json['assets']."""
    assets = load_assets(folder)
    for k, v in kwargs.items():
        if k not in ("segments", "output_name", "viral_title") and v is not None:
            assets[k] = _to_relative_asset_path(folder, v)
    save_assets(folder, assets)
    return assets


def get_segment(folder: Path, seg_index: int) -> Path | None:
    """
    Localiza dinámicamente el archivo WAV del segmento en Seqs_trg sin depender de diccionarios en JSON.
    Prioriza el estándar actual: tts_{speaker}_{seg_index:03d}.wav con fallback a vocals_{seg_index:03d}.wav.
    """
    seqs_dir = folder / "Seqs_trg"
    if not seqs_dir.is_dir():
        return None

    # Formato estándar: tts_{speaker}_{seg_index:03d}.wav
    for cand in seqs_dir.glob(f"tts_*_{seg_index:03d}.wav"):
        if cand.is_file():
            return cand

    return None


def register_segment(folder: Path, seg_index: int, path: Path) -> None:
    """No-op: los segmentos de audio se resuelven dinámicamente desde el sistema de archivos (Seqs_trg/)."""
    pass
