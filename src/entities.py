"""Detección y bloqueo de entidades para la traducción, sin diccionarios.

Qué es un nombre propio se decide por dos señales que no dependen del idioma:

- **Estructura del token**: rutas, URLs, nombres de archivo, versiones, camelCase,
  PascalCase y siglas. Esas formas no existen en el habla corriente de ningún idioma.
- **Estadística del propio lote**: un término que el ASR escribe alguna vez en
  minúscula es una palabra corriente capitalizada por la pausa, no una marca.

Una lista de excepciones nunca cubriría todos los idiomas de origen ni todas las
palabras que el ASR capitaliza, así que aquí no hay ninguna.
"""

import re
from collections import Counter
from typing import Iterable, Sequence

PLACEHOLDER_TMPL = "⟦E{}⟧"
PLACEHOLDER_RE = re.compile(r"⟦\s*E\s*(\d+)\s*⟧")

# Extensiones que delatan un nombre de archivo dentro de una frase hablada.
_FILE_EXT = (
    "ps1|py|pyc|exe|dll|sh|bat|cmd|json|ya?ml|toml|md|txt|cfg|ini|log|"
    "zip|tar|gz|7z|ipynb|js|mjs|cjs|ts|tsx|jsx|cpp|cc|hpp|h|cs|rs|go|java|"
    "apk|iso|bin|elf|hex|asm|vtt|srt|mp4|mkv|wav|mp3|m4a"
)

# Patrón → nombre de categoría (solo para diagnóstico/logs).
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"```.*?```", re.DOTALL), "code"),
    (re.compile(r"`[^`\n]+`"), "code"),
    (re.compile(r"https?://\S+"), "url"),
    (re.compile(r"\b[A-Za-z]:\\[^\s,;]+"), "path"),
    (re.compile(rf"\b[\w\-]+\.(?:{_FILE_EXT})\b", re.IGNORECASE), "file"),
    (re.compile(r"\b\d+\.\d+(?:\.\d+)*\b"), "version"),
    (re.compile(r"\b[A-Z][a-z]{1,}[A-Z][A-Za-z0-9]*\b"), "pascal"),
    (re.compile(r"\b[a-z]+[A-Z][A-Za-z0-9]*\b"), "camel"),
    (re.compile(r"\b[A-Z][A-Z0-9]{1,7}\b"), "caps"),
    (re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}\b"), "proper"),
]

# Categorías que se bloquean siempre: su forma no existe en el habla corriente.
_STRUCTURAL_KINDS = frozenset({"code", "url", "path", "file", "version", "pascal", "camel"})

# Categorías que dependen de que la mayúscula signifique algo en el idioma de origen.
_CASE_KINDS = frozenset({"caps", "proper"})

_SENTENCE_END_CHARS = ".!?:;\n\"'«»-—"
_WORD_RE = re.compile(r"[^\W\d_][\w'-]*", re.UNICODE)

# Una palabra de menos de 3 letras coincide demasiadas veces con artículos y
# preposiciones como para que la estadística diga algo.
_MIN_TOKEN_LEN = 3


def _is_sentence_start(text: str, pos: int) -> bool:
    """True si `pos` abre oración (inicio de texto o tras puntuación fuerte)."""
    prefix = text[:pos].rstrip()
    if not prefix:
        return True
    if prefix[-1] not in _SENTENCE_END_CHARS:
        return False
    # `12.1` o `U.S.` no abren oración: si el carácter previo es un dígito o una
    # inicial, seguimos dentro del mismo token.
    return not (len(prefix) >= 2 and (prefix[-2].isalnum() or prefix[-2] == "."))


def _find_spans(text: str, lock_sentence_start: bool) -> list[tuple[int, int, str]]:
    """
    Devuelve spans (start, end, categoría) sin solapar, del más específico al más
    genérico. `lock_sentence_start=False` descarta nombres propios que abren
    oración (ahí la mayúscula es ortografía, no entidad).
    """
    found: list[tuple[int, int, str]] = []
    for pattern, kind in _PATTERNS:
        for m in pattern.finditer(text):
            s, e = m.span()
            token = m.group(0)
            if kind == "caps" and not token.isupper():
                continue
            if kind == "proper" and not lock_sentence_start and _is_sentence_start(text, s):
                continue
            found.append((s, e, kind))

    found.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    accepted: list[tuple[int, int, str]] = []
    last_end = -1
    for s, e, kind in found:
        if s < last_end:
            continue
        accepted.append((s, e, kind))
        last_end = e

    return accepted


