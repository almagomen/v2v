"""
Interfaz Gradio para la pipeline Video2Video.
Uso: python app_gradio.py (local) o desde Colab con demo.launch(share=True).
"""
import io
import queue
import sys
import threading
from pathlib import Path
import zipfile
import pickle

import gradio as gr
import pandas as pd
import torchaudio
from IPython.display import Audio, display
from src.config import QUEUE_DIR, TEMP_DIR

# Mapeo speaker: nombre en UI -> voice_id LMNT o nombre de voz
SPEAKER_OPTIONS = {
    "mrbeast_lmnt": "d47094be-9814-4323-9000-e735e04d8732",
    "Dionisio Schuyler": "Dionisio Schuyler",
    "en-US-AndrewMultilingualNeural": "en-US-AndrewMultilingualNeural",
    "Chatterbox": "Chatterbox",
}


class QueueWriter(io.TextIOBase):
    """Escribe en una cola para que el log se consuma en tiempo real."""
    def __init__(self, log_queue: queue.Queue):
        self._queue = log_queue

    def write(self, s: str) -> int:
        if s:
            self._queue.put(s)
        return len(s)

    def flush(self) -> None:
        pass


def _run_pipeline_core(
    urls: list[str],
    translate_lang: str | None,
    speaker_name: str,
) -> list[Path]:
    """
    Lógica de la pipeline. Debe ejecutarse con sys.stdout ya reemplazado por QueueWriter.
    Returns: lista de paths de videos renderizados.
    """
    from src.config import TEMP_DIR
    from src.pipeline import process_video_queue, split_all_sequences
    from src.audio_utils import clone_voice_segments, merge_cloned_audio
    from src.render import render_video
    from src.tts import model_tts

    import torchaudio

    print("📥 Descargando y transcribiendo... \n")
    speaker_audio = SPEAKER_OPTIONS.get(speaker_name, speaker_name)
    results = process_video_queue(urls, translate_lang=translate_lang)
    if not results:
        print("❌ No se pudo procesar ningún video.")
        return []

    output_paths: list[Path] = []
    
    for idx, r in enumerate(results):
        path = r["path"]
        texts = r["texts"]
        output_name = r["output_name"]
        transcription = r["transcription"]
        lang = translate_lang if translate_lang else transcription.language
        
        # El nombre final del video según render.py
        output_video_path = path.parent / f"{output_name}.mp4"

        # --- Lógica de Caché para Clonado y Renderizado ---
        if output_video_path.exists():
            print(f"✅ Video final ya existe en caché: {output_video_path.name}")
            output_paths.append(output_video_path)
            continue
        # -------------------------------------------------

        print("\n🚀 Inferencia iniciada...\n")

        # Dividir audio en secuencias (no imprime nada extra)
        split_all_sequences([path])

        # Log principal por video
        print(f"🎙️ Clonando voz: {path.stem}  [{idx + 1}/{len(results)}]")
        paths_es, times, freq = clone_voice_segments(
            path,
            texts,
            lang,
            speaker_audio,
            model_tts,
            slowdown_range=(0.5, 0.8),
            stretch_target_ratio=0.85,
        )

        if not paths_es:
            print("❌ No se generaron segmentos de audio.")
            continue

        vocals_es_path = path.with_name("vocals_es.wav")
        merged = merge_cloned_audio(
            path.with_name("vocals.wav"),
            paths_es,
            times,
            freq,
        )
        torchaudio.save(str(vocals_es_path), merged, freq)

        no_vocals_path = path.with_name("no_vocals.wav")
        if not no_vocals_path.exists():
            print("❌ No se encontró no_vocals.wav")
            continue

        print("🎬 Renderizando video...")
        # Guardar en la misma carpeta que el video original para que result.pkl sea accesible
        output_path = render_video(path, output_name, vocals_es_path, no_vocals_path, output_dir=path.parent)
        output_paths.append(output_path)
        print("=" * 60 + "\n")

    n = len(output_paths)
    if n:
        print(f"✅ Proceso Completado [{n}/{len(results)}]")
    return output_paths


def _worker(
    urls: list[str],
    translate_lang: str | None,
    speaker_name: str,
    log_queue: queue.Queue,
    result_queue: queue.Queue,
) -> None:
    old_stdout = sys.stdout
    try:
        sys.stdout = QueueWriter(log_queue)
        paths = _run_pipeline_core(urls, translate_lang, speaker_name)
        result_queue.put((paths,))
    except Exception as e:
        import traceback
        sys.stdout.write(traceback.format_exc() + f"\n❌ Error: {e}\n")
        result_queue.put(([],))
    finally:
        sys.stdout = old_stdout
        log_queue.put(None)


