# Video2Video

Pipeline de **traducción y doblaje** de videos de YouTube: descarga → transcripción (Whisper) → diarización (Pyannote) → traducción (Gemini) → TTS (LMNT) → render con ffmpeg.

## Requisitos

- Python 3.10+
- GPU recomendada (Whisper, Pyannote, Roformer)
- **ffmpeg** en el PATH

## Variables de entorno / Secrets

| Variable         | Uso                          |
|------------------|------------------------------|
| `GOOGLE_API_KEY` | Gemini (traducción, títulos)  |
| `LMNT_API_KEY`   | LMNT TTS (clonado de voz)     |
| `DRIVE_MOUNT`    | Opcional: `true` para montar Drive en Colab |

En Colab: panel izquierdo → **Secrets** y añade `GOOGLE_API_KEY` y `LMNT_API_KEY`.

## Uso en Google Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/TU_USUARIO/v2v/blob/main/colab_launch.ipynb)

1. Abre [colab_launch.ipynb](colab_launch.ipynb) (o el enlace de arriba tras sustituir `TU_USUARIO` por tu usuario de GitHub).
2. **Runtime → Change runtime type → T4 GPU**.
3. Añade en **Secrets**: `GOOGLE_API_KEY`, `LMNT_API_KEY`.
4. Ejecuta las celdas para instalar dependencias y lanzar el backend (`uvicorn`).
5. Abre la URL pública (ngrok/Colab proxy) del puerto 8000 y entra al editor OpenReel.

Si no usas GitHub, sube esta carpeta a Colab (o a Drive y monta Drive), entra en la carpeta y ejecuta:

```bash
pip install -r requirements.txt
```

Luego ejecuta el backend (por ejemplo con `colab_launch.py` o `uvicorn api.main:app`).

## Instalación local

```bash
git clone https://github.com/almagomen/v2v.git
cd v2v
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

Copia `.env.example` a `.env` y rellena `GOOGLE_API_KEY` y `LMNT_API_KEY`.

```bash
uvicorn api.main:app --reload --port 8000
```

## Editor OpenReel

v2v incluye integración con [OpenReel](https://github.com/Augani/openreel-video), un editor de video profesional en el navegador. El flujo v2v (URLs → transcripción → TTS → render) está disponible como panel en OpenReel.

### Arquitectura

- **Backend API** (FastAPI): expone la pipeline v2v vía REST.
- **Frontend** (OpenReel modificado): panel "Video2Video" en la pestaña del panel de assets.

### Uso con OpenReel en Colab

Consulta [COLAB_V2V_OPENREEL.md](COLAB_V2V_OPENREEL.md) para instrucciones detalladas.

Resumen:
1. Instala dependencias y construye OpenReel (`cd openreel && pnpm install && pnpm build`).
2. Lanza el backend: `uvicorn api.main:app --host 0.0.0.0 --port 8000`.
3. Usa ngrok para exponer el puerto y abre la URL en el navegador.
4. En OpenReel, pestaña **Video2Video**: pega URLs, procesa y carga en el editor.

### Desarrollo local

```bash
# Terminal 1: Backend
pip install fastapi uvicorn python-multipart
uvicorn api.main:app --reload --port 8000

# Terminal 2: OpenReel (opcional, para dev del frontend)
cd openreel && pnpm dev
# Configura VITE_V2V_API_URL=http://localhost:8000 en openreel/apps/web/.env
# En el mismo host que Vite, las rutas /api/* se proxifican a uvicorn (8000); ver V2V_API_PROXY_TARGET en openreel/FORK_V2V.md
```

Si OpenReel está construido, el backend sirve el frontend en la raíz (`/`).

## Fork OpenReel (V2V)

Los ajustes propios del fork (Vite en Colab, proxy `/api`, clone voice, export, lista de archivos sensibles al merge con upstream) están descritos en **[`openreel/FORK_V2V.md`](openreel/FORK_V2V.md)**.

## Estructura del repo

```
v2v/
├── README.md
├── requirements.txt
├── .env.example
├── colab_launch.py     # Lanzar backend para Colab
├── api/                # Backend FastAPI (OpenReel)
│   ├── main.py
│   ├── routes/
│   ├── schemas.py
│   ├── service.py
│   └── job_store.py
├── openreel/           # Editor OpenReel (fork con panel v2v)
└── src/
    ├── config.py       # Rutas, device, API keys
    ├── models.py       # Caché de modelos
    ├── audio_utils.py  # Ajuste duración, clone_voice_segments, merge
    ├── translation.py  # Gemini: traducir, título TikTok
    ├── download.py     # yt-dlp, Roformer
    ├── stt.py          # Whisper, run_main
    ├── diarization.py  # Pyannote
    ├── tts.py          # LMNT
    ├── pipeline.py     # process_video_queue, split_audio_sequences
    ├── render.py       # ffmpeg, preview
    └── edit_utils.py   # Edición de textos, regenerate_segments
```

## Licencia

Uso bajo tu propia responsabilidad. No incluyas claves API en el código ni en el repo.
