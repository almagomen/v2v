"""Etiquetado automático de emociones de Fish Audio (``/enhance/text``).

El endpoint que usa el panel web de Fish no forma parte de la API pública
documentada (no aparece en ``openapi.json``). Se integra como una mejora
opcional y tolerante a fallos: si no responde, se sintetiza el texto original
sin romper el job.

La respuesta de Fish se usa **tal cual**: no se normalizan pausas, no se
reformatean etiquetas y no se valida el contenido. La única excepción son las
etiquetas de emoción que el usuario ya escribió al principio del texto: esas
se conservan y sustituyen a las que devuelva Fish en esa misma posición.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, Optional

import requests

FISH_ENHANCE_URL = "https://api.fish.audio/enhance/text"

# Códigos que indican que la clave o la ruta privada no sirven para este
# proceso. Reintentar segmento a segmento solo llenaría el log de 401.
_FATAL_STATUS = (401, 403, 404)

_TAG_RE = re.compile(r"\[[^\]]*\]")
_LEADING_TAGS_RE = re.compile(r"^(?:\s*\[[^\]]*\]\s*)+")

_DISABLED_REASON: Optional[str] = None
_DISABLED_LOCK = threading.Lock()


def _disable(reason: str, log_fn: Callable[[str], None]) -> None:
    """Desactiva ``/enhance/text`` para el resto del proceso (una sola vez)."""
    global _DISABLED_REASON
    with _DISABLED_LOCK:
        already = _DISABLED_REASON is not None
        if not already:
            _DISABLED_REASON = reason
    if not already:
        log_fn(f"[auto-emociones] {reason}")
        log_fn(
            "[auto-emociones] /enhance/text desactivado para este proceso: "
            "se usará el texto original sin reintentos."
        )


def _disabled_reason() -> Optional[str]:
    with _DISABLED_LOCK:
        return _DISABLED_REASON


def reset_disable_state() -> None:
    """Reactiva el endpoint (útil para tests o tras cambiar la clave)."""
    global _DISABLED_REASON
    with _DISABLED_LOCK:
        _DISABLED_REASON = None


def _config():
    from src import config

    return config


def is_enabled() -> bool:
    """Lee el interruptor global ``V2V_FISH_AUTO_EMOTIONS`` (activado por defecto)."""
    return _config().get_fish_auto_emotions()


def get_version() -> str:
    """Versión de modelo usada por ``/enhance/text``."""
    return _config().get_fish_enhance_version()


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub(" ", text or "")


def _has_visible_text(text: str) -> bool:
    return bool(re.sub(r"\s+", "", _strip_tags(text)))


def _split_leading_tags(text: str) -> tuple[str, str]:
    match = _LEADING_TAGS_RE.match(text or "")
    if not match:
        return "", (text or "").strip()
    return match.group(0).strip(), (text or "")[match.end():].strip()


def prepare_enhanced_text(original: str, enhanced: str) -> str:
    """Devuelve la respuesta de Fish sin tocarla, salvo las etiquetas iniciales.

    Si el usuario ya puso una emoción al principio (``[excited] ...``), esa
    etiqueta manda y se descartan las que Fish añada en esa misma posición.
    El resto del texto se conserva exactamente como lo devolvió Fish.
    """
    result = (enhanced or "").strip()
    original_prefix, _ = _split_leading_tags(original)
    if original_prefix:
        _, rest = _split_leading_tags(result)
        result = f"{original_prefix} {rest}".strip()
    return result


def enhance_text(
    text: str,
    version: Optional[str] = None,
    timeout: int = 30,
    max_retries: int = 2,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """Devuelve el texto etiquetado por Fish o ``None`` si no se pudo mejorar.

    Nunca lanza excepciones: cualquier fallo se registra y se traduce en
    ``None`` para que el llamador sintetice el texto original.
    """

    def _log(message: str) -> None:
        if log_fn is not None:
            try:
                log_fn(message)
                return
            except Exception:
                pass
        print(message)

    text = (text or "").strip()
    if not _has_visible_text(text):
        return None

    if _disabled_reason():
        return None

    try:
        ver = (version or get_version()).strip().lower()
    except Exception:
        ver = (version or "s2.1-pro").strip().lower()
    try:
        from src.config import FISH_ENHANCE_VERSIONS

        if ver not in FISH_ENHANCE_VERSIONS:
            ver = get_version()
    except Exception:
        ver = version or "s2.1-pro"

    try:
        from src.config import get_fish_enhance_token

        token = get_fish_enhance_token()
    except Exception:
        token = None

    if not token:
        _log(
            "[auto-emociones] FISH_ENHANCE_TOKEN no configurado: se usa el texto "
            "original. Añade el token de sesión del Studio de Fish para activarlo."
        )
        return None

    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {"payload": {"text": text, "version": ver}}

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                FISH_ENHANCE_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            status = getattr(response, "status_code", 0)
            if status in _FATAL_STATUS:
                detail = ""
                if getattr(response, "text", ""):
                    detail = f" | {str(response.text)[:300]}"
                _disable(
                    f"/enhance/text rechazó el token (HTTP {status}){detail}. "
                    "Copia un token de sesión nuevo desde el Studio de Fish.",
                    _log,
                )
                return None
            if status == 429:
                wait = 2.0 * (attempt + 1)
                _log(
                    "[auto-emociones] Rate limit de Fish (429): "
                    f"reintentando en {wait:.1f}s..."
                )
                time.sleep(wait)
                continue
            if 400 <= status < 500:
                detail = ""
                if getattr(response, "text", ""):
                    detail = f" | {str(response.text)[:300]}"
                _log(
                    f"[auto-emociones] /enhance/text rechazó el texto "
                    f"(HTTP {status}){detail}: se usa el texto original."
                )
                return None
            response.raise_for_status()
            data = response.json()
            enhanced = str(data.get("enhanced_script") or "").strip()
            if not enhanced:
                _log(
                    "[auto-emociones] Fish devolvió una respuesta vacía: "
                    "se usa el texto original."
                )
                return None
            return prepare_enhanced_text(text, enhanced)

        except requests.exceptions.RequestException as exc:
            if attempt < max_retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            detail = ""
            response = getattr(exc, "response", None)
            if response is not None and getattr(response, "text", ""):
                detail = f" | {str(response.text)[:300]}"
            _log(f"[auto-emociones] Falló /enhance/text: {exc}{detail}")
            return None
        except Exception as exc:  # JSON inválido, etc.
            _log(f"[auto-emociones] Respuesta inválida de /enhance/text: {exc}")
            return None

    return None


def test_token(
    token: Optional[str] = None,
    version: Optional[str] = None,
    timeout: int = 20,
) -> dict:
    """Prueba el token de sesión contra ``/enhance/text`` sin desactivar nada.

    Devuelve un dict con ``ok``, ``status``, ``message`` y ``preview`` para que
    el panel pueda avisar de un token caducado o inválido al instante.
    """
    token_val = (token or "").strip()
    if not token_val:
        try:
            from src.config import get_fish_enhance_token

            token_val = (get_fish_enhance_token() or "").strip()
        except Exception:
            token_val = ""

    if not token_val:
        return {
            "ok": False,
            "status": 0,
            "message": "No hay FISH_ENHANCE_TOKEN configurado.",
            "preview": None,
        }

    try:
        from src.config import FISH_ENHANCE_VERSIONS
    except Exception:
        FISH_ENHANCE_VERSIONS = ("s2.1-pro", "drama-3")

    try:
        ver = (version or get_version()).strip().lower()
    except Exception:
        ver = "s2.1-pro"
    if ver not in FISH_ENHANCE_VERSIONS:
        ver = "s2.1-pro"

    headers = {
        "Authorization": f"Bearer {token_val}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "payload": {
            "text": "Hola, esta es una prueba de conexión.",
            "version": ver,
        }
    }

    try:
        response = requests.post(
            FISH_ENHANCE_URL, headers=headers, json=payload, timeout=timeout
        )
    except requests.exceptions.RequestException as exc:
        return {
            "ok": False,
            "status": 0,
            "message": f"Error de red al probar el token: {exc}",
            "preview": None,
        }

    status = int(getattr(response, "status_code", 0) or 0)
    body = str(getattr(response, "text", "") or "")

    if status == 200:
        try:
            data = response.json()
        except Exception:
            data = {}
        enhanced = str(data.get("enhanced_script") or "").strip()
        if enhanced:
            return {
                "ok": True,
                "status": 200,
                "message": "Token válido: /enhance/text responde correctamente.",
                "preview": enhanced[:200],
            }
        return {
            "ok": False,
            "status": 200,
            "message": "El token responde, pero Fish no devolvió texto mejorado.",
            "preview": None,
        }

    if status in (401, 403):
        return {
            "ok": False,
            "status": status,
            "message": (
                f"Token inválido o caducado (HTTP {status}). "
                "Copia uno nuevo del Studio de Fish."
            ),
            "preview": None,
        }

    detail = f" | {body[:200]}" if body else ""
    return {
        "ok": False,
        "status": status,
        "message": f"HTTP {status}{detail}",
        "preview": None,
    }


def enhance_texts(
    texts: list[str],
    version: Optional[str] = None,
    log_fn: Optional[Callable[[str], None]] = None,
    max_workers: int = 5,
) -> list[Optional[str]]:
    """Mejora una lista de textos en paralelo, conservando el orden."""
    if not texts:
        return []
    if len(texts) == 1:
        return [enhance_text(texts[0], version=version, log_fn=log_fn)]

    from concurrent.futures import ThreadPoolExecutor

    def _one(value: str) -> Optional[str]:
        return enhance_text(value, version=version, log_fn=log_fn)

    workers = max(1, min(max_workers, len(texts)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(_one, texts))
