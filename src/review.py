"""Auditoría pre-TTS: revisa el texto ya traducido antes de sintetizar.

El pipeline ya hace cuatro pasadas (traducción, rescate de entidades, idioma y
encaje). Esta no es una quinta pasada genérica: primero mide, y solo llama al
modelo por lo que quedó marcado.

Dos trabajos:

1. **Variantes del ASR.** Una misma entidad puede llegar escrita de dos formas
   distintas. Si viajan como entidades protegidas, el doblaje locuta la variante
   equivocada. El modelo decide la grafía canónica y el reemplazo es mecánico
   (palabra completa, sin tocar el resto).
2. **Segmentos marcados.** Los que todavía tienen una fuga de idioma, una entidad
   perdida o una desviación de duración severa. Se reescriben con instrucciones
   estrictas y se aceptan solo si mejoran y conservan las entidades.

El módulo es puro: no importa `genai`, no hace red. Recibe una función `call(prompt)`
y devuelve datos; la aceptación final vive en `translation.py`, que es quien conoce
los marcadores y los presupuestos.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Sequence

from src.lang_utils import SENTENCE_END_CHARS

_WORD_RE = re.compile(r"[^\W\d_][\w'’-]*", re.UNICODE)
_CAP_TERM_RE = re.compile(r"\b[^\W\d_][\w'’.-]{3,}\b", re.UNICODE)
_SENTENCE_RE = re.compile(
    rf"[^{re.escape(SENTENCE_END_CHARS)}]+[{re.escape(SENTENCE_END_CHARS)}]?",
    re.UNICODE,
)

def levenshtein(a: str, b: str) -> int:
    """Distancia de edición con dos filas (las palabras son cortas)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + (ca != cb),
            ))
        prev = cur
    return prev[-1]


def _context_for(term: str, texts: Sequence[str], limit: int = 140) -> str:
    """Primera frase donde aparece el término, recortada para el prompt."""
    for text in texts:
        for sentence in _SENTENCE_RE.findall(text or ""):
            if term in sentence:
                clean = re.sub(r"\s+", " ", sentence).strip()
                return clean[:limit]
    return ""


def _opens_sentence(text: str, pos: int) -> bool:
    """¿El token que empieza en `pos` abre una frase?"""
    j = pos - 1
    while j >= 0 and text[j] in " \t\n\r\"'«»—–-(":
        j -= 1
    return j < 0 or text[j] in SENTENCE_END_CHARS


def collect_term_variants(
    texts: Sequence[str],
    ignore: Iterable[str] = (),
) -> list[dict]:
    """
    Términos capitalizados que aparecen en el lote, con conteo y contexto.

    No agrupa: solo reúne los candidatos que el modelo puede confundir. Se excluyen
    las palabras que también aparecen en minúscula (son habla, no marcas), las que
    solo aparecen abriendo frase (ahí la mayúscula es ortografía, no marca) y los
    términos que el usuario ya fijó.
    """
    ignored = {str(t).lower() for t in ignore}
    lower_seen: set[str] = set()
    mid_sentence: set[str] = set()
    surfaces: Counter[str] = Counter()

    for text in texts:
        clean = text or ""
        for match in _WORD_RE.finditer(clean):
            token = match.group(0)
            if token[:1].islower():
                lower_seen.add(token.lower())
        for match in _CAP_TERM_RE.finditer(clean):
            # El patrón admite el punto final de la frase; si se cuenta como parte
            # del término, el reemplazo se come la puntuación.
            token = match.group(0).rstrip(".-")
            if len(token) < 4 or not token[:1].isupper():
                continue
            surfaces[token] += 1
            if not _opens_sentence(clean, match.start()):
                mid_sentence.add(token)

    candidates = [
        (term, count)
        for term, count in surfaces.items()
        if term.lower() not in ignored
        and term in mid_sentence
        and term.lower() not in lower_seen
    ]
    candidates.sort(key=lambda item: (-item[1], item[0]))

    return [
        {
            "term": term,
            "count": count,
            "context": _context_for(term, texts),
        }
        for term, count in candidates[:60]
    ]


def build_term_prompt(candidates: Sequence[dict], source_lang_name: str) -> str:
    """Prompt de consolidación de variantes del ASR."""
    lines = []
    for item in candidates:
        context = item.get("context") or ""
        lines.append(
            f'- "{item["term"]}" ({item["count"]}) · contexto: {context}'
        )
    return f"""Recibes términos que el reconocimiento de voz escribió en mayúscula en la
transcripción de un vídeo en {source_lang_name}. Algunos son la MISMA entidad escrita
de dos formas distintas; otros son entidades diferentes.

Agrupa solo las variantes que designen el mismo objeto y devuelve la grafía canónica
correcta (el nombre real del producto, empresa o persona):

- Si no estás seguro de que sean lo mismo, no las agrupes.
- No inventes entidades que no estén en la lista.
- La canónica tiene que ser una grafía real del término, no una explicación.
- No agrupes formas que solo difieran por una variación gramatical (número, género,
  conjugación o cualquier otra): son palabras distintas, no grafías de la misma entidad.
- Si todas las variantes son correctas para cosas distintas, no devuelvas nada.

Devuelve únicamente este JSON:
{{"grupos": [{{"variantes": ["...", "..."], "canonica": "..."}}]}}

Términos:
{chr(10).join(lines)}"""


