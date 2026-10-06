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

# Modelos oficiales: gemini-flash-lite-latest por defecto para títulos (rápido y ligero),
# gemini-flash-latest por defecto para traducción de diálogos/subtítulos.
DEFAULT_TITLE_MODEL = "gemini-flash-lite-latest"
DEFAULT_TRANSLATION_MODEL = "gemini-flash-latest"

POPULAR_GEMINI_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemma-4-31b-it",
]


def get_default_gemini_model() -> str:
    """Retorna el modelo configurado por defecto para títulos."""
    return DEFAULT_TITLE_MODEL


def set_default_gemini_model(model_name: str) -> None:
    """Permite cambiar el modelo por defecto para títulos en caliente."""
    global DEFAULT_TITLE_MODEL
    if model_name and isinstance(model_name, str):
        DEFAULT_TITLE_MODEL = model_name.strip()



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
        print("❌ Error: No hay ninguna API Key de Google configurada. No se puede traducir.")
        return None

    from google import genai

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

    for model in models_to_try:
        # Para cada modelo, intentar con las API Keys disponibles rotando si es necesario
        keys_to_attempt = list(available_keys)
        for key in keys_to_attempt:
            try:
                client = genai.Client(api_key=key)
                is_gemma = "gemma" in model.lower()

                config = {"response_mime_type": "application/json"} if not is_gemma else None
                response = client.models.generate_content(
                    model=model,
                    contents=[prompt],
                    config=config,
                )

                if response and response.text:
                    raw_text = response.text.strip()
                    # Extraer bloque json si el modelo devolvió markdown
                    match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_text, re.DOTALL)
                    clean_json = match.group(1) if match else raw_text
                    parsed = json.loads(clean_json)
                    if isinstance(parsed, list):
                        return parsed
            except Exception as e:
                last_error = e
                err_str = str(e)
                # Si hay error de cuota o disponibilidad y tenemos más keys, rotar
                if len(available_keys) > 1 and any(code in err_str for code in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "quota")):
                    rotate_google_api_key()
                print(f"⚠️ Error al traducir con {model} (key ...{key[-4:] if len(key) >= 4 else '***'}): {e}")
                continue

    print(f"❌ Fallaron todos los modelos y keys para traducción: {last_error}")
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
      - Cascada de modelos (gemini-flash-latest -> gemini-flash-lite-latest -> gemma-4-31b-it).
      - Rotación automática de API keys ante cuotas o errores 503/429.
      - Para Gemma (que no acepta URLs de YouTube), utiliza directamente el texto transcrito (fallback_text).
    """
    available_keys = get_google_api_keys()
    if not available_keys:
        print("⚠️ No hay ninguna GOOGLE_API_KEY configurada para generar título viral.")
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

    models_to_try = [model_name.strip()] if (model_name and model_name.strip()) else [DEFAULT_TITLE_MODEL]
    for m in POPULAR_GEMINI_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    is_yt_url = bool(
        youtube_url
        and isinstance(youtube_url, str)
        and (youtube_url.startswith("http://") or youtube_url.startswith("https://"))
    )

    last_error = None

    for model in models_to_try:
        is_gemma = "gemma" in model.lower()
        keys_to_attempt = list(available_keys)

        for key in keys_to_attempt:
            client = genai.Client(api_key=key)

            # Intento 1: Si es un modelo Gemini multimodal y tenemos URL de YouTube
            if is_yt_url and not is_gemma:
                try:
                    contents = types.Content(
                        parts=[
                            types.Part(file_data=types.FileData(file_uri=youtube_url)),
                            types.Part(text=base_prompt),
                        ]
                    )
                    response = client.models.generate_content(model=model, contents=contents)
                    if response and response.text and response.text.strip():
                        title = response.text.strip().replace("\n", " ").strip("\"'")
                        print(f"✨ Título viral generado con {model} (vía YouTube URI): {title}")
                        return title
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    if len(available_keys) > 1 and any(code in err_str for code in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")):
                        rotate_google_api_key()
                    print(f"⚠️ Error con {model} vía YouTube URI ({e}). Intentando con texto...")

            # Intento 2: Mediante fallback_text (subtítulos/transcripción de los segmentos)
            # Para gemma-4-31b-it este es el camino directo ya que Gemma no soporta URLs de YouTube
            if fallback_text and fallback_text.strip():
                try:
                    text_prompt = f"{base_prompt}\n\nTranscripción / Diálogos del video:\n{fallback_text.strip()[:3500]}"
                    response = client.models.generate_content(model=model, contents=[text_prompt])
                    if response and response.text and response.text.strip():
                        title = response.text.strip().replace("\n", " ").strip("\"'")
                        print(f"✨ Título viral generado con {model} (vía fallback_text transcrito): {title}")
                        return title
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    if len(available_keys) > 1 and any(code in err_str for code in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")):
                        rotate_google_api_key()
                    print(f"⚠️ Error con {model} vía texto ({e})")

    print(f"❌ No se pudo generar título viral con ninguno de los modelos. Último error: {last_error}")
    return None
