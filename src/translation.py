"""
Traducción y generación de títulos con Gemini.
"""
import json

from src.config import get_google_api_key

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


def translate_text_list(
    list_sentences: list[str],
    target_lang: str,
    source_lang: str = "en",
) -> list[str] | None:
    """
    Traduce una lista de frases a un idioma objetivo usando Gemini.
    """
    if not list_sentences:
        return []

    GOOGLE_API_KEY = get_google_api_key()
    if not GOOGLE_API_KEY:
        print("Error: La API Key de Google no está configurada. No se puede traducir.")
        return None

    from google import genai

    client = genai.Client(api_key=GOOGLE_API_KEY)
    source_lang_name = LANGUAGE_NAMES.get(source_lang, "español")
    target_lang_name = LANGUAGE_NAMES.get(target_lang, "ingles")

    prompt = f"""
Eres un traductor experto. Traduce el siguiente texto del {source_lang_name} al {target_lang_name}.
El texto original está compuesto por varias frases que forman un párrafo o una secuencia lógica.
Es CRUCIAL que mantengas la coherencia, el tono y el contexto entre todas las frases traducidas.
Utiliza las mejores prácticas de traducción para el {target_lang_name}.

Texto original en {source_lang_name}:
---
{json.dumps(list_sentences, indent=2, ensure_ascii=False)}
---

Por favor, devuelve la traducción como una LISTA JSON de strings, donde cada string
corresponda a una frase traducida, manteniendo el mismo orden que las frases originales.
Cada string traducida debe tener una longitud similar a la del lenguaje original.
Asegúrate de que la salida sea únicamente la lista JSON y nada más.
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[prompt],
        config={"response_mime_type": "application/json"},
    )
    return json.loads(response.text.strip())


def generate_tiktok_title(
    youtube_url: str,
    target_lang: str = "es",
) -> str | None:
    GOOGLE_API_KEY = get_google_api_key()
    if not GOOGLE_API_KEY:
        return None

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GOOGLE_API_KEY)
    target_lang_name = LANGUAGE_NAMES.get(target_lang, "español")

    prompt = f"""Eres un experto en marketing digital y creación de contenido viral.
Tu misión es generar EL TÍTULO MÁS LLAMATIVO para TikTok que despierte curiosidad
y haga que la gente quiera ver el video completo.

Requisitos:
- El título debe estar en español.
- Usa EMOJIS impactantes y relevantes que capten la atención.
- Incluye 5 HASHTAGS virales y relacionados con el tema del video.
- Hazlo breve, explosivo y con estilo auténtico de TikTok.
- El título debe provocar intriga, emoción o sorpresa.

IMPORTANTE: Devuelve **solo el título final**, sin explicaciones ni opciones adicionales.
"""
    model = "gemini-2.5-flash"
    contents = types.Content(
        parts=[
            types.Part(file_data=types.FileData(file_uri=youtube_url)),
            types.Part(text=prompt),
        ]
    )
    response = client.models.generate_content(model=model, contents=contents)
    return response.text.strip() if response.text else None
