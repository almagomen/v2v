"""
Utilidades de audio: ajuste de duración, clonado de segmentos, merge.
"""

from pathlib import Path
from typing import Optional, Tuple, Any

try:
    import torch
    import torchaudio
except ImportError:
    torch = None
    torchaudio = None

from src.assets import register_segment


def _build_atempo_filter(tempo: float) -> str:
    """Construye cadena de filtros atempo encadenados para valores fuera de [0.5, 2.0]."""
    factors = []
    curr = float(tempo)
    while curr > 2.0:
        factors.append("atempo=2.0")
        curr /= 2.0
    while curr < 0.5:
        factors.append("atempo=0.5")
        curr /= 0.5
    factors.append(f"atempo={curr:.4f}")
    return ",".join(factors)


def adjust_audio_duration(
    audio: Any,
    target_duration_samples: int,
    sample_rate: int,
    min_tempo: float = 0.5,
    max_tempo: float = 4.0,
) -> Any:
    """
    Ajusta la duración del audio usando cambio de tempo.
    """
    if audio is None or audio.shape[-1] == 0 or target_duration_samples <= 0:
        return audio

    tempo = audio.shape[-1] / target_duration_samples
    safe_tempo = max(min(tempo, max_tempo), min_tempo)

    try:
        filter_str = _build_atempo_filter(safe_tempo)
        effector = torchaudio.io.AudioEffector(filter_str)
        adjusted = effector.apply(audio.T, sample_rate).T
        if adjusted.shape[-1] > target_duration_samples:
            return adjusted[:, :target_duration_samples]
        return adjusted
    except Exception as e:
        print(f"⚠️ Error al ajustar tempo ({safe_tempo:.2f}x): {e}")
        if audio.shape[-1] > target_duration_samples:
            return audio[:, :target_duration_samples]
        return audio


def clone_voice_segments(
    path: Path,
    texts: list[dict],
    language: str,
    audio_ref: str | Path,
    tts_fn: callable,
    only_indices: Optional[list[int]] = None,
    slowdown_range: Optional[Tuple[float, float]] = None,
    stretch_target_ratio: float = 1.0,
    speed: float = 1.0,
    target_duration: Optional[float] = None,
    register: bool = True,
    **kwargs,
) -> Tuple[list[Path], list[int], int]:
    seqs_src_dir = path.parent / "Seqs_src"
    seqs_trg_dir = path.parent / "Seqs_trg"
    seqs_trg_dir.mkdir(exist_ok=True)

    texts_to_process = (
        texts if only_indices is None else [texts[i - 1] for i in only_indices]
    )

    times: list[int] = []
    path_es: list[Path] = []

    for idx, text_dict in enumerate(texts_to_process):
        text = text_dict["text"]
        start_time = text_dict["start"]
        speaker = text_dict.get("speaker", "SPEAKER_00")

        seq_num = only_indices[idx] if only_indices else idx + 1

        audio_en_path = seqs_src_dir / f"vocals_{seq_num:03d}.wav"
        if not audio_en_path.exists():
            print(f"⚠️ No se encontró: {audio_en_path}")
            continue

        arr_en, rate_en = torchaudio.load(str(audio_en_path))
        dur_en = arr_en.shape[-1] / rate_en

        arr, rate = tts_fn(text, language, audio_ref, **kwargs)
        if arr is None or rate is None:
            continue

        # --- GUARDAR COPIA RAW INTACTA PARA "APPLY SPEED" FUTURO ---
        safe_speaker = speaker.replace(" ", "_").replace("/", "_").replace("\\", "_")
        raw_es_path = seqs_trg_dir / f"tts_{safe_speaker}_{seq_num:03d}_raw.wav"
        torchaudio.save(str(raw_es_path), arr, sample_rate=rate)
        # --------------------------------------------------------

        dur_es = arr.shape[-1] / rate
        duration_ratio = dur_es / dur_en if dur_en > 0 else 0
        print(f"{idx+1:2d}. ", end="")

        if slowdown_range and stretch_target_ratio != 1.0:
            if duration_ratio > 1.0:
                print(
                    f"{(dur_es / dur_en):.2f}x: {dur_es:5.2f}s → {dur_en:5.2f}s",
                    end=" ",
                )
                target_samples = int(dur_en * rate)
                arr = adjust_audio_duration(arr, target_samples, rate)
            elif slowdown_range[0] < duration_ratio < slowdown_range[1]:
                target_dur_sec = dur_es + (dur_en - dur_es) * stretch_target_ratio
                print(
                    f"{(dur_es / target_dur_sec):.2f}x: {dur_es:5.2f}s → {target_dur_sec:5.2f}s",
                    end=" ",
                )
                target_samples = int(target_dur_sec * rate)
                arr = adjust_audio_duration(arr, target_samples, rate)
            else:
                print(
                    f"{(dur_es / dur_en):.2f}x: {dur_es:5.2f}s → {dur_en:5.2f}s",
                    end=" ",
                )

        # Aplicar target_duration (modo 's') si está presente
        if target_duration is not None and target_duration > 0:
            raw_speed = dur_es / target_duration if target_duration > 0 else 1.0
            if raw_speed < 0.5:
                effective_speed = 0.5
                print(
                    f"Target duration: {target_duration:.2f}s -> speed={raw_speed:.2f}x CLAMPED a 0.5x",
                    end=" ",
                )
            elif raw_speed > 2.0:
                effective_speed = 2.0
                print(
                    f"Target duration: {target_duration:.2f}s -> speed={raw_speed:.2f}x CLAMPED a 2.0x",
                    end=" ",
                )
            else:
                effective_speed = raw_speed
                print(
                    f"Target duration: {target_duration:.2f}s -> speed={effective_speed:.2f}x",
                    end=" ",
                )
            target_samples = int(target_duration * rate)
            arr = adjust_audio_duration(arr, target_samples, rate)
        # Aplicar speed manual del usuario si es distinto de 1.0 y no se aplicó target_duration
        elif speed != 1.0:
            target_samples = int(arr.shape[-1] / speed)
            print(f"Speed manual: {speed}x -> {target_samples} samples", end=" ")
            arr = adjust_audio_duration(arr, target_samples, rate)

        print(f" {text}")

        # Generar nombre con formato consistente: tts_{speaker}_{NNNN}.wav
        # Esto permite al frontend identificar el segmento y su speaker
        safe_speaker = speaker.replace(" ", "_").replace("/", "_").replace("\\", "_")
        audio_es_path = seqs_trg_dir / f"tts_{safe_speaker}_{seq_num:03d}.wav"
        torchaudio.save(str(audio_es_path), arr, sample_rate=rate)
        path_es.append(audio_es_path)
        # Registrar ruta exacta del segmento en el manifiesto de activos
        if register:
            register_segment(path.parent, seq_num, audio_es_path)
        start_samples = int(start_time * rate)
        times.append(start_samples)

    return path_es, times, rate


def merge_cloned_audio(
    original_audio_path: Path,
    cloned_segments: list[Path],
    segment_times: list[int],
    sample_rate: int,
) -> Any:
    """Combina segmentos de audio clonados en un solo tensor."""
    arr, org_sr = torchaudio.load(str(original_audio_path))
    fix_es = torchaudio.functional.resample(arr, orig_freq=org_sr, new_freq=sample_rate)
    fix_es[:, :] = 0

    for start_samples, audio_seg_path in zip(segment_times, cloned_segments):
        arr_es, _ = torchaudio.load(str(audio_seg_path))
        end_samples = start_samples + arr_es.shape[1]
        if end_samples <= fix_es.shape[1]:
            fix_es[:, start_samples:end_samples] = arr_es

    return fix_es
