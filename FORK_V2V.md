# Fork V2V sobre OpenReel — Guía Maestra de Integración y Mantenimiento

Este documento detalla exhaustivamente la arquitectura de integración de **Video2Video** (backend FastAPI en el repo padre) sobre el frontend de **OpenReel**, así como las optimizaciones para entornos de GPU en la nube (Google Colab y Kaggle Dual-T4).

Está diseñado para que desarrolladores y asistentes de IA (LLMs) comprendan la arquitectura técnica, **por qué está estructurada de esta manera, cómo funciona la sincronización en tiempo real y cómo mantener o actualizar OpenReel desde el upstream oficial sin romper código ni introducir conflictos de Git**.

---

## 1. Filosofía de la Integración: Módulo Aislado y Mínima Huella (Near-Zero Core Touch)

Toda la funcionalidad de Video2Video vive estrictamente encapsulada en un único directorio modular:
👉 **`apps/web/src/v2v/`**

### Principios de Diseño
1. **Cero colisiones con Upstream**: Al no dispersar archivos en `components/`, `stores/`, `lib/` ni `utils/`, cualquier actualización o rebase desde el repositorio oficial de OpenReel (`Augani/openreel-video`) se realiza sin conflictos con los archivos propios de V2V.
2. **Cero cambios de configuración de compilación**: No se altera `vite.config.ts`, `tsconfig.json` ni los paths del bundler. Gracias a que OpenReel ya tiene configurado el alias `@/*` apuntando a `./src/*`, cualquier módulo dentro de `src/v2v/` se importa de manera limpia vía `@/v2v` o imports relativos internos (`../stores/`, `../api/`, etc.).
3. **Puntos de contacto mínimos en UI (Web & Desktop)**: En toda la base de código de OpenReel, solo existen **2 puntos de montaje de 1 línea** para habilitar Video2Video tanto en la versión Web como en la app Desktop nativa:
   - **Web**: `apps/web/src/components/editor/Toolbar.tsx`:
     ```tsx
     import { V2VToolbarEntry } from "@/v2v";
     // ...
     <V2VToolbarEntry />
     ```
   - **Desktop**: `apps/web/src/desktop/DesktopApp.tsx` (en `DesktopTitleBar`):
     ```tsx
     import { V2VToolbarEntry } from "@/v2v";
     // ...
     {hasProject && isVideoEditing ? <V2VToolbarEntry /> : null}
     ```
   - **Atajo global**: `Alt+V` registrado en el listener para alternar el panel en cualquier plataforma.
4. **Directorios estándar 100% limpios**: Las carpetas nativas de OpenReel (`src/components/`, `src/stores/`, `src/lib/`, `src/utils/`) se mantienen puras, preservando la arquitectura original del proyecto.

> [!IMPORTANT]
> **REGLA MANDATORIA PARA LLMs Y DESARROLLADORES**:
> Cualquier nueva funcionalidad, componente, store, utilidad o cliente API relacionado con Video2Video **DEBE ubicarse dentro de `apps/web/src/v2v/`**. No colocar archivos de V2V en los directorios nativos de OpenReel.

---

## 2. Inventario Total de Archivos de la Integración

### A. Estructura del Módulo Autónomo `apps/web/src/v2v/`

