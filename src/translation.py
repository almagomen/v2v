"""
Traducción y generación de títulos con Gemini y modelos de lenguaje (Gemma).
Soporta rotación de API keys, cascada de modelos y fallback robusto a texto.
"""
import json
import re
from typing import Optional

from src.config import get_google_api_key, get_google_api_keys, rotate_google_api_key

LANGUAGE_NAMES = {
    "es": "Español",
    "en": "Inglés",
    "fr": "Francés",
    "de": "Alemán",
    "it": "Italiano",
    "pt": "Portugués",
    "ja": "Japonés",
    "zh-CN": "Chino",
}

# Modelos oficiales: gemini-flash-latest por defecto para traducción de máxima calidad,
# con fallback automático a gemini-flash-lite-latest ante 503/429/timeout.
DEFAULT_TITLE_MODEL = "gemini-flash-lite-latest"
DEFAULT_TRANSLATION_MODEL = "gemini-flash-latest"

POPULAR_GEMINI_MODELS = [
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemma-4-31b-it",
]


def get_default_title_model() -> str:
    """Retorna el modelo configurado por defecto para títulos virales."""
    return DEFAULT_TITLE_MODEL


def set_default_title_model(model_name: str) -> None:
    """Permite cambiar el modelo por defecto para títulos virales en caliente."""
    global DEFAULT_TITLE_MODEL
    if model_name and isinstance(model_name, str):
        DEFAULT_TITLE_MODEL = model_name.strip()


def get_default_translation_model() -> str:
    """Retorna el modelo configurado por defecto para traducción."""
    return DEFAULT_TRANSLATION_MODEL


def set_default_translation_model(model_name: str) -> None:
    """Permite cambiar el modelo por defecto para traducción en caliente."""
    global DEFAULT_TRANSLATION_MODEL
    if model_name and isinstance(model_name, str):
        DEFAULT_TRANSLATION_MODEL = model_name.strip()


def get_default_gemini_model() -> str:
    """Retorna el modelo configurado por defecto para títulos (compatibilidad)."""
    return get_default_title_model()


def set_default_gemini_model(model_name: str) -> None:
    """Permite cambiar el modelo por defecto para títulos en caliente (compatibilidad)."""
    set_default_title_model(model_name)



