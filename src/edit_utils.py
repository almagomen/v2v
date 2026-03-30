"""
Utilidades para editar textos y regenerar segmentos TTS.
"""
from pathlib import Path
from typing import Union

from src.audio_utils import clone_voice_segments
from src.pipeline import split_audio_sequences
from src.tts import model_tts


def find_changed_segments(
    original_texts: list[dict],
    edited_texts: list[dict],
) -> list[int]:
    """Devuelve índices (1-based) de segmentos que han cambiado."""
    changed = []
    for idx, (orig, edit) in enumerate(zip(original_texts, edited_texts), 1):
        if str(orig) != str(edit):
            changed.append(idx)
    return changed


def parse_sequence_input(seq_input: str, total_segments: int) -> list[int]:
    """
    Parsea entrada tipo "1,3,5" o "2-4" o ":" (todas).
    Returns: lista de índices 1-based.
    """
    if not seq_input or not seq_input.strip():
        raise ValueError(
            "La entrada está vacía. Usa números separados por comas (ej: 1,3,5), "
            "'-' para rangos (ej: 2-4) o ':' para todas."
        )
    seq_input = seq_input.strip()
    if seq_input == ":":
        return list(range(1, total_segments + 1))

    indices: list[int] = []
    for part in seq_input.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start, end = map(int, part.split("-"))
            except ValueError:
                raise ValueError(f"Formato inválido en rango: '{part}'.")
            if start > end:
                raise ValueError(f"Rango inválido: {part}.")
            indices.extend(range(start, end + 1))
        else:
            try:
                indices.append(int(part))
            except ValueError:
                raise ValueError(f"Formato inválido: '{part}'.")

    invalid = [i for i in indices if i < 1 or i > total_segments]
    if invalid:
        raise ValueError(f"Índices fuera de rango: {invalid}. Rango válido: 1-{total_segments}")
    return sorted(set(indices))


def regenerate_segments(
    video_path: Path,
    texts: list[dict],
    speaker_audio: Union[str, Path],
    changed_indices: list[int],
    language: str | None = None,
    slowdown_range: tuple[float, float] = (0.5, 0.80),
    stretch_target_ratio: float = 0.85,
    **kwargs,
) -> list[Path]:
    """Regenera solo los segmentos indicados. Returns lista de rutas a audios generados."""
    if not changed_indices:
        print("✅ No hay cambios para regenerar")
        return []

    print(f"🔄 Regenerando {len(changed_indices)} segmento(s): {changed_indices}")

    split_audio_sequences(
        audio_path=video_path.with_name("vocals.wav"),
        texts=texts,
        edit_indices=changed_indices,
    )

    paths, times, freq = clone_voice_segments(
        video_path,
        texts,
        language or "en",
        speaker_audio,
        model_tts,
        only_indices=changed_indices,
        slowdown_range=slowdown_range,
        stretch_target_ratio=stretch_target_ratio,
        **kwargs,
    )
    return paths


def get_video_bitrate(file_path: Union[str, Path]) -> int:
    """
    Obtiene el bitrate del video usando ffprobe (en bits por segundo).
    Si el metadato no está, lo calcula: (size * 8) / duration.
    """
    import subprocess
    import os

    file_path = str(file_path)
    if not os.path.exists(file_path):
        return 0

    try:
        # 1. Intentar obtener el bitrate directo del stream de video
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=bit_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        bitrate_str = res.stdout.strip()
        
        if bitrate_str and bitrate_str.isdigit():
            return int(bitrate_str)

        # 2. Si falla (N/A), calcular: (File Size bits) / Duration
        # Obtener duración
        cmd_dur = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        res_dur = subprocess.run(cmd_dur, capture_output=True, text=True, check=True)
        duration_str = res_dur.stdout.strip()

        if duration_str:
            duration = float(duration_str)
            if duration > 0:
                file_size_bits = os.path.getsize(file_path) * 8
                return int(file_size_bits / duration)

    except Exception as e:
        print(f"⚠️ Error al obtener bitrate de {file_path}: {e}")
    
    return 0