def _lowercase_counts(sentences: Sequence[str]) -> Counter[str]:
    """Cuántas veces aparece cada palabra escrita en minúscula en todo el lote."""
    counts: Counter[str] = Counter()
    for text in sentences:
        for m in _WORD_RE.finditer(text or ""):
            word = m.group(0)
            if word == word.lower():
                counts[word] += 1
    return counts


def normalize_asr_casing(text: str, keep: Iterable[str] = ()) -> str:
    """
    Baja a minúscula las mayúsculas que el ASR pone a mitad de oración.

    Whisper capitaliza el inicio de cada trozo separado por pausa, así que aparecen
    'funciona Mais em outro lugar' o 'Utilizar no Hermes Porém'. El modelo de
    traducción lee una mayúscula a mitad de frase como nombre propio y no la traduce;
    medido sobre un doblaje real, eso dejó 26 segmentos con portugués sin traducir.

    Se conservan intactos los términos de `keep` (las entidades ya detectadas), las
    siglas en mayúscula sostenida y los tokens de una sola letra.
    """
    if not text:
        return text

    keep_lower = {k.lower() for k in keep if k}
    out: list[str] = []
    cursor = 0
    for m in _WORD_RE.finditer(text):
        word = m.group(0)
        if (
            len(word) < 2
            or word.isupper()
            or word.lower() in keep_lower
            or not word[0].isupper()
            or _is_sentence_start(text, m.start())
        ):
            continue
        out.append(text[cursor:m.start()])
        out.append(word[0].lower() + word[1:])
        cursor = m.end()
    if not out:
        return text
    out.append(text[cursor:])
    return "".join(out)


def _split_terms(sentences: Sequence[str]) -> tuple[set[str], set[str]]:
    """
    Separa las entidades en (estructurales, dudosas).

    Las estructurales se bloquean sin preguntar. Las dudosas son palabras en
    mayúscula que nunca aparecen en minúscula: pueden ser un nombre propio o una
    palabra corriente capitalizada por la pausa del reconocimiento de voz. La
    estadística del lote no las distingue cuando aparecen una sola vez, así que
    quedan marcadas para que el modelo las juzgue.
    """
    texts = [t or "" for t in sentences]
    lowercase = _lowercase_counts(texts)

    structural: set[str] = set()
    ambiguous: set[str] = set()
    for text in texts:
        for s, e, kind in _find_spans(text, lock_sentence_start=False):
            token = text[s:e].strip()
            if not token:
                continue
            if kind in _STRUCTURAL_KINDS:
                structural.add(token)
            elif kind in _CASE_KINDS and len(token) >= _MIN_TOKEN_LEN:
                if lowercase.get(token.lower(), 0) == 0:
                    ambiguous.add(token)
    return structural, ambiguous


def collect_known_terms(sentences: Sequence[str]) -> set[str]:
    """
    Reúne las entidades del lote: formas estructurales y palabras que nunca
    aparecen en minúscula en todo el texto.

    Una palabra que el ASR escribe alguna vez en minúscula es habla corriente, y
    bloquearla congelaría una función gramatical del idioma de origen dentro de la
    traducción. Por eso el criterio es la estadística del propio lote y no una lista.
    """
    structural, ambiguous = _split_terms(sentences)
    return structural | ambiguous


def ambiguous_terms(sentences: Sequence[str]) -> set[str]:
    """Subconjunto de `collect_known_terms` que necesita el juicio del modelo."""
    return _split_terms(sentences)[1]


def lock_text(text: str, known: Iterable[str] = ()) -> tuple[str, dict[int, str]]:
    """
    Sustituye entidades por placeholders numerados desde 1.

    `known` viene de `collect_known_terms` sobre el lote completo, de modo que una
    entidad se bloquea también cuando abre oración en este segmento concreto.

    Returns:
        (texto_bloqueado, {1: "Ghidra", 2: "12.1", ...})
    """
    if not text:
        return "", {}

    terms = {k for k in known if k}
    if not terms:
        terms = collect_known_terms([text])

    spans: list[tuple[int, int, str]] = []
    for term in sorted(terms, key=len, reverse=True):
        for m in re.finditer(re.escape(term), text):
            spans.append((m.start(), m.end(), "known"))

    merged: list[tuple[int, int, str]] = []
    last_end = -1
    for s, e, kind in sorted(spans, key=lambda x: (x[0], -(x[1] - x[0]))):
        if s < last_end:
            continue
        merged.append((s, e, kind))
        last_end = e

    if not merged:
        return text, {}

    out: list[str] = []
    mapping: dict[int, str] = {}
    cursor = 0
    for idx, (s, e, _kind) in enumerate(merged, start=1):
        out.append(text[cursor:s])
        original = text[s:e]
        mapping[idx] = original
        out.append(PLACEHOLDER_TMPL.format(idx))
        cursor = e
    out.append(text[cursor:])
    return "".join(out), mapping


