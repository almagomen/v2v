import os
import json
import re
import time
from typing import Optional

from google import genai

from src.config import get_google_api_keys, rotate_google_api_key

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

# Modelos recomendados: gemini-flash-lite-latest (alta velocidad, sin errores 503) y gemma-4-26b-a4b-it como respaldo
DEFAULT_TITLE_MODEL = os.environ.get("DEFAULT_TITLE_MODEL", "gemini-flash-lite-latest")
DEFAULT_TRANSLATION_MODEL = os.environ.get("DEFAULT_TRANSLATION_MODEL", "gemini-flash-lite-latest")

POPULAR_GEMINI_MODELS = [
    "gemini-flash-lite-latest",
    "gemma-4-26b-a4b-it",
]


def get_default_title_model() -> str:
    return DEFAULT_TITLE_MODEL


def set_default_title_model(model_name: str) -> None:
    global DEFAULT_TITLE_MODEL
    if model_name and isinstance(model_name, str):
        DEFAULT_TITLE_MODEL = model_name.strip()


def get_default_translation_model() -> str:
    return DEFAULT_TRANSLATION_MODEL


def set_default_translation_model(model_name: str) -> None:
    global DEFAULT_TRANSLATION_MODEL
    if model_name and isinstance(model_name, str):
        DEFAULT_TRANSLATION_MODEL = model_name.strip()


def get_default_gemini_model() -> str:
    return get_default_title_model()


def set_default_gemini_model(model_name: str) -> None:
    set_default_title_model(model_name)


