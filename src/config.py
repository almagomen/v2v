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
        import importlib.util
        return importlib.util.find_spec("google.colab") is not None
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

# Motor de transcripción elegido por el usuario. No hay fallback silencioso entre
# motores: cada job usa exactamente el que esté configurado.
STT_ENGINES = ("stable", "crisper")
DEFAULT_STT_ENGINE = "stable"


def get_stt_engine() -> str:
    """Retorna el motor STT configurado ('stable' o 'crisper')."""
    value = (os.getenv("V2V_STT_ENGINE") or DEFAULT_STT_ENGINE).strip().lower()
    return value if value in STT_ENGINES else DEFAULT_STT_ENGINE


def set_stt_engine(engine: str | None) -> str:
    """Actualiza el motor STT en caliente y valida el valor recibido."""
    value = (engine or "").strip().lower()
    if value not in STT_ENGINES:
        raise ValueError(
            f"Motor STT inválido: {engine!r}. Valores permitidos: {', '.join(STT_ENGINES)}"
        )
    os.environ["V2V_STT_ENGINE"] = value
    return value


# Etiquetado automático de emociones con Fish Audio (`/enhance/text`).
# Es opcional y nunca sustituye al motor TTS: solo añade/ajusta etiquetas.
FISH_ENHANCE_VERSIONS = ("s2.1-pro", "drama-3")
DEFAULT_FISH_ENHANCE_VERSION = "s2.1-pro"


