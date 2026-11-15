"""
Aplicación de una variación de segmentación sobre un video ya procesado.

Tres modos, con costes muy distintos:

- ``resync``: misma agrupación, márgenes nuevos. Re-corta `Seqs_src` y
  re-sincroniza el TTS desde el máster ``*_raw.wav``. Cero llamadas a Fish y a
  Gemini: segundos.
- ``regenerate_changed``: re-agrupa y solo re-traduce/re-sintetiza los segmentos
  cuyo texto de origen cambió. Los demás reutilizan su máster.
- ``regenerate_all``: re-agrupa, re-traduce y re-sintetiza todo.

Ninguna operación destruye el máster ``*_raw.wav``: se lee, se re-sincroniza y
se vuelve a escribir con el mismo contenido. El gate de QA se recalcula dentro
de `clone_voice_segments` y el TAR de segmentos se rehace al final.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from src.diarization import smart_group_segments_strict
from src.pacing import source_bounds
from src.result_store import (
    create_segment_entry,
    load_result,
    update_result_original_segments,
    update_result_segments,
)
from src.segmentation import SegmentationParams
from src.segmentation_preview import load_words, resolve_total_duration

VALID_MODES = ("resync", "regenerate_changed", "regenerate_all")

# `tts_{speaker}_{NNN}.m4a`, `tts_{speaker}_{NNN}_raw.wav`, `vocals_{NNN}.wav`.
# El nombre del hablante puede llevar guiones bajos, así que el índice se ancla
# al final del nombre y no se parte por `_`.
_SEQ_INDEX_RE = re.compile(r"_(\d{3})(?:_raw)?\.(?:m4a|wav)$")


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split())


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _contains_span(cur: Mapping[str, Any], prop: Mapping[str, Any], eps: float = 0.005) -> bool:
    """Indica si el tramo del segmento propuesto cae dentro del segmento actual."""
    old_start = float(cur.get("orig_start") or cur.get("start") or 0.0)
    old_end = float(cur.get("orig_end") or cur.get("end") or 0.0)
    new_start = float(prop.get("start") or 0.0)
    new_end = float(prop.get("end") or 0.0)
    return new_start >= old_start - eps and new_end <= old_end + eps


def _vocals_path(folder: Path) -> Path:
    for name in ("vocals.wav", "vocals.m4a"):
        candidate = folder / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No se encontró vocals.wav/vocals.m4a en la carpeta del video")


def _old_raw_path(folder: Path, seg: int) -> Path | None:
    seqs = folder / "Seqs_trg"
    if not seqs.exists():
        return None
    matches = sorted(seqs.glob(f"tts_*_{seg:03d}_raw.wav"))
    return matches[0] if matches else None


def _build_proposed(
    folder: Path,
    params: SegmentationParams,
) -> tuple[list[dict], list[dict], str]:
    result = load_result(folder) or {}
    current = result.get("segments") or []
    words, words_source = load_words(folder)
    if not words:
        raise ValueError("No hay transcripción por palabra para este video")
    total = resolve_total_duration(result, words, current)
    grouped = smart_group_segments_strict(
        [{"speaker": words[0].get("speaker", ""), "words": words}],
        params=params,
    )
    if not grouped:
        raise ValueError("La variación no produjo ningún segmento")
    times = [(float(seg["start"]), float(seg["end"])) for seg in grouped]
    proposed = []
    for idx, seg in enumerate(grouped):
        src_start, src_end = source_bounds(times, idx, total, params)
        proposed.append(
            {
                "start": round(float(seg["start"]), 3),
                "end": round(float(seg["end"]), 3),
                "src_start": src_start,
                "src_end": src_end,
                "text": str(seg.get("text", "")),
                "speaker": str(seg.get("speaker", "")),
            }
        )
    return proposed, words, words_source


def _match_reuse(
    mode: str,
    current: list[dict],
    proposed: list[dict],
) -> dict[int, int]:
    """
    Devuelve ``{índice_propuesto: índice_actual}`` de los segmentos que pueden
    reutilizar su traducción y su máster.

    El emparejamiento es por texto de origen normalizado, y entre candidatos
    repetidos gana el que más solape temporal tiene: las repeticiones reales del
    ASR no deben cruzarse entre sí.
    """
    if mode == "regenerate_all":
        return {}

    if mode == "resync":
        if len(current) != len(proposed):
            raise ValueError(
                "Re-sincronizar no puede cambiar el número de segmentos; "
                "usa «Regenerar lo que cambia» o «Regenerar todo»."
            )
        for idx, (cur, prop) in enumerate(zip(current, proposed)):
            if _norm(cur.get("original_text") or cur.get("text")) != _norm(prop["text"]):
                raise ValueError(
                    "Re-sincronizar no puede cambiar la agrupación; "
                    "usa «Regenerar lo que cambia» o «Regenerar todo»."
                )
        return {i: i for i in range(len(proposed))}

    # regenerate_changed
    by_text: dict[str, list[int]] = {}
    for idx, seg in enumerate(current):
        by_text.setdefault(_norm(seg.get("original_text") or seg.get("text")), []).append(idx)

    reuse: dict[int, int] = {}
    used: set[int] = set()
    for prop_idx, prop in enumerate(proposed):
        key = _norm(prop["text"])
        best: int | None = None
        best_overlap = -1.0
        for cand in by_text.get(key) or []:
            if cand in used:
                continue
            cur = current[cand]
            overlap = _overlap(
                prop["start"],
                prop["end"],
                float(cur.get("orig_start", cur.get("start", 0.0))),
                float(cur.get("orig_end", cur.get("end", 0.0))),
            )
            if overlap > best_overlap:
                best_overlap = overlap
                best = cand
        if best is not None:
            used.add(best)
            reuse[prop_idx] = best
    return reuse


def _translate_new(
    entries: list[dict],
    new_indices: list[int],
    target_lang: str,
    source_lang: str,
    total_duration: float,
) -> None:
    if not new_indices:
        return

    from src.lang_utils import same_language

    source_texts = [entries[i]["original_text"] for i in new_indices]
    if not target_lang or same_language(source_lang, target_lang):
        for i, text in zip(new_indices, source_texts):
            entries[i]["text"] = text
        return

    from src.translation import translate_text_list

    # El presupuesto de cada segmento nuevo se mide contra su propio habla; los
    # vecinos reutilizados no viajan en esta llamada, así que el margen se queda
    # en el tope configurado en vez de repartirse con ellos.
    times = [(entries[i]["start"], entries[i]["end"]) for i in new_indices]
    translated = translate_text_list(
        source_texts,
        target_lang=target_lang,
        source_lang=source_lang,
        times=times,
        total_duration=total_duration,
        segments_meta=[entries[i] for i in new_indices],
    )
    if not translated or len(translated) != len(new_indices):
        raise RuntimeError("La traducción de los segmentos nuevos falló")
    for i, text in zip(new_indices, translated):
        entries[i]["text"] = text


def _load_cached_arrays(folder: Path, reuse: Mapping[int, int], current: list[dict]) -> dict[int, tuple]:
    if not reuse:
        return {}

    import torchaudio

    cached: dict[int, tuple] = {}
    missing: list[int] = []
    for prop_idx, cur_idx in reuse.items():
        old_seg = int(current[cur_idx].get("seg") or cur_idx + 1)
        raw = _old_raw_path(folder, old_seg)
        if raw is None:
            missing.append(old_seg)
            continue
        arr, rate = torchaudio.load(str(raw))
        cached[prop_idx + 1] = (arr, rate)
    if missing:
        raise FileNotFoundError(
            "Faltan másters _raw.wav para los segmentos "
            + ", ".join(f"#{n}" for n in missing)
            + ". Usa «Regenerar todo» para volver a sintetizarlos."
        )
    return cached


def _seq_index(path: Path) -> int | None:
    match = _SEQ_INDEX_RE.search(path.name)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _cleanup_stale(folder: Path, keep_count: int) -> None:
    """
    Borra los audios de índices que ya no existen.

    `clone_voice_segments` reescribe el máster ``*_raw.wav`` en el índice nuevo,
    así que solo se eliminan los índices por encima del recuento actual; los
    másters de índices vivos se conservan intactos.
    """
    for directory, patterns in (
        (folder / "Seqs_trg", ("tts_*_*.m4a", "tts_*_*_raw.wav")),
        (folder / "Seqs_src", ("vocals_*.wav",)),
    ):
        if not directory.exists():
            continue
        for pattern in patterns:
            for path in directory.glob(pattern):
                idx = _seq_index(path)
                if idx is None or idx <= keep_count:
                    continue
                try:
                    path.unlink()
                except OSError:
                    pass


def apply_segmentation(
    folder: Path,
    overrides: Mapping[str, Any] | None,
    mode: str,
) -> dict[str, Any]:
    """
    Aplica la variación y devuelve el resumen. Escribe `result.json`, los audios
    y el reporte de QA; no toca el timeline (lo reconstruye el frontend).
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Modo inválido: {mode}")

    params = SegmentationParams().with_overrides(overrides)
    result = load_result(folder) or {}
    current = result.get("segments") or []
    if not current:
        raise ValueError("result.json no tiene segmentos")

    proposed, words, words_source = _build_proposed(folder, params)
    reuse = _match_reuse(mode, current, proposed)
    total_duration = resolve_total_duration(result, words, current)

    source_lang = str(result.get("source_lang") or "")
    target_lang = str(result.get("target_lang") or source_lang or "")

    # Mapa de voz derivado de lo que ya existe: conserva la asignación por hablante
    # sin necesitar el `speaker_map` original, que no se guarda en result.json.
    voice_by_original: dict[str, str] = {}
    for seg in current:
        orig = str(seg.get("original_speaker") or "")
        voice = str(seg.get("speaker") or "")
        if orig and voice and orig not in voice_by_original:
            voice_by_original[orig] = voice

    entries: list[dict] = []
    new_indices: list[int] = []
    carried_phonemes: set[int] = set()
    for prop_idx, prop in enumerate(proposed):
        cur_idx = reuse.get(prop_idx)
        if cur_idx is not None:
            cur = current[cur_idx]
            text = str(cur.get("text") or cur.get("original_text") or prop["text"])
            original_text = str(cur.get("original_text") or prop["text"])
            speaker = str(cur.get("speaker") or voice_by_original.get(prop["speaker"], prop["speaker"]))
            original_speaker = str(cur.get("original_speaker") or prop["speaker"])
            phonemes = cur.get("phonemes") or {}
            # Un diccionario manual solo viaja si el tramo del segmento nuevo está
            # contenido en el viejo: si el corte se amplió, las palabras añadidas
            # quedarían con la pronunciación de otra frase.
            if phonemes and _contains_span(cur, prop):
                carried_phonemes.add(cur_idx)
            else:
                phonemes = {}
        else:
            text = ""
            original_text = prop["text"]
            phonemes = {}
            original_speaker = prop["speaker"]
            speaker = voice_by_original.get(original_speaker, original_speaker)
            new_indices.append(prop_idx)

        entries.append(
            {
                "seg": prop_idx + 1,
                "start": prop["start"],
                "end": prop["end"],
                "orig_start": prop["start"],
                "orig_end": prop["end"],
                "orig_duration": round(prop["end"] - prop["start"], 3),
                "src_start": prop["src_start"],
                "src_end": prop["src_end"],
                "text": text,
                "original_text": original_text,
                "speaker": speaker,
                "original_speaker": original_speaker,
                "phonemes": phonemes,
            }
        )

    _translate_new(entries, new_indices, target_lang, source_lang, total_duration)

    cached_arrays = _load_cached_arrays(folder, reuse, current)

    from src.audio_utils import clone_voice_segments
    from src.pipeline import split_audio_sequences
    from src.tts import model_tts

    vocals = _vocals_path(folder)
    # `split_audio_sequences` reescribe `src_start`/`src_end` con la duración real
    # del audio de voces: son los bordes definitivos del clip de origen.
    split_audio_sequences(vocals, entries, params=params)

    audio_ref = entries[0]["speaker"] if entries else ""
    clone_voice_segments(
        vocals,
        entries,
        target_lang or source_lang,
        audio_ref,
        model_tts,
        cached_arrays=cached_arrays,
        auto_emotions=False,
        source_lang=source_lang,
    )

    saved_segments = [
        create_segment_entry(
            seg=e["seg"],
            start=e["start"],
            end=e["end"],
            text=e["text"],
            original_text=e["original_text"],
            speaker=e["speaker"],
            original_speaker=e["original_speaker"],
            phonemes=e.get("phonemes"),
            orig_start=e["orig_start"],
            orig_end=e["orig_end"],
            orig_duration=e["orig_duration"],
            src_start=e["src_start"],
            src_end=e["src_end"],
        )
        for e in entries
    ]
    update_result_segments(folder, saved_segments)

    # `Seqs_src` se ha vuelto a cortar con la nueva agrupación: la pista original
    # del timeline se reconstruye con estos mismos tramos, no con los de antes.
    original_segments = [
        create_segment_entry(
            seg=e["seg"],
            start=e["orig_start"],
            end=e["orig_end"],
            text=e["original_text"],
            original_text=e["original_text"],
            speaker=e["original_speaker"],
            original_speaker=e["original_speaker"],
            orig_start=e["orig_start"],
            orig_end=e["orig_end"],
            orig_duration=e["orig_duration"],
            src_start=e["src_start"],
            src_end=e["src_end"],
        )
        for e in entries
    ]
    update_result_original_segments(folder, original_segments)

    _cleanup_stale(folder, len(entries))

    try:
        from api.routes.files import ensure_audio_segments_tar, ensure_src_audio_segments_tar

        ensure_audio_segments_tar(folder)
        ensure_src_audio_segments_tar(folder)
    except Exception as exc:
        print(f"⚠️ No se pudo re-empaquetar el TAR de segmentos: {exc}")

    phonemes_dropped = sum(
        1
        for idx, seg in enumerate(current)
        if seg.get("phonemes") and idx not in carried_phonemes
    )

    return {
        "mode": mode,
        "words_source": words_source,
        "params": params.as_dict(),
        "segments": saved_segments,
        "summary": {
            "count": len(saved_segments),
            "reused": len(reuse),
            "retranslated": len(new_indices),
            "resynthesized": len(entries) - len(cached_arrays),
            "phonemes_dropped": phonemes_dropped,
        },
        "qa": (load_result(folder) or {}).get("qa") or {},
    }
