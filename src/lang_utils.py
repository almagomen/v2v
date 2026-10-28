"""Utilidades de códigos de idioma, sin dependencias pesadas (importable en tests puros)."""


def same_language(a: str, b: str) -> bool:
    """
    Compara idiomas por subtag primario: 'pt-BR', 'pt_BR' y 'pt' son el mismo idioma.

    Whisper devuelve el código base ('pt'), así que comparar la cadena completa
    ('pt-BR' != 'pt') lanzaba una traducción pt→pt que reescribía el texto sin necesidad.
    """
    def _primary(code: str) -> str:
        return str(code).strip().lower().replace("_", "-").split("-")[0]

    return _primary(a) == _primary(b)
