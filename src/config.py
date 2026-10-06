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

# Detección de entornos (Colab vs Kaggle vs Local)
def is_colab() -> bool:
    if "google.colab" in sys.modules:
        return True
    try:
        import google.colab
        return True
    except Exception:
        return False


def is_kaggle() -> bool:
    return os.path.exists("/kaggle/working") or "KAGGLE_KERNEL_RUN_TYPE" in os.environ


# Rutas base
if is_colab():
    BASE_DIR = Path("/content")
elif is_kaggle():
    BASE_DIR = Path("/kaggle/working")
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


def get_google_api_keys() -> list[str]:
    """Retorna una lista con todas las API Keys de Google/Gemini configuradas."""
    keys: list[str] = []

    # 1. Variables de entorno principales (soporta múltiples separadas por coma o ;)
    for env_var in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEYS"):
        raw = os.getenv(env_var)
        if raw:
            for k in raw.replace(";", ",").split(","):
                k = k.strip()
                if k and k not in keys:
                    keys.append(k)

    # 2. Variables numeradas en entorno: GOOGLE_API_KEY_1, GOOGLE_API_KEY_2, etc.
    for i in range(1, 10):
        for prefix in ("GOOGLE_API_KEY_", "GEMINI_API_KEY_"):
            val = os.getenv(f"{prefix}{i}")
            if val and val.strip() and val.strip() not in keys:
                keys.append(val.strip())

    # 3. Colab userdata secrets
    try:
        from google.colab import userdata

        candidate_names = (
            ["GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEYS"]
            + [f"GOOGLE_API_KEY_{i}" for i in range(1, 10)]
            + [f"GEMINI_API_KEY_{i}" for i in range(1, 10)]
        )
        for name in candidate_names:
            try:
                val = userdata.get(name)
                if val:
                    for k in str(val).replace(";", ",").split(","):
                        k = k.strip()
                        if k and k not in keys:
                            keys.append(k)
            except Exception:
                pass
    except Exception:
        pass

    # 4. Kaggle secrets (UserSecretsClient)
    try:
        from kaggle_secrets import UserSecretsClient
        user_secrets = UserSecretsClient()

        candidate_names = (
            ["GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEYS"]
            + [f"GOOGLE_API_KEY_{i}" for i in range(1, 10)]
            + [f"GEMINI_API_KEY_{i}" for i in range(1, 10)]
        )
        for name in candidate_names:
            try:
                val = user_secrets.get_secret(name)
                if val:
                    for k in str(val).replace(";", ",").split(","):
                        k = k.strip()
                        if k and k not in keys:
                            keys.append(k)
            except Exception:
                pass
    except Exception:
        pass

    return keys


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
    # 1. Variable de entorno (env o cargada previamente)
    env_key = os.getenv("FISH_API_KEY")
    if env_key:
        return env_key

    # 2. Colab Secrets (userdata)
    try:
        from google.colab import userdata
        val = userdata.get("FISH_API_KEY")
        if val:
            os.environ["FISH_API_KEY"] = val
            return val
    except Exception:
        pass

    # 3. Kaggle Secrets (UserSecretsClient)
    try:
        from kaggle_secrets import UserSecretsClient
        val = UserSecretsClient().get_secret("FISH_API_KEY")
        if val:
            os.environ["FISH_API_KEY"] = val
            return val
    except Exception:
        pass

def get_hf_token() -> str | None:
    """Retorna el token de Hugging Face desde env, Colab userdata o Kaggle secrets."""
    # 1. Variables de entorno
    for env_var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        val = os.getenv(env_var)
        if val:
            return val

    # 2. Colab Secrets (userdata)
    try:
        from google.colab import userdata
        for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
            try:
                val = userdata.get(key)
                if val:
                    os.environ["HF_TOKEN"] = str(val)
                    os.environ["HUGGING_FACE_HUB_TOKEN"] = str(val)
                    return str(val)
            except Exception:
                pass
    except Exception:
        pass

    # 3. Kaggle Secrets (UserSecretsClient)
    try:
        from kaggle_secrets import UserSecretsClient
        user_secrets = UserSecretsClient()
        for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
            try:
                val = user_secrets.get_secret(key)
                if val:
                    os.environ["HF_TOKEN"] = str(val)
                    os.environ["HUGGING_FACE_HUB_TOKEN"] = str(val)
                    return str(val)
            except Exception:
                pass
    except Exception:
        pass

    return None


def get_drive_mount() -> bool: return _google_drive and is_colab()

