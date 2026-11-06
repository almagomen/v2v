"""Resolución de alias ``*-latest`` de Gemini.

La API de Interactions rechaza algunos alias que sí existen en el playground
(``gemini-flash-lite-latest`` → 404). En vez de fijar una versión concreta —que
envejece en cuanto sale la siguiente— se consulta la lista de modelos y se usa
el más reciente de la misma familia. El alias se cachea para que el 404 ocurra
una sola vez por proceso.

Este módulo no importa ``google-genai``: solo usa el cliente que recibe, de modo
que sus pruebas corren sin la librería instalada.
"""
from __future__ import annotations

import re
from typing import Any, Optional, Tuple

# Alias → modelo concreto ya resuelto.
_MODEL_ALIAS_CACHE: dict[str, str] = {}


def model_alias_family(alias: str) -> Optional[Tuple[str, str]]:
    """Descompone un alias ``*-latest`` en (proveedor, familia).

    ``gemini-flash-lite-latest`` → ``("gemini", "flash-lite")``. Los segmentos
    numéricos de versión se descartan para que ``gemini-3.5-flash-lite`` también
    cuente como miembro de la familia.
    """
    name = (alias or "").strip().lower()
    if not name.endswith("-latest"):
        return None
    base = name[: -len("-latest")]
    parts = [p for p in base.split("-") if p]
    if not parts:
        return None
    vendor = parts[0]
    family = [p for p in parts[1:] if not re.fullmatch(r"\d+(?:\.\d+)?", p)]
    return vendor, "-".join(family) or base


def is_model_not_found(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(tok in text for tok in ("404", "not found", "not_found"))


def resolve_latest_alias(client: Any, alias: str) -> Optional[str]:
    """Busca el modelo concreto más reciente de la familia de un alias ``-latest``.

    La API de Interactions no resuelve algunos alias que sí aparecen en el
    playground/documentación. En vez de fijar una versión (que envejece), se
    consulta la lista de modelos y se elige el más nuevo de la misma familia.
    """
    cached = _MODEL_ALIAS_CACHE.get(alias)
    if cached:
        return cached

    family = model_alias_family(alias)
    if not family:
        return None
    vendor, fam = family

    try:
        models = list(client.models.list())
    except Exception:
        return None

    candidates: list[tuple[str, str]] = []
    for item in models:
        name = str(getattr(item, "name", "") or "").strip()
        if name.startswith("models/"):
            name = name[len("models/"):]
        low = name.lower()
        # Los modelos versionados añaden un sufijo numérico ("-001"): no cambia
        # la familia. Se compara el final exacto para que "flash" no capture
        # "flash-lite" (son modelos distintos, con precio y calidad distintos).
        low = re.sub(r"-\d{3}$", "", low)
        if not low.startswith(vendor) or not low.endswith("-" + fam):
            continue
        # Se descartan otros alias y modelos que no sirven para texto.
        if low.endswith("-latest") or any(
            tok in low
            for tok in ("exp", "preview", "image", "tts", "audio", "live", "embedding", "veo", "imagen")
        ):
            continue
        candidates.append((str(getattr(item, "create_time", "") or ""), name))

    if not candidates:
        return None

    candidates.sort(key=lambda pair: (pair[0], pair[1]), reverse=True)
    resolved = candidates[0][1]
    _MODEL_ALIAS_CACHE[alias] = resolved
    return resolved


def create_interaction(client: Any, call_kwargs: dict[str, Any]) -> Any:
    """Crea la interacción y, si un alias ``-latest`` no existe, lo resuelve.

    Se reintenta una sola vez con el modelo concreto más reciente de la familia.
    Cualquier otro error se propaga sin tocar el nombre del modelo.
    """
    kwargs = dict(call_kwargs)
    model = str(kwargs.get("model") or "")
    try:
        return client.interactions.create(**kwargs)
    except Exception as exc:
        if not is_model_not_found(exc):
            raise
        resolved = resolve_latest_alias(client, model)
        if not resolved or resolved == model:
            raise
        print(
            f"ℹ️ [Gemini] El alias '{model}' no existe en la API; "
            f"se usa '{resolved}' (última versión disponible).",
            flush=True,
        )
        kwargs["model"] = resolved
        return client.interactions.create(**kwargs)
