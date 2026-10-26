"""
Utilidades de audio: ajuste de duración, clonado de segmentos, merge.
"""

from pathlib import Path
from typing import Optional, Tuple, Any

import numpy as np

try:
    import torch
    import torchaudio
except ImportError:
    torch = None
    torchaudio = None



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


import subprocess
import tempfile
import os
import re


def _extract_emotion_prefix(text: str) -> tuple[str, str]:
    """Extrae las etiquetas de emoción iniciales [tag] y el contenido limpio restante."""
    if not text:
        return "", ""
    match = re.match(r"^((?:\[[^\]]+\]\s*)+)(.*)$", text.strip())
    if match:
        tags = match.group(1).strip()
        rest = match.group(2).strip()
        return tags, rest
    return "", text.strip()


def _format_aligned_segment_texts(
    orig_text: str,
    final_text: str,
    source_lang: Optional[str] = None,
    indent: str = "",
) -> list[str]:
    """
    Formatea las líneas de texto del segmento (original y traducido/sintetizado).
    Alinea a la derecha las etiquetas iniciales ([idioma] y [emoción]) para que los
    corchetes de cierre concuerden en la misma columna vertical y los textos arranquen alineados.
    """
    clean_curr = re.sub(r"\[.*?\]", "", final_text).strip()
    clean_orig = re.sub(r"\[.*?\]", "", orig_text).strip()
    is_translation = bool(clean_orig and clean_orig.lower() != clean_curr.lower())

    tag_final, cont_final = _extract_emotion_prefix(final_text)

    # Si no es traducción, solo emitir final_text tal cual
    if not is_translation:
        return [f"{indent}{final_text}"]

    sl = (source_lang or "").strip().lower()
    tag_orig = f"[{sl}]" if sl else ""

    if tag_final and tag_orig:
        len_orig = len(tag_orig)
        len_final = len(tag_final)
        max_w = max(len_orig, len_final)

        pad_orig = " " * (max_w - len_orig)
        pad_final = " " * (max_w - len_final)

        pfx_orig = f"{indent}{pad_orig}{tag_orig} "
        pfx_final = f"{indent}{pad_final}{tag_final} "

        return [
            f"{pfx_orig}{orig_text}",
            f"{pfx_final}{cont_final}",
        ]

    if tag_orig:
        return [
            f"{indent}{tag_orig} {orig_text}",
            f"{indent}{final_text}",
        ]

    return [
        f"{indent}{orig_text}",
        f"{indent}{final_text}",
    ]


def _adjust_audio_duration_ffmpeg(
    audio: Any,
    filter_str: str,
    sample_rate: int,
    target_duration_samples: int,
) -> Any:
    """Ajusta el tempo del tensor de audio usando FFmpeg de forma nativa y robusta."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_in, \
         tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_out:
        in_path = f_in.name
        out_path = f_out.name

    try:
        torchaudio.save(in_path, audio, sample_rate=sample_rate)
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-i", in_path,
            "-filter:a", filter_str,
            out_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 44:
            adjusted, _ = torchaudio.load(out_path)
            if adjusted.shape[-1] > target_duration_samples:
                return adjusted[:, :target_duration_samples]
            return adjusted
        else:
            raise RuntimeError(res.stderr.strip() or "FFmpeg falló al procesar el audio")
    finally:
        for p in (in_path, out_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


def adjust_audio_duration(
    audio: Any,
    target_duration_samples: int,
    sample_rate: int,
    min_tempo: float = 0.5,
    max_tempo: float = 4.0,
) -> Any:
    """
    Ajusta la duración del audio usando cambio de tempo (time-stretching sin alterar tono).
    """
    if audio is None or audio.shape[-1] == 0 or target_duration_samples <= 0:
        return audio

    tempo = audio.shape[-1] / target_duration_samples
    safe_tempo = max(min(tempo, max_tempo), min_tempo)

    # Si la diferencia es imperceptible (<=4%), no alterar con atempo para no degradar el timbre:
    # aplicar micro-trim suave con fade-out o micro-pad de silencio
    if abs(safe_tempo - 1.0) <= 0.04:
        if audio.shape[-1] > target_duration_samples:
            trimmed = audio[:, :target_duration_samples].clone()
            fade_len = max(16, min(int(0.005 * sample_rate), target_duration_samples))
            if torch is not None and fade_len > 0:
                fade = torch.linspace(1.0, 0.0, fade_len, device=trimmed.device)
                trimmed[:, -fade_len:] *= fade
            return trimmed
        elif audio.shape[-1] < target_duration_samples:
            pad_len = target_duration_samples - audio.shape[-1]
            if torch is not None:
                return torch.nn.functional.pad(audio, (0, pad_len))
        return audio

    filter_str = _build_atempo_filter(safe_tempo)

    # 1. Intentar torchaudio.io.AudioEffector si está disponible en la versión instalada
    try:
        import torchaudio.io
        if hasattr(torchaudio.io, "AudioEffector"):
            effector = torchaudio.io.AudioEffector(filter_str)
            adjusted = effector.apply(audio.T, sample_rate).T
            if adjusted.shape[-1] > target_duration_samples:
                return adjusted[:, :target_duration_samples]
            return adjusted
    except Exception:
        pass

    # 2. Método estándar y confiable con FFmpeg nativo
    try:
        return _adjust_audio_duration_ffmpeg(audio, filter_str, sample_rate, target_duration_samples)
    except Exception as e:
        print(f"⚠️ Error al ajustar tempo ({safe_tempo:.2f}x): {e}")
        if audio.shape[-1] > target_duration_samples:
            return audio[:, :target_duration_samples]
        return audio


def distribute_silence_padding(
    arr: Any,
    target_samples: int,
    rate: int,
    max_per_valley: Optional[int] = None,
    allow_tail_pad: bool = True,
) -> Any:
    """
    Distribuye el padding de silencio necesario entre los valles de silencio internos (respiros/[break])
    y el final del audio, evitando dejar un hueco muerto gigante al final del clip.
    Si allow_tail_pad es False, expande únicamente las pausas internas entre frases sin añadir colas de silencio al final.
    Soporta tensores de PyTorch y arrays de NumPy.
    """
    needed_pad = target_samples - arr.shape[-1]
    if needed_pad <= 0:
        return arr

    is_torch = hasattr(arr, "device") and hasattr(arr, "cpu")
    arr_np = arr.detach().cpu().numpy() if is_torch else arr

    # Si no se permite padding en la cola y no hay valles internos, no forzar ceros al final
    if not allow_tail_pad and needed_pad < int(0.08 * rate):
        return arr

    # Si el padding necesario es muy pequeño (<= 0.15s) y se permite padding final
    if allow_tail_pad and needed_pad < int(0.15 * rate):
        pad = np.zeros((arr_np.shape[0], needed_pad), dtype=arr_np.dtype)
        res_np = np.concatenate([arr_np, pad], axis=-1)
        return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np

    window_size = int(0.04 * rate)
    hop_size = int(0.02 * rate)
    total_samples = arr_np.shape[-1]

    if total_samples < window_size:
        pad = np.zeros((arr_np.shape[0], needed_pad), dtype=arr_np.dtype)
        res_np = np.concatenate([arr_np, pad], axis=-1)
        return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np

    mono = np.mean(arr_np, axis=0) if arr_np.shape[0] > 1 else arr_np[0]
    num_frames = (total_samples - window_size) // hop_size + 1
    if num_frames <= 0:
        pad = np.zeros((arr_np.shape[0], needed_pad), dtype=arr_np.dtype)
        res_np = np.concatenate([arr_np, pad], axis=-1)
        return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np

    frame_rms = np.zeros(num_frames, dtype=np.float32)
    for f in range(num_frames):
        start = f * hop_size
        chunk = mono[start:start + window_size]
        frame_rms[f] = np.sqrt(np.mean(chunk ** 2))

    max_rms = float(np.max(frame_rms))
    if max_rms < 1e-4:
        pad = np.zeros((arr_np.shape[0], needed_pad), dtype=arr_np.dtype)
        res_np = np.concatenate([arr_np, pad], axis=-1)
        return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np

    silence_threshold = max(0.005, max_rms * 0.08)
    is_silent = frame_rms < silence_threshold

    min_silence_frames = max(3, int(0.12 / 0.02))
    valleys = []
    start_f = None
    for f_idx, silent in enumerate(is_silent):
        if silent:
            if start_f is None:
                start_f = f_idx
        else:
            if start_f is not None:
                dur_frames = f_idx - start_f
                if dur_frames >= min_silence_frames:
                    mid_frame = start_f + dur_frames // 2
                    valleys.append(mid_frame * hop_size)
                start_f = None

    min_edge = int(0.35 * rate)
    valleys = [v for v in valleys if v > min_edge and v < (total_samples - min_edge)]

    if not valleys:
        if not allow_tail_pad:
            return arr
        pad = np.zeros((arr_np.shape[0], needed_pad), dtype=arr_np.dtype)
        res_np = np.concatenate([arr_np, pad], axis=-1)
        return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np

    limit_valley = max_per_valley if max_per_valley is not None else (int(0.35 * rate) if not allow_tail_pad else int(0.80 * rate))
    if allow_tail_pad:
        num_points = len(valleys) + 1
        valley_share = min(limit_valley, needed_pad // num_points)
        allocated_to_valleys = valley_share * len(valleys)
        end_share = needed_pad - allocated_to_valleys
    else:
        valley_share = min(limit_valley, needed_pad // len(valleys)) if valleys else 0
        end_share = 0

    fade_len = max(64, min(int(0.005 * rate), valley_share // 2 if valley_share > 0 else 64))
    fade_out = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
    fade_in = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)

    parts = []
    prev_idx = 0
    silence_chunk = np.zeros((arr_np.shape[0], valley_share), dtype=arr_np.dtype)
    for v_idx in valleys:
        chunk = arr_np[:, prev_idx:v_idx].copy()
        if prev_idx > 0 and chunk.shape[-1] >= fade_len:
            chunk[:, :fade_len] *= fade_in
        if chunk.shape[-1] >= fade_len:
            chunk[:, -fade_len:] *= fade_out
        parts.append(chunk)
        if valley_share > 0:
            parts.append(silence_chunk)
        prev_idx = v_idx

    chunk_last = arr_np[:, prev_idx:].copy()
    if prev_idx > 0 and chunk_last.shape[-1] >= fade_len:
        chunk_last[:, :fade_len] *= fade_in
    parts.append(chunk_last)

    if allow_tail_pad and end_share > 0:
        parts.append(np.zeros((arr_np.shape[0], end_share), dtype=arr_np.dtype))

    res_np = np.concatenate(parts, axis=-1)
    if allow_tail_pad:
        if res_np.shape[-1] < target_samples:
            extra = np.zeros((arr_np.shape[0], target_samples - res_np.shape[-1]), dtype=arr_np.dtype)
            res_np = np.concatenate([res_np, extra], axis=-1)
        elif res_np.shape[-1] > target_samples:
            res_np = res_np[:, :target_samples]

    return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np


def compact_silence_valleys(
    arr: Any,
    rate: int,
    target_samples: int,
    min_pause_sec: float = 0.12,
    target_pause_sec: float = 0.08,
) -> Any:
    """
    Comprime quirúrgicamente los valles de silencio internos (pausas entre oraciones / respiraciones)
    reduciendo el tiempo muerto sin alterar la velocidad ni el timbre de las partes habladas (1.00x natural).
    Aplica micro-fades de 5ms en cada unión para erradicar cualquier artefacto o 'tip' acústico.
    """
    if arr is None or arr.shape[-1] <= target_samples:
        return arr

    needed_reduction = arr.shape[-1] - target_samples
    if needed_reduction <= 0:
        return arr

    is_torch = hasattr(arr, "device") and hasattr(arr, "cpu")
    arr_np = arr.detach().cpu().numpy() if is_torch else arr

    window_size = int(0.04 * rate)
    hop_size = int(0.02 * rate)
    total_samples = arr_np.shape[-1]

    if total_samples < window_size * 2:
        return arr

    mono = np.mean(arr_np, axis=0) if arr_np.shape[0] > 1 else arr_np[0]
    num_frames = (total_samples - window_size) // hop_size + 1
    if num_frames <= 0:
        return arr

    frame_rms = np.zeros(num_frames, dtype=np.float32)
    for f in range(num_frames):
        start = f * hop_size
        chunk = mono[start:start + window_size]
        frame_rms[f] = np.sqrt(np.mean(chunk ** 2))

    max_rms = float(np.max(frame_rms))
    if max_rms < 1e-4:
        return arr

    silence_threshold = max(0.005, max_rms * 0.08)
    is_silent = frame_rms < silence_threshold

    min_frames = max(3, int(min_pause_sec / 0.02))
    valleys = []
    start_f = None
    for f_idx, silent in enumerate(is_silent):
        if silent:
            if start_f is None:
                start_f = f_idx
        else:
            if start_f is not None:
                dur_f = f_idx - start_f
                if dur_f >= min_frames:
                    v_start_sample = start_f * hop_size
                    v_end_sample = f_idx * hop_size
                    valleys.append((v_start_sample, v_end_sample))
                start_f = None

    # Proteger márgenes de inicio y fin (primeros y últimos 300ms)
    min_edge = int(0.30 * rate)
    valleys = [(vs, ve) for (vs, ve) in valleys if vs > min_edge and ve < (total_samples - min_edge)]

    if not valleys:
        return arr

    target_pause_samples = int(target_pause_sec * rate)
    reducible_samples_list = []
    for vs, ve in valleys:
        dur = ve - vs
        can_cut = max(0, dur - target_pause_samples)
        reducible_samples_list.append(can_cut)

    total_reducible = sum(reducible_samples_list)
    if total_reducible <= 0:
        return arr

    cut_ratio = min(1.0, needed_reduction / total_reducible)

    fade_len = max(64, int(0.005 * rate))  # 5ms de rampa suave
    fade_out = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
    fade_in = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)

    parts = []
    prev_idx = 0
    for (vs, ve), can_cut in zip(valleys, reducible_samples_list):
        cut_amount = int(round(can_cut * cut_ratio))
        keep_silence = (ve - vs) - cut_amount

        chunk_before = arr_np[:, prev_idx:vs].copy()
        if prev_idx > 0 and chunk_before.shape[-1] >= fade_len:
            chunk_before[:, :fade_len] *= fade_in
        if chunk_before.shape[-1] >= fade_len:
            chunk_before[:, -fade_len:] *= fade_out
        parts.append(chunk_before)

        if keep_silence > 0:
            parts.append(np.zeros((arr_np.shape[0], keep_silence), dtype=arr_np.dtype))

        prev_idx = ve

    chunk_last = arr_np[:, prev_idx:].copy()
    if prev_idx > 0 and chunk_last.shape[-1] >= fade_len:
        chunk_last[:, :fade_len] *= fade_in
    parts.append(chunk_last)

    res_np = np.concatenate(parts, axis=-1)

    return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np


def get_audio_file_duration(file_path: Path | str, fallback: Optional[float] = None) -> Optional[float]:
    """
    Obtiene la duración en segundos de un archivo de audio de forma robusta y rápida.
    Prueba sucesivamente: wave (estándar, 0 dependencias), soundfile, torchaudio.info y torchaudio.load.
    """
    p_str = str(file_path)
    # 1. wave (módulo estándar de Python, ultrarrápido para archivos WAV)
    try:
        import wave
        with wave.open(p_str, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate > 0 and frames > 0:
                return frames / float(rate)
    except Exception:
        pass

    # 2. soundfile (muy confiable en entornos Linux/Kaggle)
    try:
        import soundfile as sf
        info = sf.info(p_str)
        if info.duration > 0:
            return float(info.duration)
    except Exception:
        pass

    # 3. torchaudio.info (si está disponible y soportado en el build de PyTorch)
    try:
        if torchaudio is not None and hasattr(torchaudio, "info"):
            v_info = torchaudio.info(p_str)
            if getattr(v_info, "sample_rate", 0) > 0:
                return v_info.num_frames / float(v_info.sample_rate)
    except Exception:
        pass

    # 4. torchaudio.load (fallback leyendo cabecera/datos)
    try:
        if torchaudio is not None:
            arr, sr = torchaudio.load(p_str)
            if sr > 0:
                return arr.shape[-1] / float(sr)
    except Exception:
        pass

    print(f"⚠️ [Fallback Duración] No se pudo medir duración física de '{Path(file_path).name}', usando fallback={fallback}s.", flush=True)
    return fallback


def synthesize_segment_audio(
    text: str,
    lang: str,
    speaker: str,
    out_audio_path: Optional[Path | str] = None,
    raw_audio_path: Optional[Path | str] = None,
    phonemes: Optional[dict[str, str]] = None,
    speed: float = 1.0,
    target_duration: Optional[float] = None,
    orig_duration: Optional[float] = None,
    slowdown_range: Optional[Tuple[float, float]] = None,
    max_allowed_dur: Optional[float] = None,
    tts_fn: Optional[callable] = None,
    cached_arr_rate: Optional[Tuple[Any, int]] = None,
    **tts_kwargs,
) -> Tuple[Optional[Any], Optional[int], float, float, str]:
    """
    Función centralizada para sintetizar y procesar un segmento individual de audio TTS.

    1. Invoca tts_fn (o usa cached_arr_rate si fue precalculado en paralelo).
    2. Guarda copia intacta en raw_audio_path.
    3. Aplica ajuste de tempo, sincronía de duración o padding orgánico de respiros.
    4. Aplica micro-fade out de 5ms al final para evitar artefactos o clicks.
    5. Guarda el audio final en out_audio_path.

    Retorna: (arr, rate, raw_duration, final_duration, mode_tag)
    """
    if tts_fn is None:
        from src.tts import model_tts
        tts_fn = model_tts

    if cached_arr_rate is not None and cached_arr_rate[0] is not None:
        arr, rate = cached_arr_rate
    else:
        seg_kwargs = dict(tts_kwargs)
        if phonemes:
            from src.tts import normalize_pronunciation_dictionary
            seg_dict = normalize_pronunciation_dictionary(phonemes)
            if seg_dict:
                seg_kwargs["pronunciation_dictionary"] = seg_dict
        arr, rate = tts_fn(text, lang, speaker, **seg_kwargs)

    if arr is None or rate is None:
        return None, None, 0.0, 0.0, "error"

    raw_dur = float(arr.shape[-1]) / float(rate)

    if raw_audio_path and torchaudio is not None:
        raw_p = Path(raw_audio_path)
        raw_p.parent.mkdir(parents=True, exist_ok=True)
        torchaudio.save(str(raw_p), arr, sample_rate=rate)

    mode_tag = "✨ 1.00x (natural)"

    # Sincronía orgánica respecto al audio original (si slowdown_range y orig_duration están activos)
    if slowdown_range and orig_duration and orig_duration > 0:
        # 1. CASO OVERFLOW / RIESGO DE CHOQUE:
        # El audio excede el tiempo disponible antes del siguiente segmento
        if max_allowed_dur is not None and raw_dur > max_allowed_dur:
            # Primero intentar compactar quirúrgicamente los valles de silencio internos (respiros/pausas)
            arr_compact = compact_silence_valleys(arr, rate, int(max_allowed_dur * rate))
            compact_dur = float(arr_compact.shape[-1]) / float(rate)

            if compact_dur <= max_allowed_dur:
                arr = arr_compact
                gained_pct = max(1, int(round((1.0 - compact_dur / raw_dur) * 100)))
                mode_tag = f"✂️ 1.00x (-{gained_pct}%)"
            else:
                # Si aún excede, aplicar compresión de tempo para forzar que quepa sin chocar
                arr = arr_compact
                target_samples = int(max_allowed_dur * rate)
                ratio_needed = float(arr.shape[-1]) / float(target_samples)
                speed_str = f"⚡ {ratio_needed:.2f}x" if ratio_needed <= 1.25 else f"🔥 {ratio_needed:.2f}x"
                if (raw_dur - compact_dur) >= 0.05:
                    gained_pct = max(1, int(round((1.0 - compact_dur / raw_dur) * 100)))
                    mode_tag = f"{speed_str} + ✂️ (-{gained_pct}%)"
                else:
                    mode_tag = speed_str
                arr = adjust_audio_duration(arr, target_samples, rate)

        # 2. CASO EN QUE NO CHOCA CON EL SIGUIENTE SEGMENTO:
        else:
            ratio_slow = raw_dur / orig_duration
            diff_pct = int(round((ratio_slow - 1.0) * 100))
            diff_str = f"+{diff_pct}%" if diff_pct > 0 else f"{diff_pct}%" if diff_pct < 0 else "0%"

            # Margen Neutro y fidelidad temporal en Timeline:
            # Si ratio_slow >= 0.94: Mantener el audio 100% intacto a 1.00x, sin estirar y sin colas de silencio
            if ratio_slow >= 0.94:
                mode_tag = f"✨ 1.00x ({diff_str})"
            else:
                # Sub-duración (< 0.94x):
                # 1. Expandir suavemente valles internos de silencio (sin añadir silencio artificial al final del clip)
                target_samples = int(orig_duration * rate)
                arr_expanded = distribute_silence_padding(
                    arr, target_samples, rate, max_per_valley=int(0.35 * rate), allow_tail_pad=False
                )
                expanded_dur = float(arr_expanded.shape[-1]) / float(rate)
                expanded_ratio = expanded_dur / orig_duration

                if expanded_ratio >= 0.94:
                    arr = arr_expanded
                    mode_tag = f"✨ 1.00x (pausas +{int(round((expanded_ratio - ratio_slow) * 100))}%)"
                else:
                    arr = arr_expanded
                    # 2. Si aún después de expandir pausas internas sigue < 0.94x, piso estricto de 0.85x
                    # (máximo 15% de estiramiento suave imperceptible, nunca caer a 0.85x ni colas de ceros)
                    min_allowed_speed = 0.85
                    effective_speed = max(min_allowed_speed, expanded_ratio)
                    mode_tag = f"🔉 {effective_speed:.2f}x"
                    stretch_samples = int(arr.shape[-1] / effective_speed)
                    arr = adjust_audio_duration(arr, stretch_samples, rate)

    # Micro-fade out suave (5ms estándar) al final para eliminar ruidos de corte abrupto
    fade_len_5ms = max(16, min(int(0.005 * rate), arr.shape[-1]))
    if arr.shape[-1] >= fade_len_5ms and torch is not None:
        fade = torch.linspace(1.0, 0.0, fade_len_5ms, device=arr.device)
        arr = arr.clone()
        arr[:, -fade_len_5ms:] *= fade

    # Modo target_duration (fijar duración objetivo explícita)
    dur_after_sync = float(arr.shape[-1]) / float(rate)
    if target_duration is not None and target_duration > 0:
        raw_speed = dur_after_sync / target_duration
        effective_speed = max(0.5, min(raw_speed, 2.0))
        mode_tag = f"🎯 {effective_speed:.2f}x (target)"
        target_samples = int(target_duration * rate)
        arr = adjust_audio_duration(arr, target_samples, rate)
    elif speed is not None and abs(speed - 1.0) > 0.01 and speed > 0:
        target_samples = int(arr.shape[-1] / speed)
        mode_tag = f"🎛️ {speed:.2f}x (manual)"
        arr = adjust_audio_duration(arr, target_samples, rate)

    final_dur = float(arr.shape[-1]) / float(rate)

    if out_audio_path and torchaudio is not None:
        out_p = Path(out_audio_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        if out_p.suffix.lower() == ".m4a":
            tmp_wav = out_p.with_suffix(".tmp.wav")
            torchaudio.save(str(tmp_wav), arr, sample_rate=rate)
            cmd = [
                "ffmpeg", "-y", "-v", "error",
                "-i", str(tmp_wav),
                "-c:a", "aac", "-b:a", "192k",
                str(out_p),
            ]
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            except Exception as e:
                print(f"⚠️ [Fallback Audio] Falló codificación AAC (.m4a) para {out_p.name} ({e}), guardando como .wav.", flush=True)
                torchaudio.save(str(out_p.with_suffix(".wav")), arr, sample_rate=rate)
            finally:
                if tmp_wav.exists():
                    try:
                        tmp_wav.unlink()
                    except OSError:
                        pass
            old_wav = out_p.with_suffix(".wav")
            if old_wav.exists():
                try:
                    old_wav.unlink()
                except OSError:
                    pass
        else:
            torchaudio.save(str(out_p), arr, sample_rate=rate)

    return arr, rate, raw_dur, final_dur, mode_tag


def clone_voice_segments(
    path: Path,
    texts: list[dict],
    language: str,
    audio_ref: str | Path,
    tts_fn: callable,
    only_indices: Optional[list[int]] = None,
    slowdown_range: Optional[Tuple[float, float]] = None,
    speed: float = 1.0,
    target_duration: Optional[float] = None,
    speaker_map: Optional[dict[str, str]] = None,
    source_lang: Optional[str] = None,
    **kwargs,
) -> Tuple[list[Path], list[int], int]:
    seqs_src_dir = path.parent / "Seqs_src"
    seqs_trg_dir = path.parent / "Seqs_trg"
    seqs_trg_dir.mkdir(exist_ok=True)

    texts_to_process = (
        texts if only_indices is None else [texts[i - 1] for i in only_indices]
    )

    # Determinar idioma fuente (origen)
    src_lang = source_lang or kwargs.get("source_lang")
    if not src_lang and texts_to_process:
        src_lang = texts_to_process[0].get("source_lang") or texts_to_process[0].get("src_lang")
    if not src_lang:
        try:
            from src.result_store import load_result
            r_data = load_result(path.parent)
            if r_data:
                src_lang = r_data.get("source_lang")
        except Exception:
            pass
    if not src_lang:
        src_lang = "pt"

    times: list[int] = []
    path_es: list[Path] = []

    # Obtener duración total del video de forma exhaustiva y precisa
    video_total_duration: Optional[float] = None
    for cand_name in ["no_vocals.wav", "no_vocals.m4a", "vocals.wav"]:
        cand_p = path.with_name(cand_name)
        if cand_p.exists():
            d = get_audio_file_duration(cand_p)
            if d is not None and d > 0:
                video_total_duration = d
                break

    if video_total_duration is None and path.exists():
        video_total_duration = get_audio_file_duration(path)

    from concurrent.futures import ThreadPoolExecutor

    # Preparamos las tareas de TTS para ejecución concurrente
    tts_tasks = []
    for idx, text_dict in enumerate(texts_to_process):
        text = text_dict["text"]
        speaker = text_dict.get("speaker", "SPEAKER_00")
        orig_spk = text_dict.get("original_speaker") or speaker
        target_spk = (speaker_map.get(orig_spk) if speaker_map else None) or speaker

        from api.service import SPEAKER_OPTIONS
        seg_audio_ref = SPEAKER_OPTIONS.get(target_spk, target_spk) if target_spk else audio_ref
        if not seg_audio_ref:
            seg_audio_ref = audio_ref

        seq_num = only_indices[idx] if only_indices else idx + 1
        seg_phonemes = text_dict.get("phonemes") or {}
        tts_tasks.append((idx, text, seg_audio_ref, seq_num, seg_phonemes))

    # Si hay múltiples segmentos, paralelizamos las solicitudes HTTP (hasta 5 hilos)
    tts_results: dict[int, tuple] = {}
    if len(tts_tasks) > 1:
        max_workers = min(5, len(tts_tasks))
        def _fetch_tts(item):
            i, txt, voice_ref, s_num, s_phonemes = item
            try:
                seg_kwargs = dict(kwargs)
                if s_phonemes:
                    from src.tts import normalize_pronunciation_dictionary
                    seg_dict = normalize_pronunciation_dictionary(s_phonemes)
                    if seg_dict:
                        seg_kwargs["pronunciation_dictionary"] = seg_dict
                res = tts_fn(txt, language, voice_ref, **seg_kwargs)
                return i, res
            except Exception as ex:
                print(f"\n⚠️ Error en síntesis TTS #{s_num}: {ex}")
                return i, (None, None)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for i, res in executor.map(_fetch_tts, tts_tasks):
                tts_results[i] = res


    for idx, text_dict in enumerate(texts_to_process):
        text = text_dict["text"]
        start_time = float(text_dict["start"])
        speaker = text_dict.get("speaker", "SPEAKER_00")
        orig_spk = text_dict.get("original_speaker") or speaker
        target_spk = (speaker_map.get(orig_spk) if speaker_map else None) or speaker

        # Resolver voz específica del segmento si difiere de audio_ref
        from api.service import SPEAKER_OPTIONS
        seg_audio_ref = SPEAKER_OPTIONS.get(target_spk, target_spk) if target_spk else audio_ref
        if not seg_audio_ref:
            seg_audio_ref = audio_ref

        safe_speaker = str(target_spk).replace(" ", "_").replace("/", "_").replace("\\", "_")

        seq_num = only_indices[idx] if only_indices else idx + 1

        audio_en_path = seqs_src_dir / f"vocals_{seq_num:03d}.wav"
        if not audio_en_path.exists():
            print(f"⚠️ No se encontró: {audio_en_path}")
            continue

        arr_en, rate_en = torchaudio.load(str(audio_en_path))
        dur_en = arr_en.shape[-1] / rate_en

        # ─── BÚSQUEDA DEL PRÓXIMO SEGMENTO CRONOLÓGICO Y ESPACIO DISPONIBLE ───
        next_starts = [
            float(t["start"])
            for t in texts
            if float(t["start"]) > start_time + 0.01
        ]
        next_seg_start = min(next_starts) if next_starts else None

        # Límite máximo disponible antes de chocar o invadir silencios musicales
        if next_seg_start is not None:
            hard_limit = max(0.2, next_seg_start - start_time - 0.04)
        elif video_total_duration is not None:
            hard_limit = max(0.2, video_total_duration - start_time - 0.05)
        else:
            hard_limit = max(dur_en + 0.8, 2.0)

        # Para clips cortos (< 2.5s), permitimos margen elástico proporcional al silencio real disponible
        # evitando aceleraciones forzadas (ej. 1.27x en siglas o muletillas breves)
        if dur_en < 2.5:
            dynamic_slack = max(0.9, min(1.8, hard_limit - dur_en))
            max_allowed_dur = min(hard_limit, dur_en + dynamic_slack)
        else:
            max_allowed_dur = min(hard_limit, dur_en + 0.65)

        audio_es_path = seqs_trg_dir / f"tts_{safe_speaker}_{seq_num:03d}.m4a"
        raw_es_path = seqs_trg_dir / f"tts_{safe_speaker}_{seq_num:03d}_raw.wav"

        cached_tts = tts_results.get(idx)
        arr, rate, raw_dur_es, final_dur, mode_tag = synthesize_segment_audio(
            text=text,
            lang=language,
            speaker=seg_audio_ref,
            out_audio_path=audio_es_path,
            raw_audio_path=raw_es_path,
            phonemes=text_dict.get("phonemes"),
            speed=speed,
            target_duration=target_duration,
            orig_duration=dur_en,
            slowdown_range=slowdown_range,
            max_allowed_dur=max_allowed_dur,
            tts_fn=tts_fn,
            cached_arr_rate=cached_tts,
            **kwargs,
        )

        if arr is None or rate is None:
            continue

        # Actualizar metadatos del segmento: preservando las coordenadas del audio original intactas
        text_dict["orig_start"] = round(float(text_dict.get("orig_start", start_time)), 3)
        text_dict["orig_end"] = round(float(text_dict.get("orig_end", start_time + dur_en)), 3)
        text_dict["orig_duration"] = round(float(text_dict.get("orig_duration", dur_en)), 3)
        text_dict["start"] = round(start_time, 3)
        text_dict["end"] = round(start_time + final_dur, 3)
        text_dict["duration"] = round(final_dur, 3)

        # Línea métrica
        seq_col = f"{seq_num:>3d}. "

        if abs(final_dur - raw_dur_es) >= 0.05:
            dur_col = f"[orig: {dur_en:5.2f}s | fish: {raw_dur_es:5.2f}s ➔ {final_dur:5.2f}s]"
        else:
            dur_col = f"[orig: {dur_en:5.2f}s | fish: {raw_dur_es:5.2f}s]"
        print(f"{seq_col}{mode_tag}  {dur_col}")

        orig_text = str(text_dict.get("original_text", "")).strip()

        aligned_lines = _format_aligned_segment_texts(
            orig_text=orig_text,
            final_text=text,
            source_lang=src_lang,
        )
        for line in aligned_lines:
            print(line)
        print()

        path_es.append(audio_es_path)
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