def process_streaming(
    url_input: str,
    translate_lang: str,
    speaker_name: str,
    progress: gr.Progress | None = None,
):
    """
    Handler generador: ejecuta la pipeline en un hilo y va devolviendo el log en vivo.
    """
    urls = [u.strip() for u in url_input.strip().splitlines() if u.strip()]
    if not urls:
        yield "❌ Introduce al menos una URL de YouTube (una por línea).", gr.update(), None, None, gr.update()
        return

    translate = None if translate_lang == "None" or not translate_lang else translate_lang

    log_queue: queue.Queue = queue.Queue()
    result_queue: queue.Queue = queue.Queue()

    thread = threading.Thread(
        target=_worker,
        args=(urls, translate, speaker_name, log_queue, result_queue),
    )
    thread.start()

    if progress is not None:
        progress(0, desc="Iniciando...")

    log_parts: list[str] = []
    step = 0
    spinner = ("◐", "◓", "◑", "◒")
    while True:
        try:
            item = log_queue.get(timeout=0.05)
        except queue.Empty:
            if not thread.is_alive():
                break
            # Animación ASCII por fase (descarga, separación, transcripción, traducción, inferencia)
            step += 1
            spin = spinner[step % 4]
            current_log = "".join(log_parts)
            if "🚀 Inferencia iniciada..." in current_log and "✅ Inferencia Completada" not in current_log:
                label = "Inferencia en curso..."
            elif "🔤 Traduciendo texto con Gemini..." in current_log:
                label = "Traduciendo texto..."
            elif "📝 Transcribiendo audio (Whisper + diarización)..." in current_log:
                label = "Transcribiendo audio..."
            elif "🎧 Separando audio (BS-RoFormer)" in current_log:
                label = "Separando audio..."
            elif "📥 Descargando y transcribiendo..." in current_log:
                label = "Descargando y transcribiendo..."
            else:
                label = "Preparando pipeline..."
            yield current_log + f"\n\n{spin} {label}", gr.update(), None, None, gr.update()
            continue
        if item is None:
            break
        log_parts.append(item)
        current_log = "".join(log_parts)
        step += 1
        if progress is not None and step % 20 == 0:
            progress(min(0.95, step * 0.01), desc="Procesando...")
        yield current_log, gr.update(), None, None, gr.update()

    try:
        output_paths, = result_queue.get(timeout=1.0)
    except queue.Empty:
        output_paths = []

    thread.join()
    final_log = "".join(log_parts)

    if progress is not None:
        progress(1, desc="Completado")

    if not output_paths:
        yield final_log, gr.update(), None, None, gr.update()
        return

    # Guardar lista de paths para descarga individual y como .zip
    str_paths = [str(p) for p in output_paths]
    choices = [(Path(p).name, str(p)) for p in str_paths]
    first_path = str_paths[0]
    yield (
        final_log,
        gr.update(choices=choices, value=first_path),
        first_path,
        str_paths,
        gr.update(interactive=True),
    )


def _zip_videos(paths: list[str] | None) -> str | None:
    """Crea un zip con todos los videos inferidos y devuelve su path."""
    if not paths:
        return None
    from src.config import TEMP_DIR

    zip_path = TEMP_DIR / "videos_inferidos.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            p_path = Path(p)
            if p_path.exists():
                zf.write(p_path, arcname=p_path.name)
    return str(zip_path)


def load_texts_df(video_path: str):
    """Carga los textos desde result.pkl y los convierte a formato de DataFrame."""
    if not video_path: 
        return pd.DataFrame(columns=["Seg", "Inicio", "Final", "Texto"]), gr.update(interactive=False)
    
    p = Path(video_path)
    pkl_path = p.with_name("result.pkl")
    
    if not pkl_path.exists():
        print(f"⚠️ No se encontró result.pkl en: {pkl_path}")
        return pd.DataFrame(columns=["Seg", "Inicio", "Final", "Texto"]), gr.update(interactive=False)

    try:
        with open(pkl_path, "rb") as f:
            data_pkl = pickle.load(f)
            texts = data_pkl[0]

        data = []
        for idx, t in enumerate(texts, 1):
            data.append([idx, f"{t['start']:.2f}", f"{t['end']:.2f}", t['text']])

        df = pd.DataFrame(data, columns=["Seg", "Inicio", "Final", "Texto"])
        return df, gr.update(interactive=True)
    except Exception as e:
        print(f"❌ Error cargando textos desde {pkl_path}: {e}")
        return pd.DataFrame(columns=["Seg", "Inicio", "Final", "Texto"]), gr.update(interactive=False)