def get_fish_auto_emotions() -> bool:
    """Indica si el etiquetado automático de emociones está activado (por defecto sí)."""
    raw = (os.getenv("V2V_FISH_AUTO_EMOTIONS") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def set_fish_auto_emotions(enabled: bool | None) -> bool:
    """Activa/desactiva el etiquetado automático en caliente."""
    value = bool(enabled)
    os.environ["V2V_FISH_AUTO_EMOTIONS"] = "1" if value else "0"
    return value


def get_fish_enhance_version() -> str:
    """Versión de modelo usada por `/enhance/text`."""
    value = (
        os.getenv("V2V_FISH_ENHANCE_VERSION") or DEFAULT_FISH_ENHANCE_VERSION
    ).strip().lower()
    return value if value in FISH_ENHANCE_VERSIONS else DEFAULT_FISH_ENHANCE_VERSION


def set_fish_enhance_version(version: str | None) -> str:
    """Actualiza la versión de `/enhance/text` y valida el valor recibido."""
    value = (version or "").strip().lower()
    if value not in FISH_ENHANCE_VERSIONS:
        raise ValueError(
            "Versión de auto-emociones inválida: "
            f"{version!r}. Valores permitidos: {', '.join(FISH_ENHANCE_VERSIONS)}"
        )
    os.environ["V2V_FISH_ENHANCE_VERSION"] = value
    return value


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


def _get_platform_secret(name: str) -> str | None:
    """Lee un secreto de Colab userdata o Kaggle Secrets, en ese orden."""
    try:
        from google.colab import userdata

        val = userdata.get(name)
        if val and str(val).strip():
            return str(val).strip()
    except Exception:
        pass

    try:
        from kaggle_secrets import UserSecretsClient

        val = UserSecretsClient().get_secret(name)
        if val and str(val).strip():
            return str(val).strip()
    except Exception:
        pass

    return None


def get_fish_api_key() -> str | None:
    """Retorna la API Key de Fish Audio desde variables de entorno, Colab o Kaggle."""
    # 1. Variable de entorno (env o cargada previamente en la celda inicial)
    env_key = os.getenv("FISH_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    # 2. Secretos de la plataforma (Colab userdata / Kaggle Secrets)
    val = _get_platform_secret("FISH_API_KEY")
    if val:
        os.environ["FISH_API_KEY"] = val
    return val


def get_fish_enhance_token() -> str | None:
    """Token de sesión web de Fish para ``/enhance/text``.

    Es independiente de ``FISH_API_KEY``: la API key pública no autentica el
    endpoint interno del Studio. Se lee del entorno o de los secretos de
    Colab/Kaggle (``FISH_ENHANCE_TOKEN``).
    """
    env_token = os.getenv("FISH_ENHANCE_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()

    val = _get_platform_secret("FISH_ENHANCE_TOKEN")
    if val:
        os.environ["FISH_ENHANCE_TOKEN"] = val
    return val


def set_fish_enhance_token(token_str: str | None) -> None:
    """Actualiza el token de ``/enhance/text`` y reactiva el endpoint."""
    val = (token_str or "").strip()
    if val:
        os.environ["FISH_ENHANCE_TOKEN"] = val
    else:
        os.environ.pop("FISH_ENHANCE_TOKEN", None)
    try:
        from src import fish_enhance

        fish_enhance.reset_disable_state()
    except Exception:
        pass


def set_fish_api_key(key_str: str | None) -> None:
    """Actualiza la API Key de Fish Audio en os.environ."""
    val = (key_str or "").strip()
    if val:
        os.environ["FISH_API_KEY"] = val
    else:
        os.environ.pop("FISH_API_KEY", None)
    # Si /enhance/text se había desactivado por un 401, una clave nueva merece
    # otro intento sin reiniciar el backend.
    try:
        from src import fish_enhance

        fish_enhance.reset_disable_state()
    except Exception:
        pass


# Alias habituales del token de Hugging Face. Se acepta cualquiera para que el
# notebook funcione aunque el secreto se haya creado con otro nombre.
HF_TOKEN_NAMES = ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_API_TOKEN")
_hf_token_warned = False


def _mask_secret(value: str) -> str:
    """Muestra solo las últimas 4 letras de un secreto (nunca el valor completo)."""
    return f"...{value[-4:]}" if len(value) >= 8 else "***"


def get_hf_token() -> str | None:
    """Retorna el token de Hugging Face desde env o secretos de la plataforma.

    Orden: variable de entorno → Colab userdata → Kaggle Secrets. Si se encuentra,
    se normaliza en `HF_TOKEN` para que huggingface_hub y pyannote lo usen también
    de forma implícita. Si falta, se avisa una sola vez con instrucciones claras:
    `pyannote/speaker-diarization-3.1` es un repo con acceso restringido y sin
    token falla con `401 Unauthorized` (mensaje que no explica el motivo real).
    """
    global _hf_token_warned

    # 1. Variables de entorno (el lanzador de Colab/Kaggle las sincroniza al inicio)
    for name in HF_TOKEN_NAMES:
        val = os.getenv(name)
        if val and val.strip():
            token = val.strip()
            os.environ["HF_TOKEN"] = token
            return token

    # 2. Secretos de la plataforma (Colab userdata / Kaggle Secrets)
    for name in HF_TOKEN_NAMES:
        val = _get_platform_secret(name)
        if val:
            os.environ["HF_TOKEN"] = val
            print(
                f"🤗 [HF] Token cargado desde secretos ({name}, {_mask_secret(val)})",
                flush=True,
            )
            return val

    if not _hf_token_warned:
        _hf_token_warned = True
        print(
            "⚠️ [HF] No se encontró ningún token de Hugging Face "
            f"(buscado: {', '.join(HF_TOKEN_NAMES)}).\n"
            "   Pyannote fallará con '401 Unauthorized' porque "
            "pyannote/speaker-diarization-3.1 es un repo con acceso restringido.\n"
            "   • Google Colab: 🔑 Secretos → añade 'HF_TOKEN' y activa "
            "'Acceso del notebook' (se reinicia al importar o copiar el notebook).\n"
            "   • Kaggle: Add-ons → Secrets → añade 'HF_TOKEN' y actívalo para este notebook.\n"
            "   • Acepta las condiciones en https://hf.co/pyannote/speaker-diarization-3.1 "
            "y https://hf.co/pyannote/segmentation-3.0",
            flush=True,
        )

    return None


def get_drive_mount() -> bool: return _google_drive and is_colab()