def translate_text_list(
    list_sentences: list[str],
    target_lang: str,
    source_lang: str = "en",
    model_name: Optional[str] = None,
    print_full_prompt: bool = False,
) -> list[str] | None:
    """
    Traduce una lista de frases a un idioma objetivo usando Gemini (Interactions API).
    Soporta cascada limpia de modelos (lite -> gemma) y rotación de API Keys.
    """
    if not list_sentences:
        return []

    available_keys = get_google_api_keys()
    if not available_keys:
        print("❌ [Traducción] Error: No hay ninguna API Key de Google configurada.", flush=True)
        return None

    source_lang_name = LANGUAGE_NAMES.get(source_lang, "español")
    target_lang_name = LANGUAGE_NAMES.get(target_lang, "español")

    total_count = len(list_sentences)
    input_dict = {str(i + 1): s for i, s in enumerate(list_sentences)}

    prompt = f"""Eres un especialista en doblaje audiovisual, transcreación y adaptación de diálogos para síntesis de voz (TTS).
Tu misión es REESCRIBIR cada frase al {target_lang_name}, capturando con total fidelidad la IDEA, la intención, el significado y el tono original del {source_lang_name}, pero adaptándola para que suene 100% natural, fluida y creíble como la expresaría un hablante nativo.

Directrices obligatorias:
1. REGLA ESTRICTA 1-A-1: La entrada contiene EXACTAMENTE {total_count} frases indexadas con claves numéricas del "1" al "{total_count}". Tu salida DEBE ser un objeto JSON con EXACTAMENTE las mismas {total_count} claves numéricas (del "1" al "{total_count}").
2. PROHIBIDO DIVIDIR O FUSIONAR: Cada clave numérica "N" representa un clip de audio individual fijado en el tiempo. NO agregues claves nuevas (ej. "{total_count + 1}"), NO omitas claves y NO dividas una frase en múltiples claves. Si una adaptación requiere dos oraciones, colócalas juntas dentro del mismo string de la clave correspondiente.
3. REESCRIBE MANTENIENDO LA IDEA: No hagas una traducción literal o palabra por palabra. Reformula y reescribe preservando la misma idea central y sentido, usando expresiones coloquiales y naturales adecuadas al {target_lang_name}.
4. VOZ HABLADA Y DOBLAJE: El texto será sintetizado por modelos de voz (TTS). La frase debe tener ritmo fonético natural, ser directa y sonar convincente y orgánica al ser escuchada.
5. CONCISIÓN TEMPORAL: Mantén una longitud similar a la frase original para no desbordar los tiempos de habla del clip de video. Evita redundancias o explicaciones innecesarias.
6. COHERENCIA: Las frases forman parte de un diálogo o narración continua; preserva la coherencia temática y el flujo entre ellas.
7. PRESERVACIÓN DE EMOCIONES: Si alguna frase original incluye marcadores de emoción entre corchetes como [happy], [whisper], [laughter], [sad], [excited], etc., CONSÉRVALOS en la posición correspondiente dentro de la frase reescrita.

Texto original ({source_lang_name}) indexado por segmento:
---
{json.dumps(input_dict, indent=2, ensure_ascii=False)}
---

Devuelve ÚNICAMENTE un objeto JSON válido con exactamente las mismas claves numéricas del "1" al "{total_count}":
{{
  "1": "frase 1 adaptada al {target_lang_name}",
  "2": "frase 2 adaptada al {target_lang_name}",
  ...
  "{total_count}": "frase {total_count} adaptada al {target_lang_name}"
}}"""

    # En la celda del cuaderno se puede activar el prompt completo; en el panel V2V mantenemos logs limpios y descriptivos
    if print_full_prompt:
        print("\n" + "=" * 60, flush=True)
        print(f"📄 [PROMPT COMPLETO ENVIADO A GEMINI] ({len(list_sentences)} frases):", flush=True)
        print("-" * 60, flush=True)
        print(prompt, flush=True)
        print("=" * 60 + "\n", flush=True)
    # Modelos a intentar en orden: el solicitado (o DEFAULT), con fallback a los populares
    models_to_try = [model_name.strip()] if (model_name and model_name.strip()) else [DEFAULT_TRANSLATION_MODEL]
    for m in POPULAR_GEMINI_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    last_error = None

    for m_idx, model in enumerate(models_to_try):
        is_gemma = "gemma" in model.lower()

        keys_to_attempt = list(available_keys)
        for k_idx, key in enumerate(keys_to_attempt):
            key_tag = f"...{key[-4:]}" if len(key) >= 4 else "***"

            print(f"🌐 [Traducción {source_lang_name} -> {target_lang_name}] Probando '{model}' (Key {k_idx + 1}/{len(keys_to_attempt)}: {key_tag})...", flush=True)
            t_start = time.perf_counter()

            try:
                # Cliente nativo oficial google-genai
                client = genai.Client(api_key=key)

                call_kwargs = {
                    "model": model,
                    "input": prompt,
                }
                if not is_gemma:
                    call_kwargs["response_format"] = [{"type": "text", "mime_type": "application/json"}]

                # Inferencia con Interactions API
                try:
                    interaction = client.interactions.create(**call_kwargs)
                except Exception as e_rf:
                    # Si el modelo no soporta response_format (ej. Gemma), reintentar sin formato estricto
                    err_text = str(e_rf).lower()
                    if ("response_format" in err_text or "schema" in err_text) and not any(c in err_text for c in ("503", "429", "high demand")):
                        call_kwargs.pop("response_format", None)
                        interaction = client.interactions.create(**call_kwargs)
                    else:
                        raise e_rf

                raw_text = getattr(interaction, "output_text", None) or ""
                duration = time.perf_counter() - t_start

                if raw_text:
                    # Extraer bloque JSON si viene envuelto en markdown
                    clean_json = raw_text.strip()
                    match_obj = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
                    if match_obj:
                        clean_json = match_obj.group(1)
                    else:
                        match_arr = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_text, re.DOTALL)
                        if match_arr:
                            clean_json = match_arr.group(1)

                    parsed = json.loads(clean_json)

                    aligned_list: list[str] = []
                    if isinstance(parsed, dict):
                        for i in range(1, total_count + 1):
                            val = parsed.get(str(i)) or parsed.get(i)
                            if val and isinstance(val, str) and val.strip():
                                aligned_list.append(val.strip())
                            else:
                                aligned_list.append(list_sentences[i - 1])
                    elif isinstance(parsed, list):
                        for i in range(total_count):
                            if i < len(parsed) and isinstance(parsed[i], str) and parsed[i].strip():
                                aligned_list.append(parsed[i].strip())
                            else:
                                aligned_list.append(list_sentences[i])

                    if aligned_list and len(aligned_list) == total_count:
                        print(f"⏱️ [Etapa: Traducción (Gemini)] Completada con '{model}' en {duration:.1f}s ({len(aligned_list)} frases 1-a-1 verificadas)", flush=True)
                        return aligned_list

            except Exception as e:
                last_error = e
                duration = time.perf_counter() - t_start
                err_str = str(e)
                print(f"⚠️ [Traducción] Error en {duration:.1f}s con '{model}' (key {key_tag}): {e}", flush=True)

                # Si el modelo está temporalmente saturado en Google Cloud (503 / high demand), saltar de inmediato al siguiente modelo
                if any(c in err_str for c in ("503", "high demand", "service_unavailable")):
                    print(f"⏩ [Traducción] Modelo '{model}' con alta demanda en Google Cloud. Pasando de inmediato al modelo de respaldo...", flush=True)
                    break

                # Rotación de clave si es error de cuota o límite
                if len(available_keys) > 1 and any(c in err_str for c in ("429", "RESOURCE_EXHAUSTED", "quota")):
                    rotate_google_api_key()
                    continue

        if m_idx + 1 < len(models_to_try):
            print(f"🔄 [Traducción] Saltando a modelo de respaldo: '{models_to_try[m_idx + 1]}'...", flush=True)

    print(f"❌ [Traducción] Fallaron todos los modelos disponibles. Último error: {last_error}", flush=True)
    return None


