from __future__ import annotations

import os
import json
import re
import time
from typing import Optional, Tuple

from google import genai

from src.config import get_google_api_keys, rotate_google_api_key
from src.diarization import count_syllables_approx

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
    times: Optional[list[Tuple[float, float]]] = None,
    segments_meta: Optional[list[dict]] = None,
    enable_emotions: bool = True,
) -> list[str] | None:
    """
    Traduce o adapta una lista de frases a un idioma objetivo usando Gemini (Interactions API).
    Soporta doblaje isométrico con presupuesto de sílabas, tiempo neto y tags prosódicos,
    cascada limpia de modelos (lite -> gemma), control de enable_emotions y rotación de API Keys.
    """
    if not list_sentences:
        return []

    available_keys = get_google_api_keys()
    if not available_keys:
        print("❌ [Traducción] Error: No hay ninguna API Key de Google configurada.", flush=True)
        return None

    source_lang_name = LANGUAGE_NAMES.get(source_lang, "español")
    target_lang_name = LANGUAGE_NAMES.get(target_lang, "español")
    is_same_lang = (source_lang.strip().lower() == target_lang.strip().lower())

    total_count = len(list_sentences)
    has_times = bool(times and len(times) == total_count)

    input_dict = {}
    for i, s in enumerate(list_sentences):
        k = str(i + 1)
        if has_times:
            start_t, end_t = times[i]
            meta = segments_meta[i] if (segments_meta and i < len(segments_meta)) else {}
            total_dur = max(0.4, round(end_t - start_t, 2))
            net_dur = float(meta.get("net_speech_duration") or total_dur)
            orig_syl = int(meta.get("syllable_count") or count_syllables_approx(s))
            orig_chars = len(s)
            long_breaks_count = s.count("[long-break]")
            short_breaks_count = max(0, s.count("[break]") - long_breaks_count)

            # En síntesis de voz: cada [break] consume ~0.35s y cada [long-break] consume ~0.85s de respiro.
            # El tiempo de locución objetivo debe cubrir armónicamente el espacio del clip.
            speech_target_sec = max(0.4, total_dur - (short_breaks_count * 0.35) - (long_breaks_count * 0.85))

            # Tasa natural de locución en doblaje español: ~5.0 a 5.6 sílabas/s y ~15.0 a 17.5 chars/s
            target_chars = int(round(max(orig_chars * 0.95, speech_target_sec * 15.5)))
            min_chars = max(4, int(round(target_chars * 0.85)))
            max_chars = max(min_chars + 8, int(round(target_chars * 1.15)))

            target_syl = int(round(max(orig_syl * 0.95, speech_target_sec * 5.0)))
            min_syl = max(1, int(round(target_syl * 0.85)))
            max_syl = max(min_syl + 2, int(round(speech_target_sec * 5.8)))

            acoustic_hint = meta.get("acoustic_hint", "tono natural")
            input_dict[k] = f"[{total_dur:.1f}s slot | ~{min_syl}-{max_syl} sílabas | ~{min_chars}-{max_chars} chars | {acoustic_hint}]: {s}"
        else:
            input_dict[k] = s

    if enable_emotions:
        from src.expression import CANONICAL_FISH_EMOTIONS
        active_emotions = sorted([e for e in CANONICAL_FISH_EMOTIONS if not ("break" in e or "laughing" in e and "crowd" in e)])
        emotions_catalog_str = ", ".join(f"[{e}]" for e in active_emotions)
        emotion_guideline = f"""   - Modulación prosódica y expresiones: Puedes integrar marcadores de emoción, estilo o reacciones vocales seleccionados del catálogo canónico activo del sistema:
     {emotions_catalog_str}
     * Ubicación flexible: Colócalos ya sea al inicio de la frase para definir la entonación general o en cualquier punto natural de la frase donde ocurra la inflexión emocional.
     * Tono neutro: Si el tono de la frase es neutro, informativo o puramente descriptivo, déjala limpia sin ninguna etiqueta de emoción (no fuerces "calm" ni etiquetas artificiales)."""
        pacing_emotion_hint = "- MODULACIÓN PROSÓDICA DINÁMICA: Considera la pista acústica (nivel de energía y ritmo) provista en el segmento para integrar armónicamente, al inicio o en el punto de inflexión de la frase y solo si el contexto lo justifica, una modulación del catálogo de estilos activos disponible."
    else:
        emotion_guideline = """   - Modulación: Mantén una entonación natural y neutra, sin marcadores de emoción."""
        pacing_emotion_hint = "- MODULACIÓN: Entrega la locución con entonación neutra y natural."

    pacing_instruction = f"""5. DOBLAJE ISOMÉTRICO (CONTROL DE TIEMPO Y RANGO DE CARACTERES):
   Cada segmento incluye su presupuesto temporal: `[Xs slot | ~A-B sílabas | ~M-Z chars | pista acústica]: texto original`.
   En doblaje audiovisual profesional, el ritmo debe ser fluido y natural (~15 a 17 caracteres por segundo).
   - ISOMORFISMO DE LONGITUD: Ajusta la extensión de tu traducción en {target_lang_name} para que caiga DENTRO del rango de ~M-Z chars (proporcional al tiempo del video). No hagas la frase excesivamente corta (dejaría silencios muertos) ni excesivamente larga (se aceleraría la voz).
   - PRESERVACIÓN Y MANEJO DE PAUSAS: Si la escena contiene silencios naturales o respiraciones, puedes usar marcadores de pausa:
     * `[break]`: para pausas breves, respiros naturales y cesuras lógicas entre dos oraciones o cláusulas.
     * `[long-break]`: para pausas prolongadas, transiciones de plano o silencios deliberados.
     (Nunca ubiques marcadores de pausa al inicio o al final absoluto de una frase).
   {pacing_emotion_hint}
   - SEGMENTOS BREVES (< 2.0s): Respeta la concisión temporal manteniendo la traducción breve y directa sin adiciones innecesarias.
   - En tu JSON de salida entrega ÚNICAMENTE el texto adaptado dentro de cada objeto, SIN repetir el prefijo de metadatos (prohibido poner `[Xs slot | ...]:`).""" if has_times else f"""5. CONCISIÓN TEMPORAL: Mantén una longitud similar a la frase original para no desbordar los tiempos de habla del clip de video. Evita redundancias o explicaciones innecesarias."""

    empty_dict_str = "{}"
    if is_same_lang:
        role_mission = f"""Eres un director de voz y especialista en adaptación prosódica de diálogos para síntesis de voz (TTS).
Tu misión es ADAPTAR cada frase en {target_lang_name} para su locución por modelos de voz (TTS), preservando con total fidelidad el texto, la idea y la intención original del {source_lang_name}, pero dotándola de ritmo oral natural, pausas orgánicas y modulaciones vocales adecuadas."""
    else:
        role_mission = f"""Eres un especialista en doblaje audiovisual, transcreación y adaptación de diálogos para síntesis de voz (TTS).
Tu misión es REESCRIBIR cada frase al {target_lang_name}, capturando con total fidelidad la IDEA, la intención, el significado y el tono original del {source_lang_name}, pero adaptándola para que suene 100% natural, fluida y creíble como la expresaría un hablante nativo."""

    prompt = f"""{role_mission}

Directrices obligatorias:
1. REGLA ESTRICTA 1-A-1 E ISOMORFISMO: La entrada contiene EXACTAMENTE {total_count} frases indexadas con claves numéricas del "1" al "{total_count}". Tu salida DEBE ser un objeto JSON con EXACTAMENTE las mismas {total_count} claves numéricas (del "1" al "{total_count}").
2. INTEGRIDAD TEMPORAL Y SEGMENTOS INDIVIDUALES: Cada clave numérica "N" representa un clip de audio individual fijado en la línea de tiempo del video. No agregues claves nuevas, no omitas claves y no traslades contenido entre claves adyacentes. Cuando un segmento corresponda a unidades mínimas de habla (interjecciones, partículas discursivas o de enlace, afirmaciones breves, muletillas o reacciones espontáneas del hablante), adáptalo de forma concisa y directa en su propia clave "N" respetando su duración temporal, sin intentar rellenar artificialmente ni tomar texto del segmento siguiente. La clave final "{total_count}" debe corresponder al cierre del video.
3. REESCRIBE MANTENIENDO LA IDEA: Preserva la misma idea central y sentido, usando expresiones coloquiales y naturales adecuadas al {target_lang_name}.
4. VOZ HABLADA Y DOBLAJE: El texto será sintetizado por modelos de voz (TTS). La frase debe tener ritmo fonético natural, ser directa y sonar convincente y orgánica al ser escuchada.
{pacing_instruction}
6. COHERENCIA Y CONTINUIDAD ENTRE FRASES: Las frases forman parte de una narración continua en un timeline audiovisual. Si una frase continúa la idea de la clave anterior (o deja una idea abierta para la clave siguiente), preserva la ilación gramatical natural, usando puntuación de enlace (comas o puntos seguidos) para que al reproducirse consecutivamente en el reproductor suenen como un discurso fluido y continuo, sin interrupciones abruptas ni pausas antinaturales.
7. MODULACIÓN PROSÓDICA, ÉNFASIS Y PAUSAS:
{emotion_guideline}
   - Control de pausas internas:
     * `[break]`: para pausas breves, respiros naturales y cesuras lógicas entre dos oraciones o cláusulas.
     * `[long-break]`: para silencios prolongados deliberados, momentos de reflexión o transiciones de escena.
     * Nunca coloques marcadores de pausa al inicio ni al final absoluto de una frase.
   - Puedes anteponer `[emphasis]` inmediatamente antes de una palabra clave para acentuarla con fuerza vocal.
   - Preserva estrictamente la entonación interrogativa (¿?) y exclamativa (¡!) para una modulación prosódica creíble.
8. DETECCIÓN FONÉTICA Y GLOSARIO DE PRONUNCIACIÓN (TTS):
   Identifica en cada frase cualquier vocablo cuya lectura ortográfica literal en {target_lang_name} pueda ser pronunciada de forma errónea, distorsionada o antinatural por un sintetizador de voz. Evalúa rigurosamente candidatos en cualquier área temática (ciencia, tecnología, medicina, finanzas, arte, deportes, leyes, cultura general, etc.) que cumplan con alguno de los siguientes criterios:
   a) Nombres propios, marcas, productos, entidades o topónimos de origen no nativo o grafía singular.
   b) Siglas, acrónimos o combinaciones alfanuméricas que deban pronunciarse con la fonética propia de su disciplina o mediante deletreo.
   c) Extranjerismos, vocablos foráneos o términos especializados que conserven la pronunciación de su idioma de origen y no sigan las reglas ortográficas del {target_lang_name}.
   d) Palabras cuya ortografía estándar en {target_lang_name} resulte propensa a una lectura defectuosa o robótica por modelos de voz.

   Para cada vocablo detectado en la frase:
   - Como clave: la palabra exacta tal como está escrita en tu texto traducido.
   - Como valor: su transcripción fonética legible e intuitiva para un hablante de {target_lang_name}, marcando con tilde la sílaba con mayor fuerza de entonación (acento prosódico) para guiar con precisión la pronunciación de la voz sintética.
   - En tu salida, asocia el diccionario al campo "phonemes": {{"Palabra": "Pronunciación"}}. Si una frase contiene únicamente vocabulario cotidiano estándar de {target_lang_name}, deja "phonemes": {empty_dict_str}.

Texto original ({source_lang_name}) indexado por segmento:
---
{json.dumps(input_dict, indent=2, ensure_ascii=False)}
---

Devuelve ÚNICAMENTE un objeto JSON válido con exactamente las mismas claves numéricas del "1" al "{total_count}":
{{
  "1": {{
    "text": "frase 1 adaptada al {target_lang_name}",
    "phonemes": {empty_dict_str}
  }},
  "2": {{
    "text": "frase 2 adaptada al {target_lang_name}",
    "phonemes": {empty_dict_str}
  }},
  ...
  "{total_count}": {{
    "text": "frase {total_count} adaptada al {target_lang_name}",
    "phonemes": {empty_dict_str}
  }}
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

                    try:
                        parsed = json.loads(clean_json)
                    except (json.JSONDecodeError, Exception):
                        # Reparar secuencias de escape inválidas (comunes en rutas de Windows como C:\Program Files\... o regex)
                        sanitized_json = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', clean_json)
                        parsed = json.loads(sanitized_json)

                    aligned_list: list[str] = []
                    phonemes_map: dict[int, dict[str, str]] = {}

                    if isinstance(parsed, dict):
                        for i in range(1, total_count + 1):
                            val = parsed.get(str(i)) or parsed.get(i)
                            txt_raw = ""
                            seg_phonemes: dict[str, str] = {}

                            if isinstance(val, dict):
                                txt_raw = str(val.get("text", "")).strip()
                                ph = val.get("phonemes")
                                if isinstance(ph, dict):
                                    seg_phonemes = {str(k).strip(): str(v).strip() for k, v in ph.items() if k and v}
                            elif isinstance(val, list):
                                txt_raw = str(val[0]).strip() if len(val) > 0 else ""
                                if len(val) > 1 and isinstance(val[1], dict):
                                    seg_phonemes = {str(k).strip(): str(v).strip() for k, v in val[1].items() if k and v}
                            elif isinstance(val, str):
                                txt_raw = val.strip()

                            if txt_raw:
                                clean_val = re.sub(r"^\[[^\]]*(?:\||habla|sílabas|palabras|chars)[^\]]*\]:?\s*", "", txt_raw, flags=re.IGNORECASE).strip()
                                clean_val = re.sub(r"^\[[^\]]+\]:\s*", "", clean_val).strip()
                                aligned_list.append(clean_val if clean_val else list_sentences[i - 1])
                            else:
                                aligned_list.append(list_sentences[i - 1])

                            phonemes_map[i - 1] = seg_phonemes

                    elif isinstance(parsed, list):
                        for i in range(total_count):
                            val = parsed[i] if i < len(parsed) else ""
                            txt_raw = ""
                            seg_phonemes = {}
                            if isinstance(val, dict):
                                txt_raw = str(val.get("text", "")).strip()
                                ph = val.get("phonemes")
                                if isinstance(ph, dict):
                                    seg_phonemes = {str(k).strip(): str(v).strip() for k, v in ph.items() if k and v}
                            elif isinstance(val, list):
                                txt_raw = str(val[0]).strip() if len(val) > 0 else ""
                                if len(val) > 1 and isinstance(val[1], dict):
                                    seg_phonemes = {str(k).strip(): str(v).strip() for k, v in val[1].items() if k and v}
                            elif isinstance(val, str):
                                txt_raw = val.strip()

                            if txt_raw:
                                clean_val = re.sub(r"^\[[^\]]*(?:\||habla|sílabas|palabras|chars)[^\]]*\]:?\s*", "", txt_raw, flags=re.IGNORECASE).strip()
                                clean_val = re.sub(r"^\[[^\]]+\]:\s*", "", clean_val).strip()
                                aligned_list.append(clean_val if clean_val else list_sentences[i])
                            else:
                                aligned_list.append(list_sentences[i])

                            phonemes_map[i] = seg_phonemes

                    # Inyectar fonemas detectados en segments_meta si está provisto
                    if segments_meta and len(segments_meta) == total_count:
                        for idx, meta_item in enumerate(segments_meta):
                            if idx in phonemes_map and phonemes_map[idx]:
                                meta_item["phonemes"] = phonemes_map[idx]
                            elif "phonemes" not in meta_item:
                                meta_item["phonemes"] = {}


                    if aligned_list and len(aligned_list) == total_count:
                        print(f"⏱️ [Etapa: Traducción | Gemini] Completada con '{model}' en {duration:.1f}s ({len(aligned_list)} frases)", flush=True)
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


def auto_heal_short_segments(
    underflow_segments: list[dict],
    target_lang: str = "es",
    source_lang: str = "en",
    model_name: Optional[str] = None,
) -> dict[int, str]:
    """
    Auto-healer selectivo: Re-expande únicamente aquellos segmentos donde la síntesis TTS
    duró significativamente menos que el video (< 0.65x), agregando conectores y riqueza
    explicativa para cubrir el tiempo objetivo sin silencios muertos.
    Retorna: {seg_idx: nuevo_texto_expandido}
    """
    if not underflow_segments:
        return {}

    available_keys = get_google_api_keys()
    if not available_keys:
        return {}

    target_lang_name = LANGUAGE_NAMES.get(target_lang, "español")
    source_lang_name = LANGUAGE_NAMES.get(source_lang, "español")

    input_dict = {}
    for item in underflow_segments:
        idx = item["idx"]
        dur_target = item["dur_en"]
        dur_actual = item["dur_es"]
        needed_chars = int(round(dur_target * 16.0))
        cur_text = item["text_dict"].get("text", "")
        input_dict[str(idx + 1)] = {
            "texto_actual": cur_text,
            "segundos_actuales": round(dur_actual, 2),
            "segundos_objetivo": round(dur_target, 2),
            "caracteres_necesarios": f"~{needed_chars} chars",
        }

    prompt = f"""Eres un especialista en doblaje audiovisual y adaptación de guiones para TTS.
