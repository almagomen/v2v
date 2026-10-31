from __future__ import annotations

import os
import json
import re
import time
from typing import Any, Callable, Optional, Tuple

from google import genai

from src.config import get_google_api_keys, rotate_google_api_key
from src.entities import (
    ambiguous_terms,
    check_entities,
    collect_known_terms,
    lock_text,
    normalize_asr_casing,
    restore_text,
)
from src.lang_utils import shared_tokens
from src.pacing import budget_for, build_fit_prompt, fit_deviation, needs_rewrite, speech_rate
from src.pronunciation import (
    MAX_TERMS_PER_CALL,
    apply_table,
    build_respelling_prompt,
    consolidate,
    missing_terms,
    norm_key,
    validate_rule,
)

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


def _chunk_size() -> int:
    """Segmentos por llamada al MT. Videos largos se parten para no truncar el JSON."""
    try:
        return max(2, int(os.environ.get("TRANSLATION_CHUNK_SEGMENTS", "80")))
    except ValueError:
        return 80


def _call_model(client, model: str, is_gemma: bool, prompt_text: str) -> str:
    """Una llamada al modelo con JSON estricto y reintento en texto si no lo soporta."""
    call_kwargs = {"model": model, "input": prompt_text}
    if not is_gemma:
        call_kwargs["response_format"] = [{"type": "text", "mime_type": "application/json"}]
    try:
        interaction = client.interactions.create(**call_kwargs)
    except Exception as e_rf:
        err_text = str(e_rf).lower()
        if ("response_format" in err_text or "schema" in err_text) and not any(
            c in err_text for c in ("503", "429", "high demand")
        ):
            print(f"⚠️ [Fallback Traducción] '{model}' no soporta response_format JSON estricto, reintentando en modo texto...", flush=True)
            call_kwargs.pop("response_format", None)
            interaction = client.interactions.create(**call_kwargs)
        else:
            raise
    return getattr(interaction, "output_text", None) or ""


def translate_text_list(
    list_sentences: list[str],
    target_lang: str,
    source_lang: str = "en",
    model_name: Optional[str] = None,
    print_full_prompt: bool = False,
    times: Optional[list[Tuple[float, float]]] = None,
    segments_meta: Optional[list[dict]] = None,
    initial_emotion_per_sentence: bool = False,
    initial_emotion_tag: str = "[excited]",
    return_details: bool = False,
    **kwargs,
) -> list[str] | Tuple[list[str], list[dict]] | None:
    """
    Traduce o adapta una lista de frases a un idioma objetivo usando Gemini (Interactions API).

    - Doblaje isométrico: presupuesto de sílabas/tiempo neto por segmento.
    - Entity lock: nombres técnicos, archivos, rutas y versiones viajan como ⟦E#⟧ y se
      restauran tras verificar que el modelo no los tocó.
    - Chunking: la lista se parte en bloques (TRANSLATION_CHUNK_SEGMENTS, 80 por defecto)
      con 2 frases de contexto previo por bloque. Un bloque inválido se reintenta partido
      a la mitad antes de rotar de clave o de modelo.
    - Cascada de modelos (lite -> gemma) y rotación de API Keys.
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
    fit_enabled = os.environ.get("TRANSLATION_FIT_BUDGET", "1").strip().lower() not in ("0", "false", "no")

    # ─── Entity lock: congelar términos técnicos antes de tocar el prompt ───
    # Las mayúsculas del ASR no distinguen nombres propios de ortografía de pausa:
    # se normalizan antes de bloquear, o el modelo las lee como marcas y no las traduce.
    source_texts = [(s or "") for s in list_sentences]
    known_terms = collect_known_terms(source_texts)
    if not is_same_lang:
        # La estadística deja un grupo dudoso: palabras en mayúscula que nunca aparecen
        # en minúscula. Congelar una palabra corriente mete idioma origen en la salida;
        # no congelar un nombre propio solo lo expone a una mala transcripción. Ante la
        # duda, que decida el modelo, que sí conoce el idioma.
        doubtful = ambiguous_terms(source_texts) & known_terms
        if doubtful:
            try:
                judge_client = genai.Client(api_key=available_keys[0])
                judge_model = (model_name or DEFAULT_TRANSLATION_MODEL).strip()
                judge_gemma = "gemma" in judge_model.lower()
                dropped = _judge_common_words(
                    lambda prompt: _call_model(judge_client, judge_model, judge_gemma, prompt),
                    sorted(doubtful),
                    source_lang_name,
                )
            except Exception as e_judge:
                print(f"⚠️ [Entidades] juicio de palabras omitido ({e_judge})", flush=True)
                dropped = set()
            if dropped:
                known_terms -= dropped
                print(f"🔍 [Entidades] {len(dropped)} palabra(s) corriente(s) descartada(s): {', '.join(sorted(dropped))}", flush=True)

    source_sentences = [normalize_asr_casing(s.strip(), keep=known_terms) for s in source_texts]
    locked_sentences: list[str] = []
    lock_maps: list[dict[int, str]] = []
    for s in source_sentences:
        locked, mapping = lock_text(s, known=known_terms)
        locked_sentences.append(locked)
        lock_maps.append(mapping)
    entity_total = sum(len(m) for m in lock_maps)
    if entity_total:
        locked_segments = sum(1 for m in lock_maps if m)
        print(f"🔒 [Entidades] {entity_total} término(s) protegidos en {locked_segments} segmento(s)", flush=True)

    # ─── Línea de entrada por segmento (prefijo de presupuesto + texto bloqueado) ───
    entry_lines: list[str] = []
    speech_seconds: list[float] = [0.0] * total_count
    for i in range(total_count):
        locked_s = locked_sentences[i]
        if not has_times:
            entry_lines.append(locked_s)
            continue

        start_t, end_t = times[i]
        meta = segments_meta[i] if (segments_meta and i < len(segments_meta)) else {}
        total_dur = max(0.4, round(end_t - start_t, 2))
        internal_pause = float(meta.get("internal_pause_sec", 0.0) or 0.0)
        speech_target_sec = max(0.4, round(total_dur - internal_pause, 2))
        speech_seconds[i] = speech_target_sec

        b = budget_for(target_lang, speech_target_sec)
        entry_lines.append(
            f"[{total_dur:.1f}s slot | ~{b['syl_min']}-{b['syl_max']} sílabas | "
            f"~{b['chars_min']}-{b['chars_max']} chars, apunta a {b['chars_target']}]: {locked_s}"
        )

    chars_per_sec = speech_rate(target_lang)[1]

    pacing_instruction = f"""5. DOBLAJE ISOMÉTRICO (CONTROL DE TIEMPO Y EXTENSIÓN):
   Cada segmento incluye su presupuesto temporal: `[Xs slot | ~A-B sílabas | ~M-Z chars, apunta a T]: texto original`.
   El ritmo medido en doblaje profesional de {target_lang_name} es ~{chars_per_sec:.0f} caracteres por segundo, y ese valor ya está aplicado en el rango.
   - ENCAJE: apunta al valor `apunta a T`; nunca por debajo del mínimo `M`. Por encima de `Z` obliga a acelerar la voz y suena artificial.
   - QUEDARSE CORTO ES EL ERROR MÁS CARO: si el texto no llena el slot, queda silencio muerto entre frases y el sincronizador tiene que arrastrar la voz. Al quedarte corto, agrega matices naturales del habla antes que recortar.
   - RITMO ORAL: Entrega un texto hablado directo, fluido y creíble.
   - SEGMENTOS BREVES (< 2.0s): Respeta la concisión temporal manteniendo la traducción breve y directa sin adiciones innecesarias.
   - En tu JSON de salida entrega ÚNICAMENTE el texto adaptado dentro de cada objeto, SIN repetir el prefijo de metadatos (prohibido poner `[Xs slot | ...]:`).""" if has_times else f"""5. CONCISIÓN TEMPORAL: Mantén una longitud similar a la frase original para no desbordar los tiempos de habla del clip de video. Evita redundancias o explicaciones innecesarias."""

    empty_dict_str = "{}"
    if is_same_lang:
        role_mission = f"""Eres un director de voz y especialista en adaptación prosódica de diálogos para síntesis de voz (TTS).