def regenerate_single_segment(video_path: str, df: pd.DataFrame, row_idx: int | None, translate_lang: str, speaker_name: str):
    """Regenera y devuelve el audio de un único segmento seleccionado."""
    if not video_path or df is None or row_idx is None:
        return None, "⚠️ Selecciona una fila en la tabla primero."

    from src.pipeline import split_audio_sequences
    from src.audio_utils import clone_voice_segments
    from src.tts import model_tts

    p = Path(video_path)
    pkl_path = p.with_name("result.pkl")
    if not pkl_path.exists(): return None, "❌ result.pkl no encontrado."

    with open(pkl_path, "rb") as f:
        texts_original, _, _, _, _, _ = pickle.load(f)

    try:
        row = df.iloc[row_idx]
        seg_num = int(row["Seg"])
        t_edit = {
            "start": float(row["Inicio"]),
            "end": float(row["Final"]),
            "text": str(row["Texto"]),
            "speaker": texts_original[seg_num-1].get("speaker", "SPEAKER_00")
        }
    except Exception as e:
        return None, f"❌ Error en los datos del segmento: {e}"

    # Usar una lista temporal para que split_audio_sequences encuentre el índice correcto
    # y use los tiempos (start/end) actualizados de la tabla
    texts_for_split = list(texts_original)
    texts_for_split[seg_num - 1] = t_edit
    split_audio_sequences(p.with_name('vocals.wav'), texts_for_split, edit_indices=[seg_num])

    speaker_audio = SPEAKER_OPTIONS.get(speaker_name, speaker_name)
    lang = translate_lang if translate_lang and translate_lang != "None" else "es" # fallback

    # Regenerar solo este segmento
    paths_es, _, _ = clone_voice_segments(
        p,
        texts_for_split,
        lang,
        speaker_audio,
        model_tts,
        only_indices=[seg_num],
        slowdown_range=(0.5, 0.8),
        stretch_target_ratio=0.85,
    )

    if not paths_es:
        return None, "❌ No se pudo generar el audio."

    return str(paths_es[0]), f"✅ Segmento {seg_num} regenerado correctamente."


def regenerate_edited_video(video_path: str, df: pd.DataFrame, translate_lang: str, speaker_name: str, progress=gr.Progress()):
    """
    Finaliza la edición: verifica si hay cambios pendientes, actualiza metadatos,
    hace merge de todos los audios y renderiza el video final.
    """
    if not video_path or df is None or df.empty:
        return None, "❌ Error: Video no seleccionado o datos vacíos."

    from src.pipeline import split_audio_sequences
    from src.audio_utils import clone_voice_segments, merge_cloned_audio
    from src.render import render_video
    from src.tts import model_tts

    p = Path(video_path)
    pkl_path = p.with_name("result.pkl")
    if not pkl_path.exists(): return None, "❌ result.pkl no encontrado."

    progress(0.1, desc="Analizando cambios finales...")
    with open(pkl_path, "rb") as f:
        texts_original, output_name, url, result, transcription, diarization = pickle.load(f)

    changed_indices = []
    texts_edited = []

    for i, row in df.iterrows():
        idx = int(row["Seg"])
        t_edit = {
            "start": float(row["Inicio"]),
            "end": float(row["Final"]),
            "text": str(row["Texto"]),
            "speaker": texts_original[idx-1].get("speaker", "SPEAKER_00")
        }
        texts_edited.append(t_edit)
        if str(texts_original[idx-1]) != str(t_edit):
            changed_indices.append(idx)

    # Si hay cambios detectados que NO han sido regenerados individualmente todavía, los regeneramos ahora
    if changed_indices:
        progress(0.3, desc=f"Regenerando {len(changed_indices)} segmentos pendientes...")
        # Usar texts_edited para que el slicing use los nuevos tiempos de inicio/fin
        split_audio_sequences(p.with_name('vocals.wav'), texts_edited, edit_indices=changed_indices)
        speaker_audio = SPEAKER_OPTIONS.get(speaker_name, speaker_name)
        lang = translate_lang if translate_lang and translate_lang != "None" else transcription.language

        clone_voice_segments(
            p, texts_edited, lang, speaker_audio, model_tts,
            only_indices=changed_indices, slowdown_range=(0.5, 0.8), stretch_target_ratio=0.85
        )

    progress(0.6, desc="Consolidando cambios y renderizando...")
    with open(pkl_path, "wb") as f:
         pickle.dump((texts_edited, output_name, url, result, transcription, diarization), f)

    seqs_trg_dir = p.parent / 'Seqs_trg'
    all_paths_es = sorted(seqs_trg_dir.glob("*.wav"))
    
    # Obtener freq de uno cualquiera
    _, freq = torchaudio.load(str(all_paths_es[0]))
    all_times = [int(t['start'] * freq) for t in texts_edited]

    vocals_es_path = p.with_name("vocals_es.wav")
    merged = merge_cloned_audio(p.with_name("vocals.wav"), all_paths_es, all_times, freq)
    torchaudio.save(str(vocals_es_path), merged, freq)

    no_vocals_path = p.with_name("no_vocals.wav")
    output_video = render_video(p, output_name, vocals_es_path, no_vocals_path, output_dir=p.parent)

    progress(1.0, desc="✅ Video final listo")
    return str(output_video), "✅ Cambios aplicados y video final regenerado."