Las siguientes frases dobladas al {target_lang_name} fueron sintetizadas por voz, pero se pronunciaron demasiado rápido y dejaron un vacío de silencio antinatural respecto a la escena original del video.

Tu misión es REESCRIBIR Y EXPANDIR cada frase en {target_lang_name} preservando la MISMA idea central, intención y tono original del {source_lang_name}, pero con mayor desarrollo explicativo, naturalidad oral y conectores fluidos para aproximarse al número de caracteres objetivo (~Z chars), llenando el tiempo de forma armoniosa.

Directrices:
1. Mantén la numeración idéntica en el JSON de salida.
2. Si la frase original contiene marcadores prosódicos o de emoción entre corchetes, consérvalos o adáptalos coherentemente.
3. Si la frase extendida requiere pausas naturales de respiración o cambio de ritmo, puedes emplear [break] para pausas breves o [long-break] para pausas más extensas (nunca al inicio ni al final absoluto).
4. Devuelve ÚNICAMENTE un JSON con las claves numéricas y el nuevo texto expandido.

Entrada:
---
{json.dumps(input_dict, indent=2, ensure_ascii=False)}
---

Devuelve ÚNICAMENTE:
{{
  "clave": "nueva frase expandida en {target_lang_name}"
}}"""

    model = model_name.strip() if (model_name and model_name.strip()) else DEFAULT_TRANSLATION_MODEL
    try:
        client = genai.Client(api_key=available_keys[0])
        interaction = client.interactions.create(
            model=model,
            input=prompt,
            response_format=[{"type": "text", "mime_type": "application/json"}],
        )
        raw_text = getattr(interaction, "output_text", None) or ""
        if raw_text:
            clean_json = raw_text.strip()
            match_obj = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
            if match_obj:
                clean_json = match_obj.group(1)

            try:
                parsed = json.loads(clean_json)
            except Exception:
                sanitized = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', clean_json)
                parsed = json.loads(sanitized)

            healed_texts: dict[int, str] = {}
            for item in underflow_segments:
                idx = item["idx"]
                k = str(idx + 1)
                val = parsed.get(k) or parsed.get(idx + 1)
                if val and isinstance(val, str) and val.strip():
                    clean_val = re.sub(r"^\[[^\]]*(?:\||chars|slot)[^\]]*\]:?\s*", "", val).strip()
                    healed_texts[idx] = clean_val
            return healed_texts
    except Exception as e:
        print(f"⚠️ [Auto-Heal] Error en re-expansión selectiva: {e}", flush=True)

    return {}