Tu misión es ADAPTAR cada frase en {target_lang_name} para su locución por modelos de voz (TTS), preservando con total fidelidad el texto, la idea y la intención original del {source_lang_name}, pero dotándola de ritmo oral natural, pausas orgánicas y excelente fonética."""
    else:
        role_mission = f"""Eres un especialista en doblaje audiovisual, transcreación y adaptación de diálogos para síntesis de voz (TTS).
Tu misión es REESCRIBIR cada frase al {target_lang_name}, capturando con total fidelidad la IDEA, la intención, el significado y el tono original del {source_lang_name}, pero adaptándola para que suene 100% natural, fluida y creíble como la expresaría un hablante nativo."""

    # Solo se inyecta cuando hay entidades: no gastar tokens de instrucción en videos sin tecnicismos.
    if entity_total:
        entity_rule = """9. TOKENS PROTEGIDOS (PROHIBIDO TRADUCIR O ALTERAR):
   Las entidades técnicas, nombres de producto, nombres de archivo, rutas, versiones, siglas y cifras aparecen como marcadores opacos ⟦E1⟧, ⟦E2⟧, ... dentro del texto de entrada.
   - Conserva cada marcador EXACTAMENTE igual: mismos caracteres, mismo número, una sola vez y en la misma posición relativa de la frase.
   - No los traduzcas, no los expandas, no los expliques, no los elimines y no inventes marcadores nuevos.
   - No cuentan para el presupuesto de caracteres indicado en el prefijo temporal.
   - Traduce con normalidad el resto de la frase alrededor de los marcadores."""
    else:
        entity_rule = "9. CIFRAS Y NOMBRES: Conserva sin cambios los números, nombres de archivo, rutas, versiones y siglas técnicas que aparezcan en el texto."

    def _build_prompt(entries: dict[str, str], count: int, context: list[str]) -> str:
        ex_text_1 = f"frase 1 adaptada al {target_lang_name}"
        ex_text_2 = f"frase 2 adaptada al {target_lang_name}"

        def _ex(k: int, text: str) -> str:
            return f'  "{k}": {{\n    "text": "{text}",\n    "phonemes": {empty_dict_str}\n  }}'

        # El ejemplo no debe repetir la última clave cuando el bloque es corto
        # (con count=1 se generaban "1", "2" y otra vez "1").
        if count <= 2:
            example_json = ",\n".join(
                _ex(k, ex_text_1 if k == 1 else ex_text_2) for k in range(1, count + 1)
            )
        else:
            example_json = (
                _ex(1, ex_text_1) + ",\n"
                + _ex(2, ex_text_2) + ",\n"
                + "  ...\n"
                + _ex(count, f"frase {count} adaptada al {target_lang_name}")
            )

        contexto = ""
        if context:
            contexto = (
                "\nContexto previo (referencia de ilación: YA fue traducido en el bloque anterior. "
                "NO lo traduzcas, NO lo repitas y NO lo incluyas en tu respuesta):\n"
                f"{json.dumps(context, ensure_ascii=False)}\n"
            )

        return f"""{role_mission}