def generate_tiktok_title(
    youtube_url: Optional[str] = None,
    target_lang: str = "es",
    model_name: Optional[str] = None,
    fallback_text: Optional[str] = None,
    print_full_prompt: bool = False,
) -> str | None:
    """
    Genera un título viral para TikTok con emojis y hashtags.
    Usa exclusivamente el conocimiento del modelo a partir del diálogo transcrito o video.
    """
    available_keys = get_google_api_keys()
    if not available_keys:
        print("⚠️ [Título Viral] No hay ninguna GOOGLE_API_KEY configurada.", flush=True)
        return None

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

IMPORTANTE: Devuelve **solo el título final**, sin explicaciones ni opciones adicionales."""

    if fallback_text and fallback_text.strip():
        call_input = f"{base_prompt}\n\nTranscripción / Diálogos del video:\n{fallback_text.strip()}"
        source_label = "Diálogos / Transcripción"
    else:
        # Entrada multimedia nativa para Interactions API con URI de video de YouTube
        call_input = [
            {
                "type": "text",
                "text": base_prompt,
            },
            {
                "type": "video",
                "mime_type": "video/mp4",
                "uri": youtube_url or "",
            },
        ]
        source_label = f"Video Multimodal YouTube ({youtube_url})"

    if print_full_prompt:
        print("\n" + "=" * 60, flush=True)
        print(f"📄 [PROMPT COMPLETO PARA TÍTULO VIRAL] (Fuente: {source_label}):", flush=True)
        print("-" * 60, flush=True)
        if isinstance(call_input, list):
            import json
            print(json.dumps(call_input, indent=2, ensure_ascii=False), flush=True)
        else:
            print(call_input, flush=True)
        print("=" * 60 + "\n", flush=True)

    models_to_try = [model_name.strip()] if (model_name and model_name.strip()) else [DEFAULT_TITLE_MODEL]
    for m in POPULAR_GEMINI_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    last_error = None

    for m_idx, model in enumerate(models_to_try):
        is_gemma = "gemma" in model.lower()

        keys_to_attempt = list(available_keys)
        for k_idx, key in enumerate(keys_to_attempt):
            key_tag = f"...{key[-4:]}" if len(key) >= 4 else "***"
            client = genai.Client(api_key=key)

            t_start = time.perf_counter()
            try:
                # Si el modelo es Gemma (solo texto) y call_input es lista multimedia, convertir a texto simple
                actual_input = call_input
                if is_gemma and isinstance(call_input, list):
                    actual_input = f"{base_prompt}\n\nURL del video: {youtube_url or ''}"

                call_kwargs = {
                    "model": model,
                    "input": actual_input,
                }

                interaction = client.interactions.create(**call_kwargs)
                raw_title = getattr(interaction, "output_text", None) or ""
                duration = time.perf_counter() - t_start

                if raw_title:
                    title = raw_title.replace("\n", " ").strip("\"'")
                    print(f"⏱️ [Título Viral '{model}'] Generado en {duration:.1f}s: {title}", flush=True)
                    return title

            except Exception as e:
                last_error = e
                err_str = str(e)
                print(f"⚠️ [Título Viral] Error con '{model}' (key {key_tag}): {e}", flush=True)

                if any(c in err_str for c in ("503", "high demand", "service_unavailable")):
                    break

                if len(available_keys) > 1 and any(c in err_str for c in ("429", "RESOURCE_EXHAUSTED", "quota")):
                    rotate_google_api_key()
                    continue

        if m_idx + 1 < len(models_to_try):
            print(f"🔄 [Título Viral] Saltando a modelo de respaldo: '{models_to_try[m_idx + 1]}'...", flush=True)

    print(f"❌ [Título Viral] No se pudo generar el título. Último error: {last_error}", flush=True)
    return None
