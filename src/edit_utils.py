"""
Utilidades para editar textos y regenerar segmentos TTS.
"""
from pathlib import Path
from typing import Union



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
        # 1. Intentar obtener el bitrate directo del video
        cmd = [
            "ffprobe", "-v", "error", 
            "-show_entries", "format=bit_rate",
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