Directrices obligatorias:
1. REGLA ESTRICTA 1-A-1 E ISOMORFISMO: La entrada contiene EXACTAMENTE {count} frases indexadas con claves numéricas del "1" al "{count}". Tu salida DEBE ser un objeto JSON con EXACTAMENTE las mismas {count} claves numéricas (del "1" al "{count}").
2. INTEGRIDAD TEMPORAL Y SEGMENTOS INDIVIDUALES: Cada clave numérica "N" representa un clip de audio individual fijado en la línea de tiempo del video. No agregues claves nuevas, no omitas claves y no traslades contenido entre claves adyacentes. Cuando un segmento corresponda a unidades mínimas de habla (interjecciones, partículas discursivas o de enlace, afirmaciones breves, muletillas o reacciones espontáneas del hablante), adáptalo de forma concisa y directa en su propia clave "N" respetando su duración temporal, sin intentar rellenar artificialmente ni tomar texto del segmento siguiente. La clave final "{count}" debe corresponder al cierre del bloque.
3. REESCRIBE MANTENIENDO LA IDEA: Preserva la misma idea central y sentido, usando expresiones coloquiales y naturales adecuadas al {target_lang_name}.
4. VOZ HABLADA Y DOBLAJE: El texto será sintetizado por modelos de voz (TTS). La frase debe tener ritmo fonético natural, ser directa y sonar convincente y orgánica al ser escuchada.
{pacing_instruction}
6. COHERENCIA Y CONTINUIDAD ENTRE FRASES: Las frases forman parte de una narración continua en un timeline audiovisual. Si una frase continúa la idea de la clave anterior (o deja una idea abierta para la clave siguiente), preserva la ilación gramatical natural, usando puntuación de enlace (comas o puntos seguidos) para que al reproducirse consecutivamente en el reproductor suenen como un discurso fluido y continuo, sin interrupciones abruptas ni pausas antinaturales.
7. PUNTUACIÓN Y RITMO ORAL:
   - Preserva estrictamente la entonación interrogativa (¿?) y exclamativa (¡!) para una entonación creíble.
   - Emplea comas, dos puntos y puntos seguidos para articular un ritmo oral natural y bien estructurado.
8. DETECCIÓN FONÉTICA Y GLOSARIO DE PRONUNCIACIÓN (TTS):
   Identifica en cada frase cualquier vocablo cuya lectura ortográfica literal en {target_lang_name} pueda ser pronunciada de forma errónea, distorsionada o antinatural por un sintetizador de voz. Evalúa rigurosamente candidatos en cualquier área temática que cumplan con alguno de los siguientes criterios:
   a) Nombres propios, marcas, productos, entidades o topónimos de origen no nativo o grafía singular.
   b) Siglas, acrónimos o combinaciones alfanuméricas que deban pronunciarse con la fonética propia de su disciplina o mediante deletreo.
   c) Extranjerismos, vocablos foráneos o términos especializados que conserven la pronunciación de su idioma de origen y no sigan las reglas ortográficas del {target_lang_name}.
   d) Palabras cuya ortografía estándar en {target_lang_name} resulte propensa a una lectura defectuosa o robótica por modelos de voz.

   Para cada vocablo detectado en la frase:
   - Como clave: la palabra exacta tal como está escrita en tu texto traducido.
   - Como valor: su transcripción fonética legible e intuitiva para un hablante de {target_lang_name}, marcando con tilde la sílaba con mayor fuerza de entonación (acento prosódico) para guiar con precisión la pronunciación de la voz sintética.
   - En tu salida, asocia el diccionario al campo "phonemes": {{"Palabra": "Pronunciación"}}. Si una frase contiene únicamente vocabulario cotidiano estándar de {target_lang_name}, deja "phonemes": {empty_dict_str}.
{entity_rule}
10. MAYÚSCULAS DEL RECONOCIMIENTO DE VOZ (NO SON NOMBRES PROPIOS):
   El texto de entrada viene de un ASR que capitaliza la primera palabra de cada trozo separado por una pausa, aunque sea una palabra corriente. Una mayúscula a mitad de frase NO indica nombre propio: solo los marcadores ⟦E1⟧, ⟦E2⟧... son términos protegidos.
   Traduce TODAS las palabras, incluidas las que aparecen en mayúscula, salvo los marcadores protegidos. Dejar una palabra del {source_lang_name} sin traducir porque venía capitalizada es un error grave.
{contexto}
Texto original ({source_lang_name}) indexado por segmento:
---
{json.dumps(entries, indent=2, ensure_ascii=False)}
---