```
apps/web/src/v2v/
├── index.ts                           # Barrel export público (exporta V2VToolbarEntry)
├── api/
│   └── v2v-api.ts                     # Cliente HTTP/WebSocket Typed con FastAPI, AbortController y endpoints
├── components/
│   ├── V2VToolbarEntry.tsx            # Punto de montaje UI: botón en Toolbar, drawer lateral y modal flotante z-[200]
│   ├── V2VPanel.tsx                   # Panel principal: inferencia, modelos, tokens (FISH/GOOGLE), export a Colab
│   ├── V2VSegmentBulkEditor.tsx       # Editor masivo flotante de segmentos (STT vs TTS, retraducción, emociones, sliders)
│   ├── V2VGenerateTTSSection.tsx      # Generador y sintetizador TTS por segmentos
│   ├── CloneVoiceSegmentSection.tsx   # Clonación y síntesis de voz de clip seleccionado
│   ├── ColabExportTab.tsx             # Pestaña de exportación y render final acelerado por GPU en Colab
│   ├── TokensConfigSection.tsx        # Componente atómico: configuración de claves de API y modelos Gemini
│   ├── SpeakerSelector.tsx            # Componente atómico: selector de voz y emoción inicial
│   ├── JobProgressIndicator.tsx       # Componente atómico: barra de progreso de etapa, logs por URL y cancelaciones
│   ├── RenderProgressBar.tsx          # Componente atómico: progreso de renderizado FFmpeg en backend
│   ├── CatboxUploadStatus.tsx         # Componente atómico: estado de subida y enlace de descarga de Catbox
│   ├── BatchRenderQueue.tsx           # Componente atómico: visualización de la cola de videos a renderizar
│   ├── EmotionSelector.tsx            # Componente atómico: selector con categorías de emociones Fish Audio (S2.1)
│   ├── SegmentAudioSliders.tsx        # Componente atómico: sliders de temperatura, top_p, penalty y volumen
│   ├── SegmentRow.tsx                 # Componente atómico: fila individual de edición de segmento en el Bulk Editor
│   ├── TTSBatchControls.tsx           # Componente atómico: cabecera y accesos rápidos de generación TTS
│   └── TTSSegmentCard.tsx             # Componente atómico: tarjeta de edición de segmento con controles de velocidad
├── stores/
│   ├── v2v-types.ts                   # Definición centralizada de tipos TypeScript para todos los slices
│   ├── v2v-storage.ts                 # Persistencia en localStorage desacoplada con helpers type-safe
│   ├── v2v-folders-slice.ts           # Slice de Zustand: gestión de carpetas, nativeFiles y folderRefs
│   ├── v2v-segments-slice.ts          # Slice de Zustand: segmentos, speakers, multi-speaker mapping
│   ├── v2v-job-slice.ts               # Slice de Zustand: WebSocket real-time, HTTP polling adaptativo y auto-import
│   ├── v2v-store.ts                   # Barrel store unificado que combina todos los slices
│   └── colab-export-store.ts          # Slice de Zustand: cola de renderizado en lote hacia Colab / Catbox
└── utils/
    ├── v2v-segment-regen.ts           # Motor de regeneración de audio sin tocar el caché inmutable de OpenReel
    ├── v2v-segment-ids.ts             # Generador y parser de IDs deterministas de segmentos (jobId + videoIdx + segIdx)
    ├── v2v-utils.ts                   # Normalización de tokens, nombres lógicos y emparejamiento en librería
    ├── v2v-detached-actions.ts        # Acciones sobre proyectos desacoplados (inmutables) e inserción en lote
    ├── v2v-emotions.ts                # Catálogo unificado de emociones Fish Audio (s2.1) y manipulación de tags
    └── v2v-folder-utils.ts            # Helpers de carpetas y assets de jobs V2V en la librería de medios
```

---

## 3. Arquitectura del Backend y Formato de Persistencia (100% JSON)

El proyecto V2V opera bajo el principio de **cero dependencias binarias propietarias en almacenamiento**:

1. **Eliminación Total de Pickle (`result.pkl`)**:
   - Toda la información de inferencia se persiste en `result.json` en la carpeta del video correspondiente (`drive_dir / out_dir / result.json`).
   - El archivo incluye `version: 2`, `source_lang`, `target_lang`, `segments` (con texto traducido, tiempos, voz asignada y `original_speaker`), y `original_segments` (transcripción STT nativa).
   - Acceso centralizado a través de `src/result_store.py` (`load_result`, `save_result`, `update_result_segments`).
2. **Indexación O(1) de URLs en Cola**:
   - En lugar de escanear directorios en disco cada vez que se consulta el estado de la cola, el backend mantiene `Queue/url_index.json` sincronizado para búsqueda instantánea.
3. **Escritura por Lotes de Logs (`_LogBuffer`)**:
   - `api/job_store.py` implementa `_LogBuffer`, acumulando líneas de `stdout`/`stderr` en memoria y ejecutando un flush a disco cada 2 segundos o 4KB, reduciendo drásticamente la contención de I/O en Kaggle/Colab.
4. **Dual-GPU Pipeline y Hardening de Notebook**:
   - Detección precisa de entorno Colab/Kaggle en `kaggle_launch.ipynb`.
   - Carga de modelos Whisper Turbo en GPU 0 y Pyannote Diarization en GPU 1 en paralelo con `ThreadPoolExecutor`.
   - `.env` guardado exclusivamente en `openreel/apps/web/.env` sin exponer credenciales en el root de Git.
   - Verificación de salud activa `GET /health` antes de inicializar Vite.

---

## 4. Soporte Multi-Speaker Real y Diarización

El pipeline de diarización detecta automáticamente hablantes independientes (`SPEAKER_00`, `SPEAKER_01`, etc.):

1. **Preservación de `original_speaker`**:
   - Pyannote clasifica por palabra (`assign_speakers_by_word`) y asigna el hablante detectado.
   - El campo `original_speaker` se preserva inmutable en `result.json`, en los jobs en memoria y en las respuestas de la API.
2. **Mapeo Flexible de Voces (`speaker_map`)**:
   - La API (`/api/process-urls`) y los endpoints dedicados (`GET/POST /api/job/{job_id}/speakers/{video_index}`) permiten enviar un diccionario de mapeo:
     ```json
     {
       "SPEAKER_00": "mrbeast",
       "SPEAKER_01": "default_fish"
     }
     ```
   - `clone_voice_segments()` en `src/audio_utils.py` sintetiza cada segmento utilizando la voz asignada a ese hablante específico.
