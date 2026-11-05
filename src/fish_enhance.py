"""Etiquetado automático de emociones de Fish Audio (``/enhance/text``).

El endpoint que usa el panel web de Fish no forma parte de la API pública
documentada (no aparece en ``openapi.json``). Se integra como una mejora
opcional y tolerante a fallos: si no responde, se sintetiza el texto original
sin romper el job.

Reglas de seguridad para no estropear la locución:

* El texto solo puede recibir etiquetas ``[..]``; si el endpoint reescribe
  palabras, se descarta la respuesta.
* Las etiquetas de emoción que el usuario ya puso al principio mandan: se
  conservan y se eliminan las que añada el endpoint en esa misma posición.
* Las pausas se normalizan a la sintaxis documentada de S2 (``[break]`` y
  ``[long-break]``), porque el endpoint devuelve variantes como ``[pause]`` o
  ``[short pause]``.
"""

from __future__ import annotations

import difflib
import os
import re
import time
import unicodedata
from typing import Optional

import requests

FISH_ENHANCE_URL = "https://api.fish.audio/enhance/text"
DEFAULT_ENHANCE_VERSION = "s2.1-pro"
# Solo la familia S2 usa corchetes. S1 (paréntesis) y drama-3 (direcciones en
# lenguaje natural) no son intercambiables con el TTS por defecto.
ENHANCE_VERSIONS = ("s2.1-pro", "s2-pro")

_TAG_RE = re.compile(r"\[[^\]]*\]")
_LEADING_TAGS_RE = re.compile(r"^(?:\s*\[[^\]]*\]\s*)+")
_PAUSE_TAG_RE = re.compile(
    r"\[\s*(?:(short|long)\s+)?(?:pause|break|silence)\s*\]",
    re.IGNORECASE,
)
_DUP_TAG_RE = re.compile(r"(\[[^\]]+\])(?:\s*\1)+", re.IGNORECASE)
_TAG_SPACE_RE = re.compile(r"\]\s*(?=[^\s\]\.,;:!?¿¡\"'»”’])")

# Caché en memoria: regenerar el mismo texto dentro de la misma sesión devuelve
# exactamente las mismas etiquetas y evita una llamada HTTP extra.
_CACHE: dict[tuple[str, str], str] = {}
_CACHE_MAX = 2048


def is_enabled() -> bool:
    """Lee el interruptor global ``V2V_FISH_AUTO_EMOTIONS``."""
    raw = (os.getenv("V2V_FISH_AUTO_EMOTIONS") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def get_version() -> str:
    """Versión de modelo usada por ``/enhance/text`` (familia S2)."""
    value = (os.getenv("V2V_FISH_ENHANCE_VERSION") or DEFAULT_ENHANCE_VERSION).strip().lower()
    return value if value in ENHANCE_VERSIONS else DEFAULT_ENHANCE_VERSION


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub(" ", text or "")


def _has_visible_text(text: str) -> bool:
    return bool(re.sub(r"\s+", "", _strip_tags(text)))


def _comparable(text: str) -> str:
    """Texto sin etiquetas, espacios, puntuación ni acentos.

    Así ``TLOUS`` y ``T L O U S`` cuentan como el mismo contenido: el endpoint
    a veces separa siglas para que el TTS las deletree, y eso no es una
    reescritura destructiva.
    """
    plain = _strip_tags(text)
    plain = unicodedata.normalize("NFKD", plain)
    return "".join(ch for ch in plain.lower() if ch.isalnum())


def _is_safe_rewrite(original: str, enhanced: str) -> bool:
    """Acepta solo cambios de etiquetas, no reescrituras del contenido."""
    before = _comparable(original)
    after = _comparable(enhanced)
    if not before or not after:
        return False
    if len(after) / len(before) < 0.75 or len(after) / len(before) > 1.40:
        return False
    return difflib.SequenceMatcher(None, before, after).ratio() >= 0.90


def _normalize_pause_tags(text: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        return "[long-break]" if (match.group(1) or "").lower() == "long" else "[break]"

    return _PAUSE_TAG_RE.sub(_repl, text)


def _dedupe_adjacent_tags(text: str) -> str:
    return _DUP_TAG_RE.sub(r"\1", text)


def _ensure_space_after_tags(text: str) -> str:
    """El endpoint a veces devuelve ``[emphasis]palabra``; separa la etiqueta."""
    return _TAG_SPACE_RE.sub("] ", text)


def _split_leading_tags(text: str) -> tuple[str, str]:
    match = _LEADING_TAGS_RE.match(text or "")
    if not match:
        return "", (text or "").strip()
    return match.group(0).strip(), (text or "")[match.end():].strip()


def prepare_enhanced_text(original: str, enhanced: str) -> str:
    """Normaliza la respuesta y protege las etiquetas que puso el usuario."""
    result = _normalize_pause_tags(enhanced or "").strip()
    result = _ensure_space_after_tags(result)
    result = _dedupe_adjacent_tags(result)

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
) -> Optional[str]:
    """Devuelve el texto con etiquetas de emoción o ``None`` si no es seguro.

    Nunca lanza excepciones: cualquier fallo se traduce en ``None`` para que el
    llamador sintetice el texto original.
    """
    text = (text or "").strip()
    if not _has_visible_text(text):
        return None

    ver = (version or get_version()).strip().lower()
    if ver not in ENHANCE_VERSIONS:
        ver = DEFAULT_ENHANCE_VERSION

    cache_key = (ver, text)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        from src.config import get_fish_api_key

        api_key = get_fish_api_key()
    except Exception:
        api_key = None

    if not api_key:
        return None

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
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
            if response.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            response.raise_for_status()
            data = response.json()
            enhanced = str(data.get("enhanced_script") or "").strip()
            if not enhanced:
                return None
            if not _is_safe_rewrite(text, enhanced):
                print("[auto-emociones] Respuesta descartada: reescribe el texto original.")
                return None

            result = prepare_enhanced_text(text, enhanced)
            if not result:
                return None

            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.clear()
            _CACHE[cache_key] = result
            return result

        except requests.exceptions.RequestException as exc:
            if attempt < max_retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            print(f"[auto-emociones] No disponible: {exc}")
            return None
        except Exception as exc:  # JSON inválido, etc.
            print(f"[auto-emociones] Respuesta inválida: {exc}")
            return None

    return None


def clear_cache() -> None:
    """Vacía la caché (útil en tests o al cambiar de clave/versión)."""
    _CACHE.clear()
