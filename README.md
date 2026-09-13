# Video2Video + OpenCut

Pipeline de **traducción y doblaje con IA** integrado con el editor open-source **OpenCut**: descarga → transcripción (Whisper) → diarización (Pyannote) → traducción (Gemini) → TTS (Fish Audio) → edición interactiva en el timeline de OpenCut.

## Características

- **Pipeline de IA**: Whisper (STT) + Pyannote (Diarización) + Fish Audio TTS s2.1-pro (Clonado de voz).
- **Editor OpenCut Integrado**: Timeline multitrack interactivo (Video, Audio Doblado en Español, Instrumental aislado por RoFormer y Subtítulos editables).
- **Arquitectura Desacoplada**: Backend FastAPI en Python (GPU) y Frontend OpenCut (Vite + React) conectados vía API REST y WebSockets para streaming de logs.
- **Git Subtree**: Facilita actualizar OpenCut con `git subtree pull` sin romper el código de IA.

---

## Requisitos

- Python 3.10+
- Node.js / Bun (para el frontend OpenCut)
- GPU recomendada (Whisper, Pyannote, RoFormer)
- **ffmpeg** en el PATH

## Variables de entorno / Secrets

| Variable         | Uso                          |
|------------------|------------------------------|
| `GOOGLE_API_KEY` | Gemini (traducción, títulos)  |
| `FISH_API_KEY`   | Fish Audio TTS (clonado de voz) |
| `DRIVE_MOUNT`    | Opcional: `true` para montar Drive en Colab |

En Colab: panel izquierdo → **Secrets** y añade `GOOGLE_API_KEY` y `FISH_API_KEY`.

---

## Uso en Google Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/almagomen/v2v/blob/opencut_launch/colab_launch.ipynb)

1. Abre [colab_launch.ipynb](colab_launch.ipynb).
2. **Runtime → Change runtime type → T4 GPU**.
3. Añade en **Secrets**: `GOOGLE_API_KEY`, `FISH_API_KEY`.
4. Ejecuta la celda del notebook. Levantará automáticamente FastAPI, el editor OpenCut y creará el enlace nativo de Google Colab (`output.serve_kernel_port_as_window`).
5. Haz clic en el enlace **🚀 Abrir Editor OpenCut + V2V** en la celda para abrir el editor con doblaje V2V en tiempo real.

---

## Ejecución Local

```bash
git clone https://github.com/almagomen/v2v.git -b opencut_launch
cd v2v
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

Inicia los servicios con el lanzador unificado:

```bash
python launch_opencut.py
```

Abre en tu navegador:
- **Editor OpenCut + V2V**: `http://localhost:5173`
- **FastAPI Docs**: `http://localhost:8000/docs`

---

## Documentación de la Integración

Para conocer todos los detalles de arquitectura, esquemas de datos y cómo replicar la integración paso a paso, consulta:
👉 [INTEGRATION.md](INTEGRATION.md)