Devuelve ÚNICAMENTE un objeto JSON válido con exactamente las mismas claves numéricas del "1" al "{count}":
{{
{example_json}
}}"""

    def _normalize_response(
        parsed,
        fallback_texts: list[str],
    ) -> tuple[Optional[list[str]], dict[int, dict[str, str]], set[int]]:
        """Extrae textos y fonemas de la respuesta (dict indexado o lista)."""
        count = len(fallback_texts)
        if isinstance(parsed, dict):
            indexed = True
        elif isinstance(parsed, list):
            indexed = False
        else:
            return None, {}, set()

        texts: list[str] = []
        phonemes: dict[int, dict[str, str]] = {}
        missing: set[int] = set()

        for n in range(count):
            if indexed:
                val = parsed.get(str(n + 1)) or parsed.get(n + 1)
            else:
                val = parsed[n] if n < len(parsed) else ""

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

            # Quitar prefijo en caso fortuito de que el LLM repitiera metadata (ej: "[1.2s slot...]: ")
            clean_val = re.sub(r"^\[[^\]]*(?:slot|sílabas|chars)[^\]]*\]:?\s*", "", txt_raw, flags=re.IGNORECASE).strip()
            if clean_val:
                texts.append(clean_val)
            else:
                texts.append(fallback_texts[n])
                missing.add(n)
            phonemes[n] = seg_phonemes

        return texts, phonemes, missing

    def _run_chunk(
        client,
        model: str,
        is_gemma: bool,
        indices: list[int],
        chunk_no: int,
        chunk_total: int,
    ) -> Optional[dict[int, dict]]:
        """Traduce un bloque. Devuelve {índice_global: payload} o None si la respuesta no sirve."""
        local_entries = {str(n + 1): entry_lines[g] for n, g in enumerate(indices)}
        context = [locked_sentences[g] for g in range(max(0, indices[0] - 2), indices[0])]
        prompt = _build_prompt(local_entries, len(indices), context)

        if print_full_prompt:
            print("\n" + "=" * 60, flush=True)
            print(f"📄 [PROMPT COMPLETO → {model}] bloque {chunk_no}/{chunk_total} ({len(indices)} frases):", flush=True)
            print("-" * 60, flush=True)
            print(prompt, flush=True)
            print("=" * 60 + "\n", flush=True)

        raw_text = _call_model(client, model, is_gemma, prompt)
        if not raw_text:
            return None

        try:
            parsed = _loads_loose(raw_text, f"[Fallback JSON] bloque {chunk_no} '{model}'")
        except Exception as exc:
            print(f"⚠️ [Traducción] bloque {chunk_no}: JSON inválido ({exc})", flush=True)
            return None
        fallback_texts = [list_sentences[g] for g in indices]
        texts, phonemes, missing_local = _normalize_response(parsed, fallback_texts)
        if texts is None:
            return None

        # ─── Verificación de entidades + rescate dentro del bloque ───
        problems: dict[int, list[str]] = {}
        rescue: dict[str, dict[str, str]] = {}
        for n, g in enumerate(indices):
            if n in missing_local or not locked_sentences[g]:
                continue
            verdict = check_entities(locked_sentences[g], texts[n])
            if not verdict["ok"]:
                problems[n] = [str(r) for r in verdict["reasons"]]
                rescue[str(n + 1)] = {"source": locked_sentences[g], "text": texts[n]}

        if rescue:
            print(f"🔁 [Entidades] bloque {chunk_no}: {len(rescue)} segmento(s) con tokens alterados; rescate...", flush=True)
            fixed = _translate_entity_retry(client, model, is_gemma, rescue, target_lang_name)
            for key_str, new_text in fixed.items():
                n = int(key_str) - 1
                if not (0 <= n < len(indices)) or not new_text.strip():
                    continue
                if check_entities(locked_sentences[indices[n]], new_text)["ok"]:
                    texts[n] = new_text.strip()
                    problems.pop(n, None)

        # ─── Idioma de salida: palabras que viajaron sin traducir ───
        # Se detecta por solapamiento léxico con el origen, sin diccionarios: los tokens
        # idénticos en ambos lados son o nombres propios o palabras sin traducir, y solo
        # el modelo sabe cuál de las dos cosas es. La aceptación sí es mecánica: la
        # reescritura solo entra si baja el número de coincidencias.
        untranslated: dict[int, list[str]] = {}
        if not is_same_lang:
            candidates: dict[int, list[str]] = {}
            for n in range(len(indices)):
                if n in missing_local:
                    continue
                g = indices[n]
                shared = shared_tokens(
                    source_sentences[g],
                    restore_text(texts[n], lock_maps[g]),
                    lock_maps[g].values(),
                )
                if shared:
                    candidates[n] = shared

            if candidates:
                vocabulary = sorted({t for shared in candidates.values() for t in shared})
                try:
                    leaks = _judge_leaks(
                        lambda prompt: _call_model(client, model, is_gemma, prompt),
                        vocabulary,
                        source_lang_name,
                        target_lang_name,
                    )
                except Exception as e_leak:
                    print(f"⚠️ [Idioma] bloque {chunk_no}: juicio omitido ({e_leak})", flush=True)
                    leaks = set()

                affected = {
                    n: [t for t in shared if t in leaks]
                    for n, shared in candidates.items()
                    if any(t in leaks for t in shared)
                }
                if affected:
                    print(
                        f"🗣️ [Idioma] bloque {chunk_no}: {len(affected)} segmento(s) con palabras sin traducir; reescribiendo...",
                        flush=True,
                    )
                    payload = {
                        str(n + 1): {
                            "source": locked_sentences[indices[n]],
                            "text": texts[n],
                            "residuo": ", ".join(shared),
                        }
                        for n, shared in affected.items()
                    }
                    try:
                        fixed = _translate_residue_retry(client, model, is_gemma, payload, target_lang_name)
                    except Exception as e_res:
                        print(f"⚠️ [Idioma] bloque {chunk_no}: rescate omitido ({e_res})", flush=True)
                        fixed = {}

                    cleaned = 0
                    for key_str, new_text in fixed.items():
                        n = int(key_str) - 1
                        if not (0 <= n < len(indices)) or not new_text.strip():
                            continue
                        g = indices[n]
                        before = sum(1 for t in candidates[n] if t in leaks)
                        after = sum(
                            1
                            for t in shared_tokens(
                                source_sentences[g],
                                restore_text(new_text, lock_maps[g]),
                                lock_maps[g].values(),
                            )
                            if t in leaks
                        )
                        if after >= before:
                            continue
                        if not check_entities(locked_sentences[g], new_text)["ok"]:
                            continue
                        texts[n] = new_text.strip()
                        problems.pop(n, None)
                        cleaned += 1
                    print(f"🗣️ [Idioma] bloque {chunk_no}: {cleaned}/{len(affected)} limpio(s)", flush=True)
                    for n in affected:
                        g = indices[n]
                        left = [
                            t
                            for t in shared_tokens(
                                source_sentences[g],
                                restore_text(texts[n], lock_maps[g]),
                                lock_maps[g].values(),
                            )
                            if t in leaks
                        ]
                        if left:
                            untranslated[n] = left

        # ─── Encaje temporal: una pasada acotada solo sobre los que no caben ───
        # El prompt ya pide el rango, pero el modelo no lo cumple siempre. Aquí se mide
        # la duración estimada y se reescribe únicamente lo que queda fuera del slot.
        # Un fallo de esta pasada nunca descarta el bloque: el ajuste es mejora, no requisito.
        if fit_enabled and has_times:
            try:
                offenders: dict[str, dict[str, str]] = {}
                for n, g in enumerate(indices):
                    sec = speech_seconds[g]
                    if sec <= 0 or n in missing_local:
                        continue
                    if not needs_rewrite(texts[n], target_lang, sec, lock_maps[g]):
                        continue
                    b = budget_for(target_lang, sec)
                    dev = fit_deviation(texts[n], target_lang, sec, lock_maps[g])
                    offenders[str(n + 1)] = {
                        "texto": texts[n],
                        "objetivo": f"{b['chars_min']}-{b['chars_max']} caracteres",
                        "estado": "largo" if dev > 0 else "corto",
                    }

                if offenders:
                    print(f"⏱️ [Encaje] bloque {chunk_no}: {len(offenders)} segmento(s) fuera de rango; ajustando...", flush=True)
                    fitted = _fit_retry(client, model, is_gemma, offenders, target_lang_name)
                    adjusted = 0
                    for key_str, new_text in fitted.items():
                        n = int(key_str) - 1
                        if not (0 <= n < len(indices)) or not new_text.strip():
                            continue
                        g = indices[n]
                        if not check_entities(locked_sentences[g], new_text)["ok"]:
                            continue
                        old_dev = abs(fit_deviation(texts[n], target_lang, speech_seconds[g], lock_maps[g]))
                        new_dev = abs(fit_deviation(new_text, target_lang, speech_seconds[g], lock_maps[g]))
                        if new_dev < old_dev:
                            texts[n] = new_text.strip()
                            adjusted += 1
                    print(f"⏱️ [Encaje] bloque {chunk_no}: {adjusted}/{len(offenders)} ajustado(s)", flush=True)
            except Exception as e_fit:
                print(f"⚠️ [Encaje] bloque {chunk_no}: ajuste omitido ({e_fit})", flush=True)

        out: dict[int, dict] = {}
        for n, g in enumerate(indices):
            out[g] = {
                "text": restore_text(texts[n], lock_maps[g]),
                "phonemes": phonemes.get(n, {}),
                "missing": n in missing_local,
                "problems": problems.get(n, []),
                "untranslated": untranslated.get(n, []),
            }
        return out

    def _run_indices(
        client,
        model: str,
        is_gemma: bool,
        indices: list[int],
        chunk_no: int,
        chunk_total: int,
        depth: int = 0,
    ) -> Optional[dict[int, dict]]:
        """Intenta el bloque; si la respuesta es inválida, lo parte a la mitad y reintenta."""
        part = _run_chunk(client, model, is_gemma, indices, chunk_no, chunk_total)
        if part is not None:
            return part
        if depth >= 2 or len(indices) < 6:
            return None

        mid = len(indices) // 2
        print(f"🧩 [Traducción] bloque {chunk_no} partido en {mid}+{len(indices) - mid} tras respuesta inválida", flush=True)
        left = _run_indices(client, model, is_gemma, indices[:mid], chunk_no, chunk_total, depth + 1)
        if left is None:
            return None
        right = _run_indices(client, model, is_gemma, indices[mid:], chunk_no, chunk_total, depth + 1)
        if right is None:
            return None
        return {**left, **right}

    # ─── Bloques: 80 segmentos o ~14k chars de prompt por llamada ───
    max_segs = _chunk_size()
    max_chars = 14000
    chunks: list[list[int]] = []
    current: list[int] = []
    current_chars = 0
    for i, line in enumerate(entry_lines):
        if current and (len(current) >= max_segs or current_chars + len(line) > max_chars):
            chunks.append(current)
            current, current_chars = [], 0
        current.append(i)
        current_chars += len(line)
    if current:
        chunks.append(current)

    # Modelos a intentar en orden: el solicitado (o DEFAULT), con fallback a los populares
    models_to_try = [model_name.strip()] if (model_name and model_name.strip()) else [DEFAULT_TRANSLATION_MODEL]
    for m in POPULAR_GEMINI_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    last_error = None

    for model in models_to_try:
        is_gemma = "gemma" in model.lower()

        for key in list(available_keys):
            key_tag = f"...{key[-4:]}" if len(key) >= 4 else "***"

            print(f"🌐 [{source_lang} → {target_lang}] {model} {key_tag} ({total_count} segs / {len(chunks)} bloques)", flush=True)
            t_start = time.perf_counter()

            try:
                client = genai.Client(api_key=key)

                resolved: dict[int, dict] = {}
                for chunk_no, indices in enumerate(chunks, start=1):
                    part = _run_indices(client, model, is_gemma, indices, chunk_no, len(chunks))
                    if part is None:
                        raise RuntimeError(f"bloque {chunk_no}/{len(chunks)} sin JSON utilizable")
                    resolved.update(part)

                aligned_list = [resolved[i]["text"] for i in range(total_count)]
                phonemes_map = {i: resolved[i]["phonemes"] for i in range(total_count)}
                duration = time.perf_counter() - t_start

                # ─── Pronunciación: una regla por palabra y cobertura de las bloqueadas ───
                # Corre antes de la etiqueta de emoción para que la clave case con el
                # texto tal como lo dirá la voz, sin prefijos de control.
                phonemes_map = _finalize_pronunciations(
                    phonemes_map,
                    aligned_list,
                    lock_maps,
                    target_lang,
                    target_lang_name,
                    lambda prompt: _call_model(client, model, is_gemma, prompt),
                )

                # Etiqueta de emoción al frente (después del rescate: el modelo no debe verla)
                if initial_emotion_per_sentence and aligned_list:
                    tag_to_insert = initial_emotion_tag if (initial_emotion_tag and initial_emotion_tag.startswith("[")) else f"[{initial_emotion_tag or 'excited'}]"
                    aligned_list = [f"{tag_to_insert} {t}".strip() for t in aligned_list]

                # Fonemas y estado de traducción por segmento
                if segments_meta and len(segments_meta) == total_count:
                    for idx, meta_item in enumerate(segments_meta):
                        ph = phonemes_map.get(idx) or {}
                        if ph:
                            meta_item["phonemes"] = ph
                        elif "phonemes" not in meta_item:
                            meta_item["phonemes"] = {}

                        info = resolved[idx]
                        if info["missing"]:
                            meta_item["translation_status"] = "fallback"
                            meta_item.pop("entity_fail", None)
                        elif info["problems"]:
                            meta_item["translation_status"] = "entity_fail"
                            meta_item["entity_fail"] = info["problems"]
                        else:
                            meta_item.pop("translation_status", None)
                            meta_item.pop("entity_fail", None)

                        if info["untranslated"]:
                            meta_item["untranslated"] = info["untranslated"]
                        else:
                            meta_item.pop("untranslated", None)

                if entity_total:
                    failed = sum(1 for i in range(total_count) if resolved[i]["problems"])
                    print(f"🔓 [Entidades] {entity_total} restauradas; {failed} segmento(s) con fallo persistente", flush=True)

                print(f"⏱️ [Traducción '{model}'] segs. en {duration:.1f}s", flush=True)
                if return_details:
                    phonemes_list = [phonemes_map.get(i, {}) for i in range(total_count)]
                    return aligned_list, phonemes_list
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

    print(f"❌ [Traducción] Fallaron todos los modelos disponibles. Último error: {last_error}", flush=True)
    if return_details:
        return None, None
    return None


def _finalize_pronunciations(
    phonemes_map: dict[int, dict[str, str]],
    texts: list[str],
    lock_maps: list[dict[int, str]],
    target_lang: str,
    target_lang_name: str,
    call: Callable[[str], str],
) -> dict[int, dict[str, str]]:
    """
    Consolida las reglas del lote y cubre los términos que el traductor no pudo ver.

    El modelo escribe la pronunciación segmento a segmento, sin memoria entre bloques:
    la misma palabra puede salir con dos respellings y el video suena inconsistente.
    Además las entidades bloqueadas viajan como marcadores opacos, así que el
    traductor nunca las ve y no puede escribir su pronunciación — son justo las
    palabras anglosajonas que suenan mal.

    Returns:
        {índice: {clave: respelling}} listo para `pronunciation_dictionary`.
    """
    tables = [phonemes_map.get(i) or {} for i in range(len(texts))]
    chosen, display, conflicts = consolidate(tables, target_lang)

    entity_terms = [term for mapping in lock_maps for term in mapping.values()]
    pending = missing_terms(texts, entity_terms, chosen)
    extra: dict[str, dict] = {}
    for start in range(0, len(pending), MAX_TERMS_PER_CALL):
        batch = pending[start : start + MAX_TERMS_PER_CALL]
        try:
            parsed = _loads_loose(
                call(build_respelling_prompt(batch, target_lang_name)),
                "[Pronunciación] respelling",
            )
        except Exception as exc:
            print(f"⚠️ [Pronunciación] respelling omitido ({exc})", flush=True)
            continue
        if not isinstance(parsed, dict):
            continue
        for term, value in parsed.items():
            if value is None:
                continue
            rule = validate_rule(str(term), str(value), target_lang)
            if rule:
                extra[norm_key(rule["key"])] = rule

    final = {
        i: apply_table(texts[i], tables[i], chosen, display, extra)
        for i in range(len(texts))
    }

    applied = {(key, value) for table in final.values() for key, value in table.items()}
    if applied:
        segments = sum(1 for table in final.values() if table)
        print(
            f"🔤 [Pronunciación] {len(applied)} regla(s) en {segments} segmento(s)",
            flush=True,
        )
        for key, value in sorted(applied):
            print(f"   {key} → {value}", flush=True)
    if conflicts:
        print(f"⚠️ [Pronunciación] {len(conflicts)} palabra(s) con dos respellings; gana el más frecuente:", flush=True)
        for line in conflicts[:10]:
            print(f"   {line}", flush=True)
    return final


def _loads_loose(raw_text: str, log_tag: str = "[JSON]") -> Any:
    """
    Parsea la salida del modelo tolerando bloques markdown y secuencias de escape
    inválidas (rutas de Windows tipo C:\\Program Files o regex sin doble barra).
    """
    clean_json = raw_text.strip()
    match_obj = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if match_obj:
        clean_json = match_obj.group(1)
    else:
        match_arr = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_text, re.DOTALL)
        if match_arr:
            clean_json = match_arr.group(1)

    try:
        return json.loads(clean_json)
    except Exception:
        print(f"⚠️ {log_tag} Reparando secuencias de escape...", flush=True)
        sanitized_json = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', clean_json)
        return json.loads(sanitized_json)


def _call_json_map(client, model: str, is_gemma: bool, prompt: str, log_tag: str) -> dict[str, str]:
    """
    Llamada única al modelo que devuelve {clave_numérica: texto}.

    Comparten esta ruta el rescate de entidades y el ajuste de encaje: mismo formato
    de salida, mismo tratamiento de `response_format` no soportado por Gemma.
    """
    call_kwargs: dict[str, Any] = {"model": model, "input": prompt}
    if not is_gemma:
        call_kwargs["response_format"] = [{"type": "text", "mime_type": "application/json"}]

    try:
        interaction = client.interactions.create(**call_kwargs)
    except Exception as e_rf:
        err_text = str(e_rf).lower()
        if "response_format" in err_text or "schema" in err_text:
            call_kwargs.pop("response_format", None)
            interaction = client.interactions.create(**call_kwargs)
        else:
            raise

    raw_text = getattr(interaction, "output_text", None) or ""
    if not raw_text:
        return {}

    parsed = _loads_loose(raw_text, log_tag)
    fixed: dict[str, str] = {}
    if isinstance(parsed, dict):
        for key, val in parsed.items():
            if isinstance(val, dict):
                text_val = str(val.get("text", "")).strip()
            elif isinstance(val, str):
                text_val = val.strip()
            else:
                text_val = ""
            if str(key).isdigit() and text_val:
                fixed[str(key)] = text_val
    return fixed


def _fit_retry(
    client,
    model: str,
    is_gemma: bool,
    payload: dict[str, dict[str, str]],
    target_lang_name: str,
) -> dict[str, str]:
    """
    Segunda pasada acotada por encaje temporal: reescribe solo los segmentos cuya
    duración estimada no cae en el slot del video. La aceptación la decide quien llama
    (entidades intactas y desviación menor que la original).
    """
    return _call_json_map(client, model, is_gemma, build_fit_prompt(payload, target_lang_name), "[Encaje]")


def _translate_entity_retry(
    client,
    model: str,
    is_gemma: bool,
    payload: dict[str, dict[str, str]],
    target_lang_name: str,
) -> dict[str, str]:
    """
    Segunda pasada acotada: solo los segmentos cuyo texto perdió o alteró tokens
    protegidos. Recibe la fuente bloqueada y la traducción defectuosa para que el
    modelo corrija sin reescribir todo el video.
    """
    prompt = f"""Eres un corrector de traducción para doblaje al {target_lang_name}.

