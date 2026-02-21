"""
Configuración central: rutas, dispositivo, API keys.
Detecta Colab vs local y carga secretos desde Colab userdata o variables de entorno.
"""
from pathlib import Path
import os
import sys

import torch

# Detección Colab
def is_colab() -> bool:
    return "google.colab" in sys.modules


# Rutas
if is_colab():
    BASE_DIR = Path("/content")
    DEMUCS_DIR = Path("/content/demucs")
else:
    BASE_DIR = Path(os.getenv("V2V_BASE_DIR", ".")).resolve()
    DEMUCS_DIR = Path(os.getenv("V2V_DEMUCS_DIR", "/content/demucs"))  # Colab path when run there

# Google Drive (solo Colab)
_google_drive = os.getenv("DRIVE_MOUNT", "true").lower() in ("1", "true", "yes")
if is_colab() and _google_drive:
    try:
        from google.colab import drive
        drive.mount("/content/drive")
    except Exception:
        pass
google_drive = is_colab() and _google_drive
DRIVE_DIR = Path("/content/drive/MyDrive/v2v") if google_drive else None

# Directorios de trabajo
QUEUE_DIR = BASE_DIR / "Queue"
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_DIR.mkdir(parents=True, exist_ok=True)

# Dispositivo
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# API keys: Colab userdata o env
def get_google_api_key() -> str | None:
    if is_colab():
        try:
            from google.colab import userdata
            return userdata.get("GOOGLE_API_KEY") or None
        except Exception:
            return os.getenv("GOOGLE_API_KEY")
    return os.getenv("GOOGLE_API_KEY")


def get_lmnt_api_key() -> str | None:
    if is_colab():
        try:
            from google.colab import userdata
            return userdata.get("LMNT_API_KEY") or None
        except Exception:
            return os.getenv("LMNT_API_KEY")
    return os.getenv("LMNT_API_KEY")


def get_drive_mount() -> bool:
    return _google_drive and is_colab()
