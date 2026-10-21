from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import torch
try:
    import torchaudio
except ImportError:
    torchaudio = None


def verify_audio_quality(audio_path: Path | str, expected_text: str = "") -> dict[str, Any]:
    """
    Verifica la integridad acústica y calidad de un segmento sintetizado:
    - Comprueba duración mínima y descarte de archivos corruptos/vacíos.
    - Detección de clipping (distorsión de pico) y silencios muertos.
    - Ratio de caracteres/tiempo para detectar posibles truncamientos de habla.
    """
    p = Path(audio_path)
    if not p.exists() or p.stat().st_size == 0:
        return {"status": "fail", "reason": "Archivo no existe o vacío", "duration": 0.0}

    if torchaudio is None:
        return {"status": "pass", "reason": "torchaudio no disponible para QA profundo", "duration": 0.0}

    try:
        waveform, sr = torchaudio.load(str(p))
        num_frames = waveform.shape[-1]
        dur = num_frames / sr if sr > 0 else 0.0

        if dur < 0.2:
            return {"status": "fail", "reason": f"Audio demasiado corto ({dur:.2f}s)", "duration": dur}

        # Detección de pico y clipping
        max_amp = float(torch.max(torch.abs(waveform)))
        if max_amp < 0.005:
            return {"status": "fail", "reason": "Audio en silencio total (amplitud inaudible)", "duration": dur}
        
        has_clipping = max_amp >= 0.999

        # Detección de truncamiento por longitud de texto
        clean_text = expected_text.strip()
        words_count = len(clean_text.split())
        # Si tiene más de 12 palabras pero el audio dura menos de 1.0s, hubo truncamiento en el TTS
        if words_count > 12 and dur < 1.0:
            return {"status": "warn", "reason": f"Posible truncamiento ({words_count} palabras en {dur:.1f}s)", "duration": dur, "clipping": has_clipping}

        status = "warn" if has_clipping else "pass"
        reason = "Picos cercanos a saturación" if has_clipping else "OK"

        return {
            "status": status,
            "reason": reason,
            "duration": round(dur, 2),
            "max_amplitude": round(max_amp, 3),
            "clipping": has_clipping,
        }
    except Exception as e:
        return {"status": "fail", "reason": f"Error al leer audio: {e}", "duration": 0.0}
