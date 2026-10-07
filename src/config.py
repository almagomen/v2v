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

def is_kaggle() -> bool:
    return os.path.exists("/kaggle/working") or "KAGGLE_KERNEL_RUN_TYPE" in os.environ


def is_colab() -> bool:
    if is_kaggle():
        return False
    if "google.colab" in sys.modules:
        return True
    try:
        import google.colab
        return True
    except Exception:
        return False


# Rutas base
if is_kaggle():
    BASE_DIR = Path("/kaggle/working")
elif is_colab():
    BASE_DIR = Path("/content")
else:
    BASE_DIR = Path(os.getenv("V2V_BASE_DIR", ".")).resolve()

# Directorio de datasets montados en Kaggle (si aplica)
KAGGLE_INPUT_DIR = Path("/kaggle/input") if is_kaggle() else None


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

# Dispositivo y soporte Multi-GPU (ej. 2x T4 en Kaggle)
GPU_COUNT = torch.cuda.device_count() if (torch is not None and torch.cuda.is_available()) else 0
DEVICE = os.getenv("V2V_DEVICE", "cuda:0" if GPU_COUNT > 0 else "cpu")
# Segunda GPU para balanceo si existen >= 2 GPUs (ej. RoFormer o Render en cuda:1)
DEVICE_SECONDARY = os.getenv("V2V_DEVICE_SECONDARY", "cuda:1" if GPU_COUNT > 1 else DEVICE)

# API keys: Colab userdata / Kaggle UserSecretsClient / env (soporta rotación de múltiples keys)
_current_google_key_idx = 0
_cached_google_keys: list[str] | None = None


def get_google_api_keys() -> list[str]:
    """Retorna una lista con todas las API Keys de Google configuradas (con caché en memoria).
    Lee directamente de os.environ['GOOGLE_API_KEY'] (soporta una o varias separadas por coma).
    """
    global _cached_google_keys
    if _cached_google_keys is not None and len(_cached_google_keys) > 0:
        return _cached_google_keys

    keys: list[str] = []

    # 1. Variable de entorno principal (soporta una o varias separadas por coma o ;)
    raw = os.getenv("GOOGLE_API_KEY")
    if raw:
        for k in raw.replace(";", ",").split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)

    # 2. Colab userdata secrets (solo si no se encontró en env)
    if not keys:
        try:
            from google.colab import userdata
            val = userdata.get("GOOGLE_API_KEY")
            if val:
                for k in str(val).replace(";", ",").split(","):
                    k = k.strip()
                    if k and k not in keys:
                        keys.append(k)
        except Exception:
            pass

    _cached_google_keys = keys
    return _cached_google_keys


def get_raw_google_api_keys() -> str:
    """Retorna el string crudo de GOOGLE_API_KEY tal como fue configurado (ideal para inputs del frontend)."""
    raw = os.getenv("GOOGLE_API_KEY")
    if raw and raw.strip():
        return raw.strip()
    keys = get_google_api_keys()
    return ", ".join(keys) if keys else ""


def set_google_api_keys(keys_str: str | None) -> None:
    """Actualiza la clave o lista de claves en os.environ e invalida la caché interna."""
    global _cached_google_keys, _current_google_key_idx
    val = (keys_str or "").strip()
    if val:
        os.environ["GOOGLE_API_KEY"] = val
    else:
        os.environ.pop("GOOGLE_API_KEY", None)
    _cached_google_keys = None
    _current_google_key_idx = 0


def get_google_api_key() -> str | None:
    """Retorna la API Key actual o la primera configurada."""
    global _current_google_key_idx
    keys = get_google_api_keys()
    if not keys:
        return None
    idx = _current_google_key_idx % len(keys)
    return keys[idx]


def rotate_google_api_key() -> str | None:
    """Rota a la siguiente API Key disponible y la retorna."""
    global _current_google_key_idx
    keys = get_google_api_keys()
    if not keys:
        return None
    _current_google_key_idx = (_current_google_key_idx + 1) % len(keys)
    next_key = keys[_current_google_key_idx]
    # Sincronizar en entorno para llamadas directas
    os.environ["GOOGLE_API_KEY"] = next_key
    print(f"🔄 [API Rotation] Rotando a Google API Key #{_current_google_key_idx + 1} de {len(keys)} (terminada en ...{next_key[-6:] if len(next_key) >= 6 else '***'})")
    return next_key


def get_fish_api_key() -> str | None:
    """Retorna la API Key de Fish Audio desde variables de entorno o Colab."""
    # 1. Variable de entorno (env o cargada previamente en la celda inicial)
    env_key = os.getenv("FISH_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    # 2. Colab Secrets (userdata)
    try:
        from google.colab import userdata
        val = userdata.get("FISH_API_KEY")
        if val and str(val).strip():
            os.environ["FISH_API_KEY"] = str(val).strip()
            return str(val).strip()
    except Exception:
        pass

    return None


def set_fish_api_key(key_str: str | None) -> None:
    """Actualiza la API Key de Fish Audio en os.environ."""
    val = (key_str or "").strip()
    if val:
        os.environ["FISH_API_KEY"] = val
    else:
        os.environ.pop("FISH_API_KEY", None)


def get_hf_token() -> str | None:
    """Retorna el token de Hugging Face desde env o Colab userdata."""
    # 1. Variable de entorno (cargada al inicio de Kaggle o Colab)
    val = os.getenv("HF_TOKEN")
    if val and val.strip():
        return val.strip()

    # 2. Colab Secrets (userdata)
    try:
        from google.colab import userdata
        val = userdata.get("HF_TOKEN")
        if val and str(val).strip():
            os.environ["HF_TOKEN"] = str(val).strip()
            return str(val).strip()
    except Exception:
        pass

    return None


def get_drive_mount() -> bool: return _google_drive and is_colab()