def _is_word_inflection(a: str, b: str) -> bool:
    """
    ¿Son la misma palabra en distinta forma gramatical?

    Sin reglas de ningún idioma: si una forma contiene a la otra y solo añade un
    sufijo corto y alfabético, se trata como flexión y no como dos grafías de la
    misma entidad.
    """
    la, lb = str(a).lower(), str(b).lower()
    if la == lb:
        return True
    short, long_ = (la, lb) if len(la) <= len(lb) else (lb, la)
    if not short or not long_.startswith(short):
        return False
    suffix = long_[len(short):]
    return 0 < len(suffix) <= 3 and suffix.isalpha()


def parse_term_groups(raw: object, known: Iterable[str]) -> dict[str, str]:
    """
    Convierte la respuesta del modelo en un mapa variante→canónica.

    Se acota a las variantes que existían en el lote y la canónica tiene que parecerse
    a alguna de ellas: así un juicio errático no puede reescribir el guion.
    """
    if not isinstance(raw, dict):
        return {}
    groups = raw.get("grupos")
    if not isinstance(groups, list):
        return {}

    allowed = {str(t): str(t) for t in known}
    mapping: dict[str, str] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        variants = group.get("variantes")
        canonical = str(group.get("canonica") or "").strip()
        if not isinstance(variants, list) or not canonical:
            continue
        if not canonical[:1].isupper():
            continue
        real = [v for v in variants if str(v) in allowed]
        if len(real) < 2:
            continue
        # Una variación gramatical no es una variante de grafía: unificarlas
        # reescribe el guion y rompe la concordancia.
        if any(
            _is_word_inflection(real[i], real[j])
            for i in range(len(real))
            for j in range(i + 1, len(real))
        ):
            continue
        # La canónica tiene que ser una grafía del lote, no una explicación ni un
        # nombre ampliado: si añade palabras queda a más distancia y no debe pasar.
        if not any(levenshtein(canonical.lower(), v.lower()) <= 2 for v in real):
            continue
        for variant in real:
            if variant != canonical:
                mapping[str(variant)] = canonical
    return mapping


def apply_term_map(texts: Sequence[str], mapping: dict[str, str]) -> tuple[list[str], int]:
    """Reemplaza las variantes por su canónica, solo como palabra completa."""
    if not mapping:
        return list(texts), 0
    pattern = re.compile(
        r"(?<![\w'’-])(" + "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)) + r")(?![\w'’-])"
    )
    out: list[str] = []
    changed = 0
    for text in texts:
        new_text, n = pattern.subn(lambda m: mapping[m.group(1)], text or "")
        changed += n
        out.append(new_text)
    return out, changed


def build_review_prompt(items: dict[str, dict[str, str]], target_lang_name: str) -> str:
    """Prompt del repaso acotado: solo los segmentos que quedaron marcados."""
    import json

    return f"""Eres un revisor de doblaje al {target_lang_name}. Recibes segmentos ya
traducidos y ajustados al tiempo del vídeo. `fuente` es el original y `patron` es ese
mismo original con los términos protegidos sustituidos por marcadores ⟦E#⟧. Corrige
SOLO el problema que indica `motivo`:

- `residuo`: esas palabras siguen en el idioma original; tradúcelas de verdad. Si la
  palabra es un cognado correcto en {target_lang_name}, déjala y no cambies nada más.
- `duración`: el texto no cabe en el tiempo disponible; ajústalo al rango sin cambiar
  el sentido. Si va corto, restituye primero información de `fuente` que se haya
  omitido.
- `entidad`: falta un marcador ⟦E#⟧; restáuralo en su sitio, en el orden de `patron`.

Reglas:
1. Conserva el significado, el tono y la persona gramatical. No añadas datos nuevos.
2. No añadas muletillas ni conectores de relleno propios de {target_lang_name}.
3. Los marcadores ⟦E1⟧, ⟦E2⟧... son intocables: los mismos que en `patron`, una sola
   vez y en el mismo orden. No los traduzcas ni los expliques.
4. Si el segmento no tiene arreglo sin inventar, devuélvelo igual.

Entrada:
{json.dumps(items, indent=2, ensure_ascii=False)}

Devuelve únicamente un objeto JSON con las mismas claves y el texto final como valor:
{{"1": "texto corregido", "2": "texto corregido"}}"""


def parse_review_map(raw: object, allowed_keys: Iterable[str]) -> dict[str, str]:
    """Acota la respuesta a las claves enviadas y descarta valores no textuales."""
    if not isinstance(raw, dict):
        return {}
    allowed = {str(k) for k in allowed_keys}
    return {
        str(k): str(v).strip()
        for k, v in raw.items()
        if str(k) in allowed and isinstance(v, str) and str(v).strip()
    }


def audit_summary(flagged: Sequence[dict]) -> str:
    """Línea corta para el log: cuántos y por qué."""
    if not flagged:
        return ""
    reasons: Counter[str] = Counter()
    for item in flagged:
        for part in str(item.get("motivo", "?")).split("|"):
            name = part.split(":")[0].strip()
            if name:
                reasons[name] += 1
    detail = ", ".join(f"{name} {count}" for name, count in sorted(reasons.items()))
    return f"{len(flagged)} segmento(s) marcado(s) ({detail})"
