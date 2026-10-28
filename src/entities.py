"""
Entity lock para traducción audiovisual.

Problema que resuelve: los LLM de traducción normalizan lo que debería quedar
congelado. `Rea Agent` -> `reagente`, `install ghidra.ps1` -> `InstallGhidra.ps 1`,
`12.1` -> `2.1`. En un tutorial técnico eso rompe el contenido.

Estrategia (análoga a un glosario protegido en CAT tools):
  1. `lock_text` sustituye cada entidad por un placeholder opaco `⟦E1⟧`.
  2. El MT traduce el texto con placeholders; el prompt prohíbe tocarlos.
  3. `check_entities` verifica placeholders y números contra el original bloqueado.
  4. `restore_text` devuelve las entidades originales.

El placeholder usa ⟦⟧ (U+27E6/27E7) y no [] para no colisionar con las etiquetas
de emoción ([excited]) ni con los prefijos de presupuesto ([2.1s slot | ...]).
"""
from __future__ import annotations

import re
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

# Palabras que pueden aparecer en mayúsculas en pt/es sin ser entidades.
_STOPWORDS = {
    "EU", "E", "ELE", "ELA", "ELES", "ELAS", "A", "O", "OS", "AS", "UM", "UMA",
    "DE", "DO", "DA", "DOS", "DAS", "EM", "NO", "NA", "NOS", "NAS", "QUE", "NAO",
    "SIM", "SE", "JA", "AI", "MAS", "POR", "PARA", "COM", "SEM", "ATE", "OU",
    "ISSO", "ISTO", "AQUI", "ASSIM", "TUDO", "NADA", "AGORA", "DEPOIS", "SO",
    "EL", "LA", "LOS", "LAS", "UN", "UNA", "Y", "ES", "EN", "LO", "LE", "LES",
    "SU", "MI", "TU", "SI", "NO",
}

# Palabras corrientes de pt/es que el ASR capitaliza a mitad de frase (tras coma o
# guion de diálogo). Bloquearlas congelaría una función gramatical en el otro idioma.
_COMMON_CAPS = {
    "MAS", "PARA", "QUE", "TEM", "BEM", "ELE", "ELA", "ELES", "ELAS", "ESSE",
    "ESSA", "ISSO", "ISTO", "AQUI", "AQUI", "AGORA", "VAMOS", "GALERA",
    "ESPERO", "SEMPRE", "MESMO", "BELEZA", "MAPEANDO", "ADORO", "ENTENDI",
    "ENTENDIDO", "CERTO", "BOM", "BOA", "GENTE", "CARA", "OLHA", "VEJA",
    "BORA", "TUDO", "NADA", "DEPOIS", "ENTAO", "HOJE", "ASSIM", "TAMBEM",
    "SO", "AINDA", "CLARO", "QUANDO", "COMO", "ONDE", "PORQUE", "ENTAO",
    "PERO", "CUANDO", "CON", "SIN", "POR", "ESTE", "ESTA", "ESTO", "ESO",
    "ESA", "AHORA", "BUENO", "ENTONCES", "DESPUES", "TAMBIEN", "SOLO",
    "TODO", "MAS", "MUY", "ESTA", "ESTOY", "TENGO", "TIENE", "HOLA",
    "SEGUNDO", "PRIMEIRO", "PRIMERO", "VEZ", "VECES", "AH", "EH", "OH",
}

_STOPWORDS |= _COMMON_CAPS

_SENTENCE_END_CHARS = ".!?:;\n\"'«»-—"


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
            if kind == "caps":
                if token in _STOPWORDS or not token.isupper():
                    continue
            elif kind == "proper":
                if token.upper() in _STOPWORDS:
                    continue
                if not lock_sentence_start and _is_sentence_start(text, s):
                    continue
            elif kind == "camel":
                if token in _STOPWORDS:
                    continue
            elif kind == "pascal":
                if token.upper() in _STOPWORDS:
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

    return _merge_adjacent(text, accepted)


def _merge_adjacent(text: str, spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """
    Une tokens consecutivos separados por un solo espacio (`Open Code`, `REA Agent`).
    Así el nombre de producto viaja como una sola unidad y el MT no puede partirlo.
    """
    if len(spans) < 2:
        return spans
    merged: list[tuple[int, int, str]] = [spans[0]]
    for s, e, kind in spans[1:]:
        ps, pe, pk = merged[-1]
        if s == pe + 1 and text[pe:s] == " " and pk != "known":
            merged[-1] = (ps, e, pk)
        else:
            merged.append((s, e, kind))
    return merged


def collect_known_terms(sentences: Sequence[str]) -> set[str]:
    """
    Reúne las entidades que aparecen fuera de inicio de oración en todo el lote.
    Permite bloquear después esas mismas palabras aunque abran una frase.
    """
    known: set[str] = set()
    for text in sentences:
        if not text:
            continue
        for s, e, _kind in _find_spans(text, lock_sentence_start=False):
            token = text[s:e].strip()
            if token:
                known.add(token)
    return known


def lock_text(text: str, known: Iterable[str] = ()) -> tuple[str, dict[int, str]]:
    """
    Sustituye entidades por placeholders numerados desde 1.

    Returns:
        (texto_bloqueado, {1: "Ghidra", 2: "12.1", ...})
    """
    if not text:
        return "", {}

    known_sorted = sorted({k for k in known if k}, key=len, reverse=True)
    known_spans: list[tuple[int, int, str]] = []
    if known_sorted:
        for term in known_sorted:
            for m in re.finditer(re.escape(term), text):
                known_spans.append((m.start(), m.end(), "known"))
        known_spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))

    spans = _find_spans(text, lock_sentence_start=False)
    merged: list[tuple[int, int, str]] = []
    last_end = -1
    for s, e, kind in sorted(spans + known_spans, key=lambda x: (x[0], -(x[1] - x[0]))):
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


def _numbers(text: str) -> list[str]:
    """Números fuera de placeholder, con `1.200` normalizado a `1200`."""
    return [n.replace(".", "") for n in re.findall(r"\d+(?:[.,]\d+)*", PLACEHOLDER_RE.sub(" ", text))]


def check_entities(locked_source: str, translated: str) -> dict[str, object]:
    """
    Verifica que la traducción conservó placeholders y números del original.

    Returns:
        {"ok": bool, "missing": [...], "extra": [...], "duplicated": [...],
         "numbers_source": [...], "numbers_target": [...], "reasons": [...]}
    """
    ids_src = [int(x) for x in PLACEHOLDER_RE.findall(locked_source)]
    ids_dst = [int(x) for x in PLACEHOLDER_RE.findall(translated)]

    missing = sorted(set(ids_src) - set(ids_dst))
    extra = sorted(set(ids_dst) - set(ids_src))
    duplicated = sorted({i for i in ids_dst if ids_dst.count(i) > 1 and ids_src.count(i) == 1})

    nums_src = _numbers(locked_source)
    nums_dst = _numbers(translated)
    if sorted(nums_src) != sorted(nums_dst):
        number_mismatch = True
    else:
        number_mismatch = False

    reasons: list[str] = []
    if missing:
        reasons.append(f"entidades perdidas {missing}")
    if extra:
        reasons.append(f"entidades inventadas {extra}")
    if duplicated:
        reasons.append(f"entidades duplicadas {duplicated}")
    if number_mismatch:
        reasons.append(f"números {nums_src} -> {nums_dst}")

    return {
        "ok": not reasons,
        "missing": missing,
        "extra": extra,
        "duplicated": duplicated,
        "numbers_source": nums_src,
        "numbers_target": nums_dst,
        "reasons": reasons,
    }