Cada entrada trae `source` (frase con marcadores ⟦E1⟧, ⟦E2⟧... que representan
términos técnicos) y `text` (su traducción, que perdió o alteró algún marcador).

Corrige el campo `text` cumpliendo, sin excepciones:
1. Cada marcador presente en `source` aparece exactamente una vez en el nuevo `text`.
2. Los marcadores conservan su número y su posición relativa en la frase.
3. No traduzcas, expandas, expliques ni elimines marcadores. No inventes marcadores nuevos.
4. Todos los números de `source` (versiones, cantidades) se conservan idénticos.
5. El texto debe seguir siendo una frase natural en {target_lang_name}, de longitud similar.

Entrada:
{json.dumps(payload, indent=2, ensure_ascii=False)}

Devuelve únicamente un JSON con las mismas claves:
{{"1": {{"text": "frase corregida con ⟦E1⟧ intacto"}}}}"""

    return _call_json_map(client, model, is_gemma, prompt, "[Rescate entidades]")


def _judge_common_words(
    call: Callable[[str], str],
    words: list[str],
    source_lang_name: str,
) -> set[str]:
    """
    De una lista de palabras capitalizadas, devuelve las que son habla corriente.

    La estadística del lote no separa un nombre propio de una palabra que el ASR
    capitalizó tras una pausa cuando aparece una sola vez. El modelo sí lo separa,
    porque conoce el idioma. La respuesta se acota a la lista de entrada: cualquier
    palabra inventada se descarta, así que un juicio errático no puede romper el lock.
    """
    if not words:
        return set()

    prompt = f"""Recibes palabras que aparecen en mayúscula en la transcripción automática de un audio en {source_lang_name}.

