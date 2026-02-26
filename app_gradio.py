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
    print("\n🚀 Inferencia iniciada...\n")

    for idx, r in enumerate(results):
        path = r["path"]
        texts = r["texts"]
        output_name = r["output_name"]
        transcription = r["transcription"]
        lang = translate_lang if translate_lang else transcription.language

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
        output_path = render_video(path, output_name, vocals_es_path, no_vocals_path)
        output_paths.append(output_path)
        print("=" * 60 + "\n")

    n = len(output_paths)
    if n:
        print(f"✅ Inferencia Completada [{n}/{len(results)}]")
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


def find_changed_segments(original_texts: list[dict], edited_texts: list[dict]) -> list[int]:
    """Encuentra los índices (1-indexed) de los segmentos que han cambiado."""
    changed = []
    for idx, (orig, edit) in enumerate(zip(original_texts, edited_texts), 1):
        if str(orig) != str(edit):
            changed.append(idx)
    return changed


def _regenerate_worker(
    path: str,
    edited_data: list[list],
    speaker_name: str,
    translate_lang: str,
    log_queue: queue.Queue,
    result_queue: queue.Queue,
):
    old_stdout = sys.stdout
    try:
        sys.stdout = QueueWriter(log_queue)
        
        path_obj = Path(path)
        with open(path_obj.with_name('result.pkl'), 'rb') as f:
            original_texts, output_name, url, result, transcription, diarization = pickle.load(f)

        # Reconstruir textos a partir de la tabla (edited_data formato lista de listas)
        edited_texts = []
        for row in edited_data:
            edited_texts.append({
                'start': float(row[0]),
                'end': float(row[1]),
                'text': str(row[2]),
                'speaker': str(row[3])
            })

        changed_indices = find_changed_segments(original_texts, edited_texts)
        if not changed_indices:
            print("✅ No hay cambios detectados")
            result_queue.put((str(path_obj),))
            return

        print(f"🔄 Regenerando {len(changed_indices)} segmento(s): {changed_indices}\n")

        from src.pipeline import split_audio_sequences
        from src.audio_utils import clone_voice_segments, merge_cloned_audio
        from src.render import render_video
        from src.tts import model_tts
        import torchaudio

        speaker_audio = SPEAKER_OPTIONS.get(speaker_name, speaker_name)
        lang = translate_lang if translate_lang and translate_lang != "None" else transcription.language

        # Dividir secuencias de audio originales
        print("🎙️ Extrayendo audios originales...")
        split_audio_sequences(
            audio_path=path_obj.with_name('vocals.wav'),
            texts=edited_texts,
            edit_indices=changed_indices
        )

        # Clonar voz para los segmentos modificados
        print("\n🎙️ Generando nuevas voces...")
        paths_es, times, freq = clone_voice_segments(
            path_obj,
            edited_texts,
            lang,
            speaker_audio,
            model_tts,
            only_indices=changed_indices,
            slowdown_range=(0.5, 0.8),
            stretch_target_ratio=0.85,
        )

        if not paths_es:
            print("❌ No se generaron nuevos segmentos de audio.")
            result_queue.put((str(path_obj),))
            return

        # Actualizar mix local 
        print("\n🎵 Combinando audios...")
        seqs_es_dir = path_obj.parent / 'Seqs_trg'
        all_paths_es = sorted(seqs_es_dir.glob("*.wav"))
        
        # Calcular nuevos tiempos de inicio
        all_times = [int(text_dict['start'] * freq) for text_dict in edited_texts]

        arr, org_sr = torchaudio.load(str(path_obj.with_name('vocals.wav')))
        fix_es = torchaudio.functional.resample(arr, orig_freq=org_sr, new_freq=freq)
        fix_es[:, :] = 0

        for start_samples, audio_es_path in zip(all_times, all_paths_es):
            arr_es, _ = torchaudio.load(str(audio_es_path))
            end_samples = start_samples + arr_es.shape[1]
            if end_samples <= fix_es.shape[1]:
                fix_es[:, start_samples:end_samples] = arr_es

        vocals_es_path = path_obj.with_name('vocals_es.wav')
        torchaudio.save(str(vocals_es_path), fix_es, freq)

        no_vocals_path = path_obj.with_name('no_vocals.wav')
        print("🎬 Renderizando video final...")
        output_video = render_video(path_obj, f"{output_name}_edited", vocals_es_path, no_vocals_path)

        # Actualizar result.pkl con los nuevos textos
        with open(path_obj.with_name('result.pkl'), "wb") as f: 
            pickle.dump((edited_texts, f"{output_name}_edited", url, result, transcription, diarization), f)

        print(f"✅ Renderización completa: {output_video.name}")
        result_queue.put((str(output_video),))

    except Exception as e:
        import traceback
        sys.stdout.write(traceback.format_exc() + f"\n❌ Error: {e}\n")
        result_queue.put((path,))
    finally:
        sys.stdout = old_stdout
        log_queue.put(None)


def regenerate_and_render(
    path: str | None,
    edited_data: list[list],
    speaker_name: str,
    translate_lang: str,
):
    if not path or not Path(path).exists() or not edited_data:
        yield "❌ Selecciona un video y asegúrate de cargar los textos.", gr.update()
        return

    log_queue: queue.Queue = queue.Queue()
    result_queue: queue.Queue = queue.Queue()

    thread = threading.Thread(
        target=_regenerate_worker,
        args=(path, edited_data, speaker_name, translate_lang, log_queue, result_queue),
    )
    thread.start()

    log_parts: list[str] = []
    while True:
        try:
            item = log_queue.get(timeout=0.05)
        except queue.Empty:
            if not thread.is_alive():
                break
            continue
        if item is None:
            break
        log_parts.append(item)
        yield "".join(log_parts), gr.update()

    try:
        updated_path, = result_queue.get(timeout=1.0)
    except queue.Empty:
        updated_path = path

    thread.join()
    yield "".join(log_parts), updated_path


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
                
                with gr.Accordion("✏️ Editar Textos y Regenerar", open=False):
                    texts_editor = gr.Dataframe(
                        headers=["start", "end", "text", "speaker"],
                        datatype=["number", "number", "str", "str"],
                        interactive=True,
                        label="Textos (modifica solo la columna 'text')",
                        wrap=True
                    )
                    with gr.Row():
                        regen_btn = gr.Button("🔄 Regenerar y Renderizar", variant="secondary")
                    regen_log = gr.Textbox(label="Log Regeneración", lines=6, interactive=False)

            with gr.Column(scale=1):
                video_selector = gr.Dropdown(
                    label="Elegir video",
                    choices=[],
                    value=None,
                    interactive=True,
                )
                download_all_btn = gr.DownloadButton("Descargar todos (.zip)", interactive=False, variant="secondary")
        videos_state = gr.State([])

        def on_select_video(path):
            if path and Path(path).exists():
                pkl_path = Path(path).with_name('result.pkl')
                try:
                    with open(pkl_path, 'rb') as f:
                        texts, *_ = pickle.load(f)
                    
                    # Convertir textos a formato de lista de listas para Dataframe
                    df_data = [[t['start'], t['end'], t['text'], t['speaker']] for t in texts]
                    return path, df_data
                except Exception as e:
                    print(f"Error cargando pkl: {e}")
                    return path, []
            return None, []

        video_selector.change(
            fn=on_select_video,
            inputs=[video_selector],
            outputs=[video_out, texts_editor],
        )

        regen_btn.click(
            fn=regenerate_and_render,
            inputs=[video_selector, texts_editor, speaker_in, translate_in],
            outputs=[regen_log, video_out],
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
    demo.launch(share=False)