def translate_text_list(
    list_sentences: list[str],
    target_lang: str,
    source_lang: str = "en",
    model_name: Optional[str] = None,
) -> list[str] | None:
    """
    Traduce una lista de frases a un idioma objetivo usando Gemini con fallback robusto
    y rotación automática de API keys ante cuotas o errores 503/429.
    """
    if not list_sentences:
        return []

    available_keys = get_google_api_keys()
    if not available_keys:
        print("❌ [Traducción] Error: No hay ninguna API Key de Google configurada.")
        return None

    from google import genai
    from google.genai import types

    source_lang_name = LANGUAGE_NAMES.get(source_lang, "español")
    target_lang_name = LANGUAGE_NAMES.get(target_lang, "ingles")

    prompt = f"""
Eres un especialista en doblaje audiovisual, transcreación y adaptación de diálogos para síntesis de voz (TTS).
Tu misión es REESCRIBIR cada frase al {target_lang_name}, capturando con total fidelidad la IDEA, la intención, el significado y el tono original del {source_lang_name}, pero adaptándola para que suene 100% natural, fluida y creíble como la expresaría un hablante nativo.

Directrices obligatorias:
1. REESCRIBE LA FRASE MANTENIENDO LA IDEA: No hagas una traducción literal o palabra por palabra. Reformula y reescribe la oración preservando la misma idea central y sentido, usando expresiones coloquiales y naturales adecuadas al {target_lang_name}.
2. VOZ HABLADA Y DOBLAJE: El texto será sintetizado por modelos de voz (TTS). La frase debe tener ritmo fonético natural, ser directa y sonar convincente y orgánica al ser escuchada.
3. CONCISIÓN TEMPORAL: Mantén una longitud similar a la frase original para no desbordar los tiempos de habla del clip de video. Evita redundancias o explicaciones innecesarias.
4. COHERENCIA: Las frases forman parte de un diálogo o narración continua; preserva la coherencia temática y el flujo entre ellas.
5. PRESERVACIÓN DE EMOCIONES: Si alguna frase original incluye marcadores de emoción entre corchetes como [happy], [whisper], [laughter], [sad], [excited], etc., CONSÉRVALOS en la posición correspondiente dentro de la frase reescrita.

Texto original ({source_lang_name}):
---
{json.dumps(list_sentences, indent=2, ensure_ascii=False)}
---

Devuelve ÚNICAMENTE una lista JSON válida de strings, donde cada elemento sea la frase reescrita en el mismo orden:
["frase 1 reescrita", "frase 2 reescrita", ...]
"""

    models_to_try = [model_name.strip()] if (model_name and model_name.strip()) else [DEFAULT_TRANSLATION_MODEL]
    for fallback in POPULAR_GEMINI_MODELS:
        if fallback not in models_to_try:
            models_to_try.append(fallback)

    last_error = None

    for m_idx, model in enumerate(models_to_try):
        keys_to_attempt = list(available_keys)
        for k_idx, key in enumerate(keys_to_attempt):
            key_tag = f"...{key[-4:]}" if len(key) >= 4 else "***"
            print(f"🌐 [Traducción] Probando modelo '{model}' (API Key {k_idx + 1}/{len(keys_to_attempt)}: {key_tag})...")
            try:
                # Timeout de 40s para no congelar la llamada en picos de demanda
                client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=40000))
                is_gemma = "gemma" in model.lower()

                config = {"response_mime_type": "application/json"} if not is_gemma else None
                response = client.models.generate_content(
                    model=model,
                    contents=[prompt],
                    config=config,
                )

                if response and response.text:
                    raw_text = response.text.strip()
                    match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_text, re.DOTALL)
                    clean_json = match.group(1) if match else raw_text
                    parsed = json.loads(clean_json)
                    if isinstance(parsed, list):
                        print(f"✅ [Traducción] Éxito con '{model}' ({len(parsed)} segmentos adaptados)")
                        return parsed
            except Exception as e:
                last_error = e
                err_str = str(e)
                print(f"⚠️ [Traducción] Error con '{model}' (key {key_tag}): {e}")
                if len(available_keys) > 1 and any(code in err_str for code in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "quota", "timeout")):
                    rotate_google_api_key()
                    if k_idx + 1 < len(keys_to_attempt):
                        next_key_tag = f"...{keys_to_attempt[k_idx + 1][-4:]}" if len(keys_to_attempt[k_idx + 1]) >= 4 else "***"
                        print(f"🔄 [Traducción] Rotando a siguiente API Key ({next_key_tag}) para reintentar con '{model}'...")
                continue

        # Si el modelo falló con todas las claves disponibles, rotar al siguiente modelo de la cascada
        if m_idx + 1 < len(models_to_try):
            next_model = models_to_try[m_idx + 1]
            print(f"🔄 [Traducción] Modelo principal '{model}' no disponible. Rotando automáticamente al modelo de respaldo: '{next_model}'...")

    print(f"❌ [Traducción] Fallaron todos los modelos y claves. Último error: {last_error}")
    return None