def build_demo():
    with gr.Blocks(title="Video2Video", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🎬 Video2Video – Traducción y doblaje con IA")

        with gr.Row():
            url_in = gr.Textbox(
                label="URLs de YouTube (una por línea)",
                placeholder="https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/watch?v=...",
                lines=5,
            )
        with gr.Row():
            translate_in = gr.Dropdown(
                label="Idioma de traducción",
                choices=["None", "es", "pt", "en", "fr", "de", "it"],
                value="es",
            )
            speaker_in = gr.Dropdown(
                label="Voz / Speaker",
                choices=list(SPEAKER_OPTIONS.keys()),
                value="mrbeast_lmnt",
            )
        btn = gr.Button("Procesar", variant="primary")

        log_out = gr.Textbox(label="Log", lines=12, interactive=False)

        with gr.Row():
            with gr.Column(scale=2):
                video_out = gr.Video(label="Vista previa", height=720)
            with gr.Column(scale=1):
                video_selector = gr.Dropdown(
                    label="Elegir video",
                    choices=[],
                    value=None,
                    interactive=True,
                )
                download_all_btn = gr.DownloadButton("Descargar todos (.zip)", interactive=False, variant="secondary")
        
        with gr.Accordion("✏️ Editar Segmentos y Tiempos", open=False):
            gr.Markdown("Haz clic en una fila de la tabla para seleccionarla. Luego puedes regenerar/probar ese audio individualmente o aplicar todos los cambios al final.")
            selected_row_index = gr.State(None)
            
            texts_df = gr.Dataframe(
                headers=["Seg", "Inicio", "Final", "Texto"],
                datatype=["number", "number", "number", "str"],
                col_count=(4, "fixed"),
                interactive=True,
                wrap=True,
                column_widths=["10%", "15%", "15%", "60%"]
            )
            
            with gr.Row():
                regen_segment_btn = gr.Button("🎧 Regenerar y Escuchar Segmento Seleccionado", variant="secondary")
                segment_preview_audio = gr.Audio(label="Vista previa audio", type="filepath", interactive=False, autoplay=True)
            
            gr.Markdown("---")
            regen_btn = gr.Button("🚀 Aplicar todos los cambios y Generar Video Final", interactive=False, variant="primary")
            regen_status = gr.Textbox(label="Estado", show_label=False, interactive=False)

        videos_state = gr.State([])

        def on_select_video(path):
            if path and Path(path).exists():
                return path
            return None

        video_selector.change(
            fn=on_select_video,
            inputs=[video_selector],
            outputs=[video_out],
        ).then(
            fn=load_texts_df,
            inputs=[video_selector],
            outputs=[texts_df, regen_btn],
        )

        def get_row_index(evt: gr.SelectData):
            """Captura el índice de la fila seleccionada en el dataframe."""
            if evt is not None and evt.index is not None:
                return evt.index[0]
            return None

        # Capturar el índice de la fila seleccionada
        texts_df.select(
            fn=get_row_index,
            outputs=[selected_row_index]
        )

        regen_segment_btn.click(
            fn=regenerate_single_segment,
            inputs=[video_selector, texts_df, selected_row_index, translate_in, speaker_in],
            outputs=[segment_preview_audio, regen_status]
        )

        regen_btn.click(
            fn=regenerate_edited_video,
            inputs=[video_selector, texts_df, translate_in, speaker_in],
            outputs=[video_out, regen_status]
        )

        download_all_btn.click(
            fn=_zip_videos,
            inputs=[videos_state],
            outputs=[download_all_btn],
        )

        btn.click(
            fn=process_streaming,
            inputs=[url_in, translate_in, speaker_in],
            outputs=[log_out, video_selector, video_out, videos_state, download_all_btn],
        )

    return demo


demo = build_demo()

if __name__ == "__main__":
    # En Colab usar demo.launch(share=True) para enlace público
    # Añadimos allowed_paths para que Gradio pueda acceder a los videos en Queue y temp
    demo.launch(
        share=False, 
        allowed_paths=[str(QUEUE_DIR), str(TEMP_DIR)]
    )