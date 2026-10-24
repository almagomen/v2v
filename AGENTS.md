# Reglas del Workspace y Guía Maestra: Fork V2V sobre OpenReel

Este documento es la **fuente de verdad única** de arquitectura, reglas de aislamiento y mantenimiento para desarrolladores y asistentes de IA (LLMs) que trabajen en este repositorio.

---

## 🚨 REGLAS MANDATORIAS PARA AGENTES E IA

1. **Aislamiento Total (Near-Zero Core Touch)**:
   - Todo código, componente, slice de Zustand, cliente API, utilidad o tipo de Video2Video debe residir **exclusivamente dentro de**:
     👉 `openreel/apps/web/src/v2v/`
   - **NUNCA modificar archivos de configuración o scripts de OpenReel**:
     - NO tocar `openreel/apps/desktop/package.json` ni añadir scripts en `openreel/apps/desktop/scripts/`.
     - NO modificar `package.json`, `pnpm-lock.yaml`, `vite.config.ts` ni `tsconfig.json` de OpenReel.
     - NO colocar código de V2V en los directorios nativos (`src/components/`, `src/stores/`, `src/lib/`, `src/utils/`).
   - **Puntos de montaje estrictamente limitados a 2 líneas en todo el proyecto**:
     1. `openreel/apps/web/src/components/editor/Toolbar.tsx`: `<V2VToolbarEntry />`
     2. `openreel/apps/web/src/desktop/DesktopApp.tsx`: `{hasProject && isVideoEditing ? <V2VToolbarEntry /> : null}`

2. **Compilación Oficial de Desktop (.exe en Windows)**:
   Ejecutar estrictamente el comando documentado:
   ```powershell
   cd .\openreel\
   $env:OPENREEL_DESKTOP="1"; pnpm --filter @openreel/web build; pnpm --filter @openreel/desktop run build:main; pnpm --filter @openreel/desktop exec electron-builder --dir
   ```

3. **Estado de V2V asociado al Proyecto Activo (Project Isolation)**:
   - La cola, URLs, videos procesados y logs del panel V2V están vinculados al `project.id` del proyecto actualmente abierto en OpenReel (`openreel.v2v.projectJob.<projectId>`).
   - Si se crea un **proyecto nuevo** o se abre un proyecto en blanco, el panel V2V arranca **completamente limpio**.
   - Si se abre un **proyecto existente** que ya tenía un trabajo V2V, restaura automáticamente sus URLs, videos y logs.
   - Las claves de API (Fish Audio, Google Gemini) y la URL del backend son globales y se conservan entre proyectos.

4. **Estrategia Anti-Límites de Cloudflare Tunnel y Optimización de Rendimiento (Regla Mandatoria)**:
   - Cloudflare Tunnel impone un límite estricto de **100 segundos** para el *primer byte* (Time To First Byte - TTFB) arrojando error `HTTP 524`.
   - **Prohibido empaquetar o comprimir en memoria (`io.BytesIO`)** durante peticiones HTTP.
   - **Pre-caching en Background**: El paquete `audio_segments.tar.gz` se genera automáticamente al terminar la síntesis TTS en el backend con compresión gzip ligera (`compresslevel=1`, >150MB/s) reduciendo el ancho de banda un 70% sin demoras en la petición del cliente.
   - Todo endpoint de transferencia masiva (TAR de segmentos, videos largos, películas) debe **servirse directamente desde disco con `FileResponse`** (`sendfile()`) para emitir el primer byte en <10ms.
   - En el cliente (`v2v-api.ts`), transferencias masivas usan `timeoutMs = 0` (sin límite arbitrario) y descompresión nativa `DecompressionStream("gzip")`.
   - **TTS Concurrente**: La síntesis con Fish Audio se paraleliza con `ThreadPoolExecutor(max_workers=5)` con reintento exponencial ante HTTP 429 para acelerar 4x la generación.
   - En fallbacks individuales de red, **prohibido `Promise.all` masivo** sin control de concurrencia; usar lotes concurrentes (máximo 5) con reintentos para evitar que Cloudflare o Chromium cierren sockets (error 429/502).

---

## 1. Filosofía de la Integración

Toda la funcionalidad de Video2Video vive encapsulada en `apps/web/src/v2v/`:
- **Cero colisiones con Upstream**: Actualizaciones y rebases desde el repo oficial (`Augani/openreel-video`) ocurren sin tocar el módulo V2V.
- **Cero cambios de configuración de compilación**: El alias nativo `@/*` resuelve `@/v2v` sin alterar bundlers.
- **Atajo global**: `Alt+V` para alternar el panel en cualquier plataforma.

---

## 2. Inventario del Módulo `apps/web/src/v2v/`

