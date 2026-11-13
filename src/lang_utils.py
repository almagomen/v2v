"""Utilidades de idioma sin diccionarios.

La detección de texto sin traducir no usa listas de palabras: compara el origen con
la salida y mide solapamiento léxico. Un token idéntico en ambos lados es copia,
nombre propio o un cognado correcto; esa distinción la resuelve el modelo, que sí
conoce el par de idiomas, y aquí solo se comprueba mecánicamente que el número de
coincidencias baje.

No hay lista de cognados: una lista siempre cubriría unos pares de idiomas y no
otros, y además envejecería con cada idioma nuevo. El prompt del juicio ya declara
la regla general —una palabra que es correcta en el idioma destino no es una fuga—
y la aceptación es mecánica (el recuento tiene que bajar).
"""

import re

_WORD_RE = re.compile(r"[^\W\d_][\w'-]*", re.UNICODE)

# Por debajo de 3 letras el solapamiento es ruido: artículos y preposiciones cortas
# coinciden en casi todos los idiomas romance y no informan de nada.
MIN_TOKEN_LEN = 3

# Signos que cierran oración en las escrituras principales (latina, CJK, árabe,
# índicas). Es puntuación, no vocabulario: sin ellos el pipeline no reconoce el fin
# de frase fuera del alfabeto latino y no puede separar pausas ni oraciones.
SENTENCE_END_CHARS = ".!?…。！？؛؟۔।॥။።"

# Nombres legibles para los códigos que puede devolver Whisper. No pretende ser
# exhaustiva: `language_name` cae al código cuando falta, nunca a otro idioma.
LANGUAGE_NAMES = {
    "es": "Español", "en": "Inglés", "pt": "Portugués", "fr": "Francés",
    "de": "Alemán", "it": "Italiano", "nl": "Neerlandés", "pl": "Polaco",
    "ru": "Ruso", "uk": "Ucraniano", "tr": "Turco", "ar": "Árabe",
    "fa": "Persa", "hi": "Hindi", "bn": "Bengalí", "ta": "Tamil",
    "ja": "Japonés", "ko": "Coreano", "zh": "Chino", "vi": "Vietnamita",
    "th": "Tailandés", "id": "Indonesio", "ms": "Malayo", "tl": "Filipino",
    "sv": "Sueco", "da": "Danés", "no": "Noruego", "fi": "Finés",
    "cs": "Checo", "sk": "Eslovaco", "hu": "Húngaro", "ro": "Rumano",
    "el": "Griego", "he": "Hebreo", "ca": "Catalán", "eu": "Euskera",
    "gl": "Gallego",
}


def primary_lang(code: str) -> str:
    """
    Subtipo primario de un código BCP-47, en minúscula.

    La variante regional o de escritura no cambia el idioma: se descarta todo lo
    que siga al primer separador, sea guion o guion bajo, para comparar siempre el
    mismo nivel de la etiqueta.
    """
    return str(code or "").strip().lower().replace("_", "-").split("-")[0]


def language_name(code: str) -> str:
    """
    Nombre legible del idioma a partir de su código BCP-47.

    La tabla solo sirve para mostrar el nombre en los prompts; no es una lista de
    idiomas admitidos ni un criterio de traducción. Si el código no está en la
    tabla se devuelve el propio código, nunca otro idioma: un fallback fijo
    traduciría al idioma equivocado en silencio.
    """
    raw = str(code or "").strip()
    if raw.lower() in ("none", "null"):
        raw = ""
    return (
        LANGUAGE_NAMES.get(primary_lang(raw))
        or LANGUAGE_NAMES.get(raw.lower())
        or raw
        or "el idioma original"
    )


def same_language(a: str, b: str) -> bool:
    """
    ¿Dos códigos designan el mismo idioma?

    Compara solo el subtipo primario, así que una variante regional o de escritura
    frente a su base no cuenta como cambio de idioma. Dos códigos vacíos no se
    consideran iguales: un idioma desconocido no demuestra identidad.
    """
    pa, pb = primary_lang(a), primary_lang(b)
    return bool(pa) and pa == pb


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
