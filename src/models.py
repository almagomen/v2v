"""
Caché de modelos: carga una vez y reutiliza.
"""
from typing import Callable, Any

import sys

if not hasattr(sys, '_v2v_models_cache'):
    sys._v2v_models_cache: dict[str, Any] = {}

MODELS = sys._v2v_models_cache


def get_or_load_model(
    model_key: str,
    loader_fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    Carga un modelo la primera vez y lo reutiliza en llamadas posteriores.
    Args:
        model_key: Identificador único del modelo.
        loader_fn: Función que carga el modelo.
        *args, **kwargs: Argumentos que se pasan al loader_fn.
    """
    global MODELS
    if model_key not in MODELS:
        try:
            MODELS[model_key] = loader_fn(*args, **kwargs)
            print(f"✅ Modelo '{model_key}' cargado")
        except Exception as e:
            raise RuntimeError(f"⚠️ Error al cargar modelo '{model_key}': {e}") from e
    return MODELS[model_key]
