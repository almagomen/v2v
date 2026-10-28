"""Utilidades de idioma sin diccionarios.

La detección de texto sin traducir no usa listas de palabras: compara el origen con
la salida y mide solapamiento léxico. Un token idéntico en ambos lados es copia o
nombre propio; la lista de candidatos la juzga el modelo, que sí conoce el par de
idiomas, y aquí solo se comprueba mecánicamente que el número de coincidencias baje.
"""

import re

_WORD_RE = re.compile(r"[^\W\d_][\w'-]*", re.UNICODE)

# Por debajo de 3 letras el solapamiento es ruido: artículos y preposiciones cortas
# coinciden en casi todos los idiomas romance y no informan de nada.
MIN_TOKEN_LEN = 3


def same_language(a: str, b: str) -> bool:
    """
    Compara idiomas por subtag primario: 'pt-BR', 'pt_BR' y 'pt' son el mismo idioma.

    Whisper devuelve el código base ('pt'), así que comparar la cadena completa
    ('pt-BR' != 'pt') lanzaba una traducción pt→pt que reescribía el texto sin necesidad.
    """
    def _primary(code: str) -> str:
        return str(code or "").strip().lower().replace("_", "-").split("-")[0]

    return _primary(a) == _primary(b)


def _tokens(text: str) -> set[str]:
    """Tokens alfabéticos en minúscula, sin los demasiado cortos para informar."""
    return {
        m.group(0).lower()
        for m in _WORD_RE.finditer(text or "")
        if len(m.group(0)) >= MIN_TOKEN_LEN
    }


def shared_tokens(source: str, translated: str, ignore=()) -> list[str]:
    """
    Tokens que aparecen literalmente en el origen y en la traducción.

    Mide copia, no traducción. No decide si un token es fuga o un nombre propio:
    eso lo resuelve el modelo en la pasada de idioma. `ignore` recibe los términos
    bloqueados, que viajan idénticos por diseño y no son fuga.
    """
    if not source or not translated:
        return []

    ignored: set[str] = set()
    for term in ignore:
        ignored |= _tokens(term)

    return sorted((_tokens(source) & _tokens(translated)) - ignored)
