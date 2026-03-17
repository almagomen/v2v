# Video2Video + OpenReel en Google Colab

Este documento describe cómo ejecutar v2v con el editor OpenReel en Google Colab.

## Requisitos previos

- Cuenta de Google Colab
- GPU habilitada (recomendado para Whisper, Pyannote, BS-RoFormer)
- API keys en Colab Secrets: `LMNT_API_KEY`, `GOOGLE_API_KEY` (para traducción), `AUTH0_COOKIE`, `MIXPANEL_COOKIE` (opcional, para LMNT)

## Pasos

### 1. Subir el proyecto a Colab

Sube la carpeta del proyecto v2v a Colab (o clona desde Git). Asegúrate de incluir:
- `api/` (backend FastAPI)
- `src/` (pipeline v2v)
- `openreel/` (editor, ya clonado)
- `requirements.txt`

### 2. Instalar dependencias

```python
!pip install -r requirements.txt
```

### 3. (Opcional) Montar Google Drive

Para modelos persistentes (BS-RoFormer, Whisper, etc.):

```python
from google.colab import drive
drive.mount('/content/drive')
```

### 4. Construir OpenReel (una vez)

OpenReel requiere Node.js 18+, pnpm y AssemblyScript. En Colab:

```python
!curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
!apt-get install -y nodejs
!npm install -g pnpm

%cd openreel
!pnpm install
# Build WASM (requiere assemblyscript) y luego el frontend
!pnpm build
%cd ..
```

Esto genera `openreel/apps/web/dist/`. El backend servirá estos archivos estáticos.

**Nota:** Si el build falla por falta de `asc` (AssemblyScript), instala: `!cd openreel/packages/core && npm install` y vuelve a intentar. En algunos entornos puede ser necesario usar un build pre-compilado.

### 5. Exponer el servidor con ngrok

Para acceder desde fuera de Colab:

```python
!pip install pyngrok -q

from pyngrok import ngrok
import threading
import uvicorn

def run_server():
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000)

thread = threading.Thread(target=run_server)
thread.daemon = True
thread.start()

# Esperar a que el servidor arranque
import time
time.sleep(5)

url = ngrok.connect(8000)
print(f"\n✅ Abre OpenReel en: {url.public_url}\n")
```

### 6. Alternativa: sin ngrok (solo local)

Si prefieres usar la URL de Colab directamente (menos estable):

```python
# En una celda
!python colab_launch.py
```

Luego usa "Conectar" > "Conectar a un host local" en Colab para exponer el puerto 8000.

## Uso

1. Abre la URL de ngrok en tu navegador.
2. Crea un nuevo proyecto o abre uno existente.
3. En el panel izquierdo, selecciona la pestaña **Video2Video**.
4. Pega una o más URLs de YouTube (una por línea).
5. Selecciona idioma de traducción y voz.
6. Pulsa **Procesar**.
7. Cuando termine, elige el video, edita segmentos si quieres, y pulsa **Cargar en editor** para editarlo en OpenReel.

## Notas

- La primera ejecución puede tardar varios minutos (descarga de modelos).
- Los videos se guardan en `/content/Queue/`.
- El backend expone la API en `/api/` y la documentación en `/docs`.
