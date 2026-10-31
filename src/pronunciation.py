"""Reglas de pronunciación para TTS: el valor es un respelling, no un fonema.

Fish Audio sustituye el `value` durante la síntesis, así que lo que se escribe es lo
que suena. Para español y portugués no existe notación de fonemas documentada: el
valor se escribe con la ortografía del idioma destino. Para inglés sí existe (CMU
Arpabet) y ahí el valor se valida contra el inventario cerrado de símbolos.

El problema que resuelve este módulo no es "qué es una entidad", sino la consistencia
y la legalidad del respelling: el modelo traduce segmento a segmento, sin memoria
entre llamadas, y la misma palabra puede salir con dos pronunciaciones distintas.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Optional, Sequence

# Inventario cerrado de CMU Arpabet: 39 símbolos, con dígito de acento opcional.
ARPABET = frozenset(
    "AA AE AH AO AW AY B CH D DH EH ER EY F G HH IH IY JH K L M N NG OW OY "
    "P R S SH T TH UH UW V W Y Z ZH".split()
)

# Dígrafos que una ortografía romance no posee. Si el valor los trae, el TTS los lee
# letra por letra y la regla suena peor que la palabra original. No es una lista de
# palabras: es el conjunto de grafemas ausentes en el idioma destino.
FOREIGN_DIGRAPHS = ("th", "sh", "ck", "ph", "wh", "oo", "ee")

# Respuelling legible: letras romance, espacio y guion de sílaba.
_RESPELL_RE = re.compile(
    r"^[a-záéíóúüñçãõâêôà]+(?:[ -][a-záéíóúüñçãõâêôà]+)*$",
    re.IGNORECASE,
)
_ARPABET_RE = re.compile(r"^([A-Z]{1,2})([012])?$")

MAX_KEY_CHARS = 256
MAX_VALUE_CHARS = 1024
MAX_RULES_PER_SEGMENT = 32
MAX_TERMS_PER_CALL = 40


def _primary(lang: str) -> str:
    return (lang or "").strip().lower().replace("_", "-").split("-")[0]


def norm_key(key: str) -> str:
    return str(key or "").strip().lower()


def _is_arpabet(value: str) -> bool:
    tokens = value.split()
    if not tokens:
        return False
    for token in tokens:
        match = _ARPABET_RE.fullmatch(token)
        if not match or match.group(1) not in ARPABET:
            return False
    return True


def validate_rule(key: str, value: str, lang: str) -> Optional[dict]:
    """
    Devuelve la regla lista para Fish Audio, o None si no aporta nada legible.

    El valor se lee como texto, así que la validación es ortográfica: caracteres que
    el idioma destino no posee, dígrafos extranjeros, valores que reproducen la propia
    clave y valores fuera de límite. Una regla inválida no falla en la API: se ignora
    en silencio, así que descartarla aquí es la única forma de saber qué se aplicó.
    """
    k = str(key or "").strip()
    v = str(value or "").strip()
    if not k or not v:
        return None
    if len(k) > MAX_KEY_CHARS or len(v) > MAX_VALUE_CHARS:
        return None
    if any(marker in k or marker in v for marker in ("<|", "⟦", "⟧")):
        return None

    case_sensitive = k.isupper() and len(k) > 1
    if _primary(lang) == "en":
        if not _is_arpabet(v):
            return None
        return {"key": k, "value": " ".join(v.split()), "case_sensitive": case_sensitive}

    if not _RESPELL_RE.fullmatch(v):
        return None
    if any(digraph in v.lower() for digraph in FOREIGN_DIGRAPHS):
        return None
    # Un valor idéntico a la clave no cambia la síntesis: solo agrega superficie de fallo.
    if v.lower().replace("-", "").replace(" ", "") == k.lower().replace(" ", ""):
        return None
    return {"key": k, "value": v, "case_sensitive": case_sensitive}


def consolidate(
    tables: Sequence[dict[str, str]],
    lang: str,
) -> tuple[dict[str, dict], dict[str, str], list[str]]:
    """
    Una sola regla por clave para todo el lote, con el valor más votado.

    El modelo escribe la pronunciación segmento a segmento y sin memoria entre
    bloques, así que la misma palabra puede salir con dos respellings y el video
    suena inconsistente. Los empates se resuelven por la primera aparición.

    Returns:
        (reglas por clave normalizada, nombre visible por clave, conflictos)
    """
    votes: dict[str, Counter] = defaultdict(Counter)
    display: dict[str, str] = {}
    order: list[str] = []

    for table in tables:
        for key, value in (table or {}).items():
            rule = validate_rule(key, value, lang)
            if not rule:
                continue
            norm = norm_key(rule["key"])
            if norm not in display:
                display[norm] = rule["key"]
                order.append(norm)
            votes[norm][rule["value"]] += 1

    chosen: dict[str, dict] = {}
    conflicts: list[str] = []
    for norm in order:
        ranked = votes[norm].most_common()
        value = ranked[0][0]
        chosen[norm] = validate_rule(display[norm], value, lang)
        if len(ranked) > 1:
            conflicts.append(
                f"{display[norm]}: " + " / ".join(f"{v} x{c}" for v, c in ranked)
            )
    return chosen, display, conflicts


def apply_table(
    text: str,
    table: dict[str, str],
    chosen: dict[str, dict],
    display: dict[str, str],
    extra: Optional[dict[str, dict]] = None,
) -> dict[str, str]:
    """
    Reglas que se aplican a un segmento concreto, en el formato `{clave: valor}`.

    Solo entran las claves que aparecen literalmente en el texto final: una regla
    cuya clave no está en el guion nunca dispara y solo ocupa cupo.
    """
    lowered = (text or "").lower()
    result: dict[str, str] = {}
    seen: set[str] = set()
    for raw_key in table or {}:
        norm = norm_key(raw_key)
        if norm in chosen and norm not in seen and display.get(norm, "").lower() in lowered:
            result[display[norm]] = chosen[norm]["value"]
            seen.add(norm)
    for norm, rule in (extra or {}).items():
        if norm in seen or not rule:
            continue
        if rule["key"].lower() in lowered:
            result.setdefault(rule["key"], rule["value"])
            seen.add(norm)
    if len(result) > MAX_RULES_PER_SEGMENT:
        return dict(list(result.items())[:MAX_RULES_PER_SEGMENT])
    return result


def missing_terms(
    texts: Sequence[str],
    entity_terms: Sequence[str],
    chosen: dict[str, dict],
) -> list[str]:
    """
    Términos que aparecen en el guion, necesitan pronunciación y no tienen regla.

    Las entidades bloqueadas viajan como marcadores opacos: el modelo traductor nunca
    las ve, así que no puede escribir su pronunciación. Son justo las palabras que más
    la necesitan.
    """
    known = {norm_key(rule["key"]) for rule in chosen.values() if rule}
    seen: list[str] = []
    seen_norms: set[str] = set()
    for term in entity_terms:
        clean = str(term or "").strip()
        norm = norm_key(clean)
        if not clean or norm in known or norm in seen_norms:
            continue
        if len(clean) < 2 or not any(ch.isalpha() for ch in clean):
            continue
        if any(clean.lower() in (t or "").lower() for t in texts):
            seen.append(clean)
            seen_norms.add(norm)
    return seen


def build_respelling_prompt(terms: Sequence[str], target_lang_name: str) -> str:
    """Prompt de respelling para los términos que el traductor no puede ver."""
    return f"""Eres director de doblaje y especialista en pronunciación de {target_lang_name}.

Recibes términos del guion que el modelo de voz puede leer mal. Para cada uno escribe cómo debe sonar en {target_lang_name}, usando la ortografía de {target_lang_name}.

Convenciones obligatorias:
- Términos de otra lengua, sobre todo anglosajones: escribe la lectura adaptada a {target_lang_name}, no la ortografía original. 'Windows' -> 'guindous', 'Cursor' -> 'cúrsor', 'OpenCode' -> 'open-coud'.
- Siglas y acrónimos en mayúscula: deletreados con los nombres de letra de {target_lang_name}, separados por guiones. 'API' -> 'a-pe-i', 'JDK' -> 'jota-de-ka', 'MCP' -> 'eme-ce-pe'.
- Marca la sílaba tónica con una sola tilde.
- Usa únicamente letras de {target_lang_name}, espacio y guion. Prohibido usar th, sh, ck, ph, wh, oo, ee.
- Si el término ya se lee correctamente tal como está escrito, devuelve null para ese término.

Responde únicamente con este JSON:
{{"Término": "respelling", "Otro": null}}

Términos: {json.dumps(list(terms), ensure_ascii=False)}"""