def generate_tiktok_title(
    youtube_url: Optional[str] = None,
    target_lang: str = "es",
    model_name: Optional[str] = None,
    fallback_text: Optional[str] = None,
) -> str | None:
    """
    Genera un título viral para TikTok con emojis y hashtags.
    Soporta:
      - Prioridad a texto transcrito directo (latencia ultra baja: 1-2 segundos).
      - Fallback secundario a YouTube URI multimodal solo si no hay transcripción.
      - Cascada de modelos y rotación automática de API keys con logs detallados.
    """
    available_keys = get_google_api_keys()
    if not available_keys:
        print("⚠️ [Título Viral] No hay ninguna GOOGLE_API_KEY configurada.")
        return None

    from google import genai
    from google.genai import types

    target_lang_name = LANGUAGE_NAMES.get(target_lang, "español")

    base_prompt = f"""Eres un experto en marketing digital y creación de contenido viral.
Tu misión es generar EL TÍTULO MÁS LLAMATIVO para TikTok que despierte curiosidad
y haga que la gente quiera ver el video completo.

Requisitos:
- El título debe estar en {target_lang_name}.
- Usa EMOJIS impactantes y relevantes que capten la atención.
- Incluye 5 HASHTAGS virales y relacionados con el tema del video.
- Hazlo breve, explosivo y con estilo auténtico de TikTok.
- El título debe provocar intriga, emoción o sorpresa.

IMPORTANTE: Devuelve **solo el título final**, sin explicaciones ni opciones adicionales.
"""

    selected_model = (model_name.strip() if (model_name and model_name.strip()) else DEFAULT_TITLE_MODEL)
    models_to_try = [selected_model]

    if "gemma-4-31b-it" not in models_to_try:
        models_to_try.append("gemma-4-31b-it")

    if selected_model != "gemini-flash-latest":
        models_to_try = [m for m in models_to_try if m != "gemini-flash-latest"]

    is_yt_url = bool(
        youtube_url
        and isinstance(youtube_url, str)
        and (youtube_url.startswith("http://") or youtube_url.startswith("https://"))
    )

    last_error = None

    for m_idx, model in enumerate(models_to_try):
        keys_to_attempt = list(available_keys)

        for k_idx, key in enumerate(keys_to_attempt):
            key_tag = f"...{key[-4:]}" if len(key) >= 4 else "***"
            client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=25000))

            # PRIORIDAD 1: Texto transcrito (extremadamente rápido: ~1-2s vs ~200s de video)
            if fallback_text and fallback_text.strip():
                try:
                    text_prompt = f"{base_prompt}\n\nTranscripción / Diálogos del video:\n{fallback_text.strip()[:3500]}"
                    response = client.models.generate_content(model=model, contents=[text_prompt])
                    if response and response.text and response.text.strip():
                        return response.text.strip().replace("\n", " ").strip("\"'")
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    print(f"⚠️ [Título Viral] Error con '{model}' vía texto (key {key_tag}): {e}")
                    if len(available_keys) > 1 and any(code in err_str for code in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "timeout")):
                        rotate_google_api_key()
                        if k_idx + 1 < len(keys_to_attempt):
                            next_key_tag = f"...{keys_to_attempt[k_idx + 1][-4:]}" if len(keys_to_attempt[k_idx + 1]) >= 4 else "***"
                            print(f"🔄 [Título Viral] Rotando a siguiente API Key ({next_key_tag}) para '{model}'...")

            # PRIORIDAD 2 (Fallback si no hay texto transcrito): Video multimodal YouTube
            if is_yt_url and "gemma" not in model.lower():
                try:
                    print(f"🌐 [Título Viral] Intentando generación multimodal con '{model}' vía YouTube URI (key {key_tag})...")
                    contents = types.Content(
                        parts=[
                            types.Part(file_data=types.FileData(file_uri=youtube_url)),
                            types.Part(text=base_prompt),
                        ]
                    )
                    response = client.models.generate_content(model=model, contents=contents)
                    if response and response.text and response.text.strip():
                        return response.text.strip().replace("\n", " ").strip("\"'")
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    print(f"⚠️ [Título Viral] Error con '{model}' vía YouTube URI (key {key_tag}): {e}")
                    if len(available_keys) > 1 and any(code in err_str for code in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "timeout")):
                        rotate_google_api_key()
                        if k_idx + 1 < len(keys_to_attempt):
                            next_key_tag = f"...{keys_to_attempt[k_idx + 1][-4:]}" if len(keys_to_attempt[k_idx + 1]) >= 4 else "***"
                            print(f"🔄 [Título Viral] Rotando a siguiente API Key ({next_key_tag}) para '{model}'...")

        if m_idx + 1 < len(models_to_try):
            next_model = models_to_try[m_idx + 1]
            print(f"🔄 [Título Viral] Modelo '{model}' agotado. Rotando automáticamente a: '{next_model}'...")

    print(f"❌ [Título Viral] No se pudo generar título viral con ninguno de los modelos. Último error: {last_error}")
    return None