3. **Visualización y Control en Frontend**:
   - Cada segmento en `SegmentRow` muestra un badge distintivo del hablante detectado.
   - En `V2VSegmentBulkEditor`, cuando se detecta más de un hablante, se activa una barra de mapeo multi-hablante que permite cambiar la voz de todos los segmentos de un personaje en un solo clic y sincronizarlo con el servidor.

---

## 5. Streaming en Tiempo Real vía WebSocket con Fallback a HTTP Polling

1. **Servidor WebSocket (`/ws/job/{job_id}`)**:
   - Implementado en `api/main.py` mediante `ConnectionManager` (`api/websocket_manager.py`).
   - Thread-safe: el pipeline en segundo plano despacha eventos mediante `loop.call_soon_threadsafe`.
   - Eventos emitidos:
     - `job_snapshot`: Estado completo del job al conectarse.
     - `log_chunk`: Streaming continuo de salida de terminal (sin esperar flush a disco).
     - `job_update`: Notificaciones inmediatas de cambios de etapa, progreso o URLs completadas.
2. **Cliente Frontend Resiliente**:
   - `v2v-job-slice.ts` abre el canal WebSocket al iniciar `startPolling(jobId)`.
   - Si el WebSocket está activo, los logs y progresos se renderizan en tiempo real.
   - **Garantía de Fallback**: Si el entorno de red (proxies de ngrok/localtunnel) bloquea WebSockets, el HTTP polling adaptativo existente continúa funcionando automáticamente cada 2 segundos sin interrupción.

---

## 6. Estrategia de Audio y Caché del Timeline (Desacoplamiento Total)

### El Problema de OpenReel con la Caché de Audio
OpenReel maneja la reproducción de audio en `Preview.tsx` y `PlaybackController` indexando los `AudioBuffer` decodificados en memoria usando el `mediaId` (`${mediaId}:0`). 
Si se regenera un segmento y se sobreescribe el blob manteniendo el mismo `mediaId`, **OpenReel nunca vuelve a decodificar el archivo** porque la clave ya existe en su caché inmutable en RAM.

### La Solución Desacoplada (`src/v2v/utils/v2v-segment-regen.ts`)
1. Llama a la API pública nativa de OpenReel: `await importMedia(file)`.
2. `importMedia` genera un **nuevo `mediaId` único**, calcula la forma de onda (*waveform*), extrae la duración real y persiste el nuevo blob en IndexedDB de forma 100% estándar.
3. Actualiza el clip en el timeline reemplazando `clip.mediaId = newMediaId` y ajustando la duración:
   ```typescript
   currentProject = {
     ...currentProject,
     timeline: {
       ...currentProject.timeline,
       tracks: currentProject.timeline.tracks.map((track) => ({
         ...track,
         clips: track.clips.map((clip) =>
           clip.id === clipId
             ? { ...clip, mediaId: newMediaId, inPoint: clip.inPoint ?? 0, outPoint: (clip.inPoint ?? 0) + newDuration, duration: newDuration }
             : clip,
         ),
       })),
     },
     modifiedAt: Date.now(),
   };
   ```
4. Elimina el `oldMediaId` de `project.mediaLibrary.items` y borra el blob viejo con `deleteMediaBlob(oldMediaId)`.
5. Ejecuta `loadProject(currentProject)` y `forceSave()`.

**Resultado**: OpenReel detecta un `mediaId` nuevo, lo decodifica de inmediato y el Timeline se actualiza al instante con cero parches sobre el core.

---

## 7. Protocolo de Actualización desde Upstream (`Augani/openreel-video`)

Cuando se desee incorporar los últimos cambios del repositorio oficial de OpenReel:

```bash
# 1. Asegurar remote upstream
git remote add openreel-upstream https://github.com/Augani/openreel-video.git 2>/dev/null || true
git fetch openreel-upstream main

# 2. Hacer merge de upstream en la rama monorepo-subtree
git merge openreel-upstream/main --allow-unrelated-histories -m "chore(openreel): merge upstream updates" -X subtree=openreel
```

### Reglas de Resolución de Conflictos:
1. **Módulo propio de V2V (`openreel/apps/web/src/v2v/*`)**: Tomar nuestra versión (`--ours`). Upstream no tiene este directorio.
2. **Archivos limpios del core (`Timeline.tsx`, `project-store.ts`, `Preview.tsx`, `audio-engine.ts`, `media-slice.ts`, `EditorInterface.tsx`)**: Tomar la versión de upstream (`--theirs`).
3. **`Toolbar.tsx`**: Aceptar los cambios de upstream y simplemente verificar que `<V2VToolbarEntry />` esté montado en la barra superior:
   ```tsx
   import { V2VToolbarEntry } from "@/v2v";
   // ...
   <V2VToolbarEntry />
   ```