El reconocimiento de voz capitaliza el inicio de cada trozo separado por una pausa, así que muchas de esas mayúsculas son palabras normales, no nombres propios.

Devuelve SOLO las que son palabras comunes de {source_lang_name} escritas en mayúscula por esa razón: verbos, adverbios, conectores, pronombres, adjetivos y expresiones corrientes.

NO incluyas nombres de personas, marcas, productos, empresas, siglas ni términos técnicos.

Responde únicamente con este JSON:
{{"palabras": ["palabra en minúscula"]}}

Palabras: {", ".join(words)}"""

    raw_text = call(prompt)
    parsed = _loads_loose(raw_text, "[Entidades] juicio de palabras")
    found = parsed.get("palabras") if isinstance(parsed, dict) else None
    if not isinstance(found, list):
        return set()

    reported = {str(item).strip().lower() for item in found}
    return {word for word in words if word.lower() in reported}


def _judge_leaks(
    call: Callable[[str], str],
    words: list[str],
    source_lang_name: str,
    target_lang_name: str,
) -> set[str]:
    """
    De las palabras idénticas en origen y traducción, devuelve las que quedaron sin traducir.

    Es la única forma sin diccionarios de separar una fuga de un cognado: el par
    pt/es comparte tantas formas que ninguna regla mecánica las distingue. El modelo
    juzga y la respuesta se acota a los tokens observados.
    """
    if not words:
        return set()

    prompt = f"""Estas palabras aparecen escritas exactamente igual en el original en {source_lang_name} y en su traducción al {target_lang_name}.

