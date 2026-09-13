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
    if "google.colab" in sys.modules:
        return True
    try:
        import google.colab
        return True
    except ImportError:
        return Path("/content").exists()


# Rutas
if is_colab():
    BASE_DIR = Path("/content")
else:
    BASE_DIR = Path(os.getenv("V2V_BASE_DIR", ".")).resolve()


# Google Drive (solo Colab)
_google_drive = os.getenv("DRIVE_MOUNT", "true").lower() in ("1", "true", "yes")
google_drive = is_colab() and _google_drive
if google_drive:
    # Preferir /content/drive/MyDrive/v2v si existe, de lo contrario /content/drive/MyDrive
    if Path("/content/drive/MyDrive/v2v").exists():
        DRIVE_DIR = Path("/content/drive/MyDrive/v2v")
    elif Path("/content/drive/MyDrive").exists():
        DRIVE_DIR = Path("/content/drive/MyDrive")
    else:
        DRIVE_DIR = Path("/content/drive/MyDrive/v2v")
else:
    DRIVE_DIR = None

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


def get_fish_api_key() -> str | None:
    if is_colab():
        try:
            from google.colab import userdata
            return userdata.get("FISH_API_KEY") or None
        except Exception: return os.getenv("FISH_API_KEY")
    return os.getenv("FISH_API_KEY")

def get_drive_mount() -> bool: return _google_drive and is_colab()