```
apps/web/src/v2v/
├── index.ts                           # Barrel export público (V2VToolbarEntry)
├── api/
│   └── v2v-api.ts                     # Cliente HTTP/WebSocket Typed con FastAPI, AbortController y endpoints
├── components/
│   ├── V2VToolbarEntry.tsx            # Punto de montaje UI: botón en Toolbar, drawer lateral y modal z-[200]
│   ├── V2VPanel.tsx                   # Panel principal: inferencia, modelos, tokens, limpieza por proyecto
│   ├── V2VSegmentBulkEditor.tsx       # Editor masivo flotante de segmentos (STT vs TTS, retraducción, sliders)
│   ├── V2VGenerateTTSSection.tsx      # Generador y sintetizador TTS por segmentos
│   ├── CloneVoiceSegmentSection.tsx   # Clonación y síntesis de voz de clip seleccionado
│   ├── ColabExportTab.tsx             # Pestaña de exportación y render final acelerado por GPU en Colab
│   ├── TokensConfigSection.tsx        # Configuración de claves de API y modelos Gemini
│   ├── SpeakerSelector.tsx            # Selector de voz y emoción inicial
│   ├── JobProgressIndicator.tsx       # Barra de progreso de etapa, logs por URL y cancelaciones
│   ├── RenderProgressBar.tsx          # Progreso de renderizado FFmpeg en backend
│   ├── CatboxUploadStatus.tsx         # Estado de subida y enlace de descarga de Catbox
│   ├── BatchRenderQueue.tsx           # Visualización de la cola de videos a renderizar
│   ├── EmotionSelector.tsx            # Selector de emociones Fish Audio (S2.1)
│   ├── SegmentAudioSliders.tsx        # Sliders de temperatura, top_p, penalty y volumen
│   ├── SegmentRow.tsx                 # Fila individual de edición de segmento en el Bulk Editor
│   ├── TTSBatchControls.tsx           # Cabecera y accesos rápidos de generación TTS
│   └── TTSSegmentCard.tsx             # Tarjeta de edición de segmento con controles de velocidad
├── stores/
│   ├── v2v-types.ts                   # Tipos TypeScript centralizados para todos los slices
│   ├── v2v-storage.ts                 # Persistencia indexada por project.id (openreel.v2v.projectJob.<id>)
│   ├── v2v-folders-slice.ts           # Slice: gestión de carpetas, nativeFiles y folderRefs
│   ├── v2v-segments-slice.ts          # Slice: segmentos, speakers, multi-speaker mapping
│   ├── v2v-job-slice.ts               # Slice: WebSocket real-time, HTTP polling adaptativo y syncWithProject
│   ├── v2v-store.ts                   # Store unificado que combina todos los slices
│   └── colab-export-store.ts          # Slice: cola de renderizado en lote hacia Colab / Catbox
└── utils/
    ├── v2v-segment-regen.ts           # Regeneración de audio sin tocar el caché inmutable de OpenReel
    ├── v2v-segment-ids.ts             # Generador y parser de IDs deterministas de segmentos
    ├── v2v-utils.ts                   # Normalización de tokens, nombres lógicos y emparejamiento
    ├── v2v-detached-actions.ts        # Acciones sobre proyectos desacoplados e inserción en lote
    ├── v2v-emotions.ts                # Catálogo unificado de emociones Fish Audio (s2.1)
    └── v2v-folder-utils.ts            # Helpers de carpetas y assets de jobs V2V en la librería
```

---

## 3. Arquitectura del Backend y Formato de Persistencia (100% JSON)

1. **Cero Dependencias Binarias Propietarias (Sin Pickle)**: Toda inferencia se guarda en `result.json` en la carpeta del video (`drive_dir / out_dir / result.json`). Centralizado en `src/result_store.py`.
2. **Indexación O(1) de URLs en Cola**: Mantenido en `Queue/url_index.json`.
3. **Escritura por Lotes de Logs (`_LogBuffer`)**: `api/job_store.py` ejecuta flush cada 2s o 4KB, reduciendo la contención de disco.
4. **Dual-GPU Pipeline**: Whisper Turbo en GPU 0 y Pyannote Diarization en GPU 1 en paralelo con `ThreadPoolExecutor` en `kaggle_launch.ipynb`.
5. **Transferencia Optimizada**: Instrumental y segmentos de voz original (`Seqs_src`) servidos en AAC/M4A 192k (ahorro del 92-94% de peso, reduciendo paquetes de 45MB a ~3.5MB con fidelidad acústica de estudio) y TAR de segmentos cacheados en disco servidos vía `FileResponse` (primer byte <10ms) para transferencias instantáneas e ilimitadas a través de Cloudflare Tunnel.

---

## 4. Soporte Multi-Speaker Real y Diarización