Devuelve SOLO las que siguen escritas en {source_lang_name} y deberían estar traducidas al {target_lang_name}.

NO incluyas las que ya son palabras correctas del {target_lang_name} aunque se escriban igual, ni nombres propios, marcas ni términos técnicos.

Responde únicamente con este JSON:
{{"fugas": ["palabra"]}}

Palabras: {", ".join(words)}"""

    raw_text = call(prompt)
    parsed = _loads_loose(raw_text, "[Idioma] juicio de fugas")
    found = parsed.get("fugas") if isinstance(parsed, dict) else None
    if not isinstance(found, list):
        return set()

    reported = {str(item).strip().lower() for item in found}
    return {word for word in words if word.lower() in reported}


def _translate_residue_retry(
    client,
    model: str,
    is_gemma: bool,
    payload: dict[str, dict[str, str]],
    target_lang_name: str,
) -> dict[str, str]:
    """
    Segunda pasada acotada: solo los segmentos con palabras del idioma origen que el
    modelo confirmó como no traducidas. Es el fallo más audible del pipeline
    (portugués dentro del español) y la entrada ya viene filtrada por `_judge_leaks`.
    """
    prompt = f"""Eres un revisor de doblaje al {target_lang_name}.

Cada entrada trae `source` (frase original), `text` (su traducción) y `residuo` (las
palabras que quedaron SIN traducir). El texto debe quedar íntegramente en {target_lang_name}.

Corrige el campo `text` cumpliendo, sin excepciones:
1. Ninguna palabra de `residuo` puede aparecer: sustitúyela por su equivalente real en {target_lang_name}.
2. No es una traducción literal palabra por palabra: reescribe la frase completa para que suene natural.
3. Conserva exactamente los marcadores ⟦E1⟧, ⟦E2⟧... de `source`, con su número y posición.
4. Conserva todos los números, versiones y nombres de archivo.
5. Mantén una longitud similar: no agregues ni quites información.

Entrada:
{json.dumps(payload, indent=2, ensure_ascii=False)}

Devuelve únicamente un JSON con las mismas claves:
{{"1": {{"text": "frase corregida, sin residuo"}}}}"""

    return _call_json_map(client, model, is_gemma, prompt, "[Rescate idioma]")


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
                    print(f"⏱️ [Título '{model}'] viral en {duration:.1f}s:\n✅ {title}", flush=True)
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

    print(f"❌ [Título Viral] No se pudo generar el título. Último error: {last_error}", flush=True)
    return None


