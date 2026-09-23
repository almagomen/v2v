"""
Traducción y generación de títulos con Gemini.
"""
import json
from typing import Optional

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
    model_name: Optional[str] = None,
) -> list[str] | None:
    """
    Traduce una lista de frases a un idioma objetivo usando Gemini con fallback robusto.
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

    selected_model = model_name or "gemini-flash-latest"
    try:
        response = client.models.generate_content(
            model=selected_model,
            contents=[prompt],
            config={"response_mime_type": "application/json"},
        )
        return json.loads(response.text.strip())
    except Exception as e:
        if not model_name and selected_model != "gemini-flash-lite-latest":
            print(f"⚠️ Error con {selected_model}, intentando fallback a gemini-flash-lite-latest: {e}")
            try:
                response = client.models.generate_content(
                    model="gemini-flash-lite-latest",
                    contents=[prompt],
                    config={"response_mime_type": "application/json"},
                )
                return json.loads(response.text.strip())
            except Exception as e2:
                print(f"❌ Fallback a gemini-flash-lite-latest fallido: {e2}")
                raise e2
        else:
            raise e


def generate_tiktok_title(
    youtube_url: str,
    target_lang: str = "es",
    model_name: Optional[str] = None,
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
    selected_model = model_name or "gemini-3.1-flash-lite"
    contents = types.Content(
        parts=[
            types.Part(file_data=types.FileData(file_uri=youtube_url)),
            types.Part(text=prompt),
        ]
    )

    try:
        response = client.models.generate_content(model=selected_model, contents=contents)
        return response.text.strip() if response.text else None
    except Exception as e:
        if not model_name and selected_model != "gemini-3.1-flash-lite":
            print(f"⚠️ Error con {selected_model}, intentando fallback a gemini-3.1-flash-lite: {e}")
            try:
                response = client.models.generate_content(model="gemini-3.1-flash-lite", contents=contents)
                return response.text.strip() if response.text else None
            except Exception as e2:
                print(f"❌ Fallback a gemini-3.1-flash-lite fallido: {e2}")
                raise e2
        else:
            raise e