1. **Preservación de `original_speaker`**: Pyannote clasifica por palabra (`assign_speakers_by_word`). El tag se conserva inmutable en `result.json`.
2. **Mapeo Flexible de Voces (`speaker_map`)**: Envía mapeos `{ "SPEAKER_00": "mrbeast", "SPEAKER_01": "default_fish" }` para clonación diferenciada por personaje.
3. **Control Visual**: En `V2VSegmentBulkEditor`, barra de reasignación masiva por speaker.

---

## 5. Streaming Real-Time WebSocket y HTTP Polling

- Endpoint `/ws/job/{job_id}` despacha `job_snapshot`, `log_chunk` y `job_update`.
- Fallback automático e ininterrumpido a HTTP polling cada 2s si la red o proxy bloquea WebSockets.

---

## 6. Estrategia de Audio y Caché del Timeline

OpenReel indexa `AudioBuffer` en memoria usando `${mediaId}:0`. Para evitar que el reproductor ignore audios regenerados:
1. `v2v-segment-regen.ts` llama a `importMedia(file)` para generar un **nuevo `mediaId`**.
2. Reemplaza `clip.mediaId = newMediaId` y actualiza duración en el timeline.
3. Borra el blob viejo con `deleteMediaBlob(oldMediaId)` y ejecuta `loadProject()`.
4. OpenReel decodifica el nuevo ID al instante sin parches sobre el core.

---

## 7. Estrategia de Red y Mitigación de Límites de Cloudflare Tunnel

Al comunicar el cliente OpenReel con el backend a través de Cloudflare Tunnel (Kaggle/Colab), aplican restricciones estrictas que todo agente e IA debe respetar:

1. **Evasión del Timeout de 100s de Cloudflare (Error 524) y Pre-caching en Background**:
   - Cloudflare Tunnel cancela cualquier petición si no recibe el primer byte (TTFB) en 100 segundos.
   - **Solución implementada**:
     - `ensure_audio_segments_tar`: Empaqueta anticipadamente a disco (`folder / "audio_segments.tar.gz"`) con compresión ultra-rápida (`compresslevel=1`, >150MB/s), ignorando archivos temporales `*_raw.wav` para reducir el tamaño al 70%.
     - Se ejecuta automáticamente en background al finalizar la etapa de TTS (o en caché hit), de modo que cuando el cliente solicita el paquete, ya está 100% generado en disco.
     - Se sirve mediante `FileResponse` utilizando `sendfile()` del kernel: el primer byte se transmite en <10ms hacia Cloudflare, lo cual **desactiva el timeout de 100s** y permite transferir películas de 2 horas sin interrupciones.
     - Caché en disco con validación por `mtime` de los segmentos para entrega instantánea en reimportaciones.

2. **Cero Límites Artificiales y Descompresión Nativa en el Cliente (`timeoutMs = 0`)**:
   - `fetchAudioSegmentsTar` usa `timeoutMs = 0` por defecto. El cliente nunca aborta prematuramente descargas de videos largos; el control de cancelación queda reservado al `AbortSignal` manual del usuario.
   - Detección automática de magic bytes gzip (`0x1f, 0x8b`) y descompresión en memoria mediante la API nativa de Chromium `DecompressionStream("gzip")`.

3. **Control de Concurrencia en Fallback de Descargas (Anti-Saturación de Sockets)**:
   - Si el paquete TAR no está disponible y se recurre a descargar segmentos individualmente, las peticiones se procesan en lotes secuenciales de **5 peticiones simultáneas** con reintento automático (`CONCURRENCY_LIMIT = 5`).
   - Esto evita saturar los 6 sockets máximos de Chromium/Electron y previene bloqueos por rate limit (`429`) o `Connection Reset` (`502/524`) en Cloudflare.

4. **Síntesis TTS Concurrente (Fish Audio)**:
   - En `src/audio_utils.py`, `clone_voice_segments` ejecuta llamadas concurrentes con `ThreadPoolExecutor(max_workers=5)`, acelerando la generación de cientos de clips de minutos a segundos sin sobrepasar los límites de concurrencia de la API.
   - En `src/tts.py`, reintentos automáticos con backoff exponencial ante respuestas HTTP 429 (Rate Limit).

---

## 8. Protocolo de Actualización desde Upstream (`Augani/openreel-video`)

```bash
git remote add openreel-upstream https://github.com/Augani/openreel-video.git 2>/dev/null || true
git fetch openreel-upstream main
git merge openreel-upstream/main --allow-unrelated-histories -m "chore(openreel): merge upstream updates" -X subtree=openreel
```

### Reglas de Resolución de Conflictos:
1. `openreel/apps/web/src/v2v/*`: Tomar nuestra versión (`--ours`).
2. Archivos del core (`Timeline.tsx`, `project-store.ts`, etc.): Tomar versión de upstream (`--theirs`).
3. `Toolbar.tsx` y `DesktopApp.tsx`: Verificar que contengan los puntos de montaje de `<V2VToolbarEntry />`.
