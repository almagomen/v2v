"""
Configuración central: rutas, dispositivo, API keys.
Detecta Colab vs local y carga secretos desde Colab userdata o variables de entorno.
"""
from pathlib import Path
import os
import sys

try:
    import torch
except ImportError:
    torch = None

# Detección Colab
def is_colab() -> bool:
    if "google.colab" in sys.modules:
        return True
    try:
        import google.colab
        return True
    except Exception:
        return False


# Rutas
if is_colab():
    BASE_DIR = Path("/content")
else:
    BASE_DIR = Path(os.getenv("V2V_BASE_DIR", ".")).resolve()


# Google Drive (solo Colab). No montamos aquí: en Colab ejecuta una celda con drive.mount("/content/drive") antes de lanzar el backend.
_google_drive = os.getenv("DRIVE_MOUNT", "true").lower() in ("1", "true", "yes")
google_drive = is_colab() and _google_drive
DRIVE_DIR = Path("/content/drive/MyDrive/v2v") if google_drive else None

# Directorios de trabajo
QUEUE_DIR = BASE_DIR / "Queue"
TEMP_DIR = BASE_DIR / "temp"
JOBS_DIR = QUEUE_DIR / "jobs"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# Dispositivo
DEVICE = "cuda" if (torch is not None and torch.cuda.is_available()) else "cpu"

# API keys: Colab userdata o env
def get_google_api_key() -> str | None:
    env_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if env_key:
        return env_key
    try:
        from google.colab import userdata
        for key_name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
            try:
                val = userdata.get(key_name)
                if val:
                    os.environ["GOOGLE_API_KEY"] = val
                    return val
            except Exception:
                continue
    except Exception:
        pass
    return None


def get_fish_api_key() -> str | None:
    # Priorizar variable de entorno (para cambios dinámicos desde la UI o .env)
    env_key = os.getenv("FISH_API_KEY") or os.getenv("FISH_AUDIO_API_KEY")
    if env_key:
        return env_key

    # Intentar obtener de Colab Secrets (evaluando cada nombre en su propio bloque try/except)
    try:
        from google.colab import userdata
        for secret_name in ("FISH_API_KEY", "FISH_AUDIO_API_KEY"):
            try:
                val = userdata.get(secret_name)
                if val:
                    os.environ["FISH_API_KEY"] = val
                    return val
            except Exception:
                continue
    except Exception:
        pass

    return os.getenv("FISH_API_KEY") or os.getenv("FISH_AUDIO_API_KEY")


def get_drive_mount() -> bool: return _google_drive and is_colab()