def restore_text(text: str, mapping: dict[int, str]) -> str:
    """
    Devuelve las entidades originales. Tolera placeholders que el modelo haya
    espaciado (`⟦ E1 ⟧`) o duplicado; los ids desconocidos quedan intactos para
    que `check_entities` los reporte.
    """
    if not text:
        return text

    def _sub(m: re.Match[str]) -> str:
        idx = int(m.group(1))
        return mapping.get(idx, m.group(0))

    return PLACEHOLDER_RE.sub(_sub, text)


_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")

# Separador de millares escrito con espacio, apóstrofo o coma/punto: `220 000`,
# `1'200`, `1,200`. Solo cuenta si agrupa exactamente tres dígitos y no hay un
# cuarto detrás, para no comerse el decimal de `12.1` ni el punto de una frase.
_THOUSANDS_RE = re.compile(r"(?<=\d)[.,'\u00a0\u202f ](?=\d{3}(?!\d))")


def _numbers(text: str) -> list[str]:
    """Números fuera de placeholder, con los separadores de millares unificados."""
    clean = _THOUSANDS_RE.sub("", PLACEHOLDER_RE.sub(" ", text))
    return _NUM_RE.findall(clean)


def _significant(nums: Sequence[str]) -> list[str]:
    """
    Números cuyo valor hay que comparar: cantidades, versiones y fechas con dígitos.

    Los de una o dos cifras se ignoran a propósito. El traductor escribe `3` como
    `tres` y `1st` como `primero`, que es la forma correcta en el idioma destino;
    compararlos dígito a dígito marcaba fallos donde la traducción era buena. Una
    versión (`12.1`) o una cantidad (`220000`) sí se comparan siempre.
    """
    return [n for n in nums if sum(c.isdigit() for c in n) >= 3 or "." in n or "," in n]


def check_entities(locked_source: str, translated: str) -> dict[str, object]:
    """
    Verifica que la traducción conservó los placeholders y compara las cifras.

    El resultado duro (`ok`) mira solo los placeholders: un nombre propio perdido
    rompe la frase y se puede comprobar sin ambigüedad. Las cifras se devuelven
    aparte porque el destino puede escribirlas en palabras (`1326` → `trece
    veintiséis`), que es la forma correcta de doblarlas y no un error; solo se
    comparan las que tienen valor inequívoco y el desvío se reporta como aviso.

    Returns:
        {"ok": bool, "missing": [...], "extra": [...], "duplicated": [...],
         "numbers_source": [...], "numbers_target": [...], "numbers_mismatch": bool,
         "reasons": [...], "warnings": [...]}
    """
    ids_src = [int(x) for x in PLACEHOLDER_RE.findall(locked_source)]
    ids_dst = [int(x) for x in PLACEHOLDER_RE.findall(translated)]

    missing = sorted(set(ids_src) - set(ids_dst))
    extra = sorted(set(ids_dst) - set(ids_src))
    duplicated = sorted({i for i in ids_dst if ids_dst.count(i) > 1 and ids_src.count(i) == 1})

    nums_src = _numbers(locked_source)
    nums_dst = _numbers(translated)
    number_mismatch = sorted(_significant(nums_src)) != sorted(_significant(nums_dst))

    reasons: list[str] = []
    if missing:
        reasons.append(f"entidades perdidas {missing}")
    if extra:
        reasons.append(f"entidades inventadas {extra}")
    if duplicated:
        reasons.append(f"entidades duplicadas {duplicated}")

    warnings: list[str] = []
    if number_mismatch:
        warnings.append(f"números {_significant(nums_src)} -> {_significant(nums_dst)}")

    return {
        "ok": not reasons,
        "missing": missing,
        "extra": extra,
        "duplicated": duplicated,
        "numbers_source": nums_src,
        "numbers_target": nums_dst,
        "numbers_mismatch": number_mismatch,
        "reasons": reasons,
        "warnings": warnings,
    }
