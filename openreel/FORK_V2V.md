# Fork V2V sobre OpenReel — Guía Maestra de Integración y Mantenimiento

Este documento detalla exhaustivamente la arquitectura de integración de **Video2Video** (backend FastAPI en el repo padre) sobre el frontend de **OpenReel**. 
Está diseñado para que futuros desarrolladores o asistentes de IA (LLMs) entiendan con total precisión cómo funciona la integración, **por qué está estructurada de esta manera, y cómo mantener o actualizar OpenReel desde el upstream oficial sin romper el código ni introducir conflictos de Git**.

---

## 1. Filosofía de la Integración: Módulo Aislado y Mínima Huella (Near-Zero Core Touch)

Toda la funcionalidad de Video2Video vive estrictamente encapsulada en un único directorio modular:
👉 **`apps/web/src/v2v/`**

### ¿Por qué esta estructura?
1. **Cero colisiones con Upstream**: Al no dispersar archivos en `components/`, `stores/`, `lib/` ni `utils/`, cualquier actualización o rebase desde el repositorio oficial de OpenReel (`Augani/openreel-video`) no generará conflictos con los archivos propios de V2V.
2. **Cero cambios de configuración**: No se altera `vite.config.ts`, `tsconfig.json` ni los paths del bundler. Gracias a que OpenReel ya tiene configurado el alias `@/*` apuntando a `./src/*`, cualquier módulo dentro de `src/v2v/` se importa de manera limpia vía `@/v2v` o imports relativos internos (`../stores/`, `../api/`, etc.).
3. **Punto único de contacto en UI**: En toda la aplicación de OpenReel, solo existe **1 punto de montaje** en el código fuente:
   - **`apps/web/src/components/editor/Toolbar.tsx`**: Una única importación y línea JSX que monta `<V2VToolbarEntry />`:
     ```tsx
     import { V2VToolbarEntry } from "@/v2v";
     // ...
     <V2VToolbarEntry />
     ```
4. **Directorios estándar 100% limpios**: Las carpetas nativas de OpenReel (`src/components/`, `src/stores/`, `src/lib/`, `src/utils/`) se mantienen puras, preservando la arquitectura original del proyecto.

> [!IMPORTANT]
> **REGLA MANDATORIA PARA FUTUROS LLMS Y DESARROLLADORES**:
> Cualquier nueva funcionalidad, componente, store, utilidad o cliente API relacionado con Video2Video **DEBE ubicarse dentro de `apps/web/src/v2v/`**. No colocar archivos de V2V en los directorios nativos de OpenReel.

---

## 2. Inventario Total de Archivos de la Integración

### A. Estructura del Módulo Autónomo `apps/web/src/v2v/`

Todos estos archivos son exclusivos de V2V y residen bajo `apps/web/src/v2v/`:

```
apps/web/src/v2v/
├── index.ts                           # Barrel export público (exporta V2VToolbarEntry)
├── api/
│   └── v2v-api.ts                     # Cliente HTTP Typed con FastAPI (/api/job, /api/settings/tokens, etc.)
├── components/
│   ├── V2VToolbarEntry.tsx            # Punto de montaje UI: botón en Toolbar, drawer lateral y modal flotante z-[200]
│   ├── V2VPanel.tsx                   # Panel principal: inferencia, modelos, tokens (FISH/GOOGLE), export a Colab
│   ├── V2VSegmentBulkEditor.tsx       # Editor masivo flotante de segmentos (STT vs TTS, retraducción, emociones, sliders)
│   ├── V2VGenerateTTSSection.tsx      # Generador y sintetizador TTS por segmentos
│   ├── CloneVoiceSegmentSection.tsx   # Clonación y síntesis de voz de clip seleccionado
│   └── ColabExportTab.tsx             # Pestaña de exportación y render final acelerado por GPU en Colab
├── stores/
│   ├── v2v-store.ts                   # Zustand store: estado reactivo de jobs, segmentos, speakers, folderRefs
│   └── colab-export-store.ts          # Zustand store: estado de renderizado y exportación hacia Colab/Catbox
└── utils/
    ├── v2v-segment-regen.ts           # Motor de regeneración de audio sin tocar el caché inmutable de OpenReel
    ├── v2v-segment-ids.ts             # Generador y parser de IDs deterministas de segmentos (jobId + videoIdx + segIdx)
    ├── v2v-utils.ts                   # Normalización de tokens, nombres lógicos y emparejamiento en librería
    ├── v2v-emotions.ts                # Catálogo unificado de emociones Fish Audio (s2.1) y manipulación de tags
    └── v2v-folder-utils.ts            # Helpers de carpetas y assets de jobs V2V en la librería de medios
```

| Archivo | Propósito |
|---|---|
| `src/v2v/index.ts` | **Fachada pública**: exporta `{ V2VToolbarEntry }` para que el resto de la app solo importe desde `@/v2v`. |
| `src/v2v/components/V2VToolbarEntry.tsx` | Monta el botón en el Toolbar, aloja el drawer lateral con `V2VPanel` y el modal flotante (`z-[200]`) del Bulk Editor sin contaminar `Toolbar.tsx` ni `EditorInterface.tsx`. |
| `src/v2v/components/V2VPanel.tsx` | Panel principal de Video2Video: control de inferencia, selección de modelos de transcripción/traducción, configuración de tokens (`FISH_API_KEY`, `GOOGLE_API_KEY`), export a Colab y acceso al editor de segmentos. |
| `src/v2v/components/V2VSegmentBulkEditor.tsx` | Diálogo flotante no bloqueante para edición masiva de segmentos (STT vs TTS, retraducción con Gemini, emociones S2.1, sliders de Fish Audio y regeneración individual). |
| `src/v2v/components/V2VGenerateTTSSection.tsx` | Generación y regeneración de audio TTS para segmentos detectados. |
| `src/v2v/components/CloneVoiceSegmentSection.tsx` | Sección para clonación y síntesis de voz de un clip seleccionado en el timeline. |
| `src/v2v/components/ColabExportTab.tsx` | Pestaña de exportación y render final acelerado por GPU en Colab. |
| `src/v2v/api/v2v-api.ts` | Cliente HTTP Typed con endpoints de FastAPI (`/api/job/...`, `/api/settings/tokens`, etc.). Maneja resolución dinámica para URLs de Colab/ngrok y localhost. |
| `src/v2v/stores/v2v-store.ts` | Zustand store para el estado reactivo del job, segmentos, transcripciones y persistencia de `folderRefs` en `localStorage` (`openreel.v2v.folderRefs`). |
| `src/v2v/stores/colab-export-store.ts` | Zustand store para la cola de exportación por lotes hacia Colab / Catbox. |
| `src/v2v/utils/v2v-segment-regen.ts` | **Motor de regeneración de audio**: sustituye audios en el timeline de forma desacoplada usando la API pública `importMedia` (ver sección 3). |
| `src/v2v/utils/v2v-segment-ids.ts` | IDs estables deterministas para segmentos V2V que persisten independientemente del cambio de nombre de archivo. |
| `src/v2v/utils/v2v-utils.ts` | Normalización de nombres de medios (`segmentLogicalName`), parseo de tokens y emparejamiento en librería. |
| `src/v2v/utils/v2v-emotions.ts` | Catálogo de 50+ emociones y estados de voz para Fish Audio (s2.1). |
| `src/v2v/utils/v2v-folder-utils.ts` | Helpers de agrupación por carpetas de proyectos y snapshots de clips en el timeline. |

---

### B. Archivos Compartidos del Core de OpenReel (Puntos de Montaje Mínimos)

Solo estos archivos del proyecto original contienen líneas adaptadas:

1. **`apps/web/src/components/editor/Toolbar.tsx`**:
   - **Modificación**: Monta el componente encapsulado `<V2VToolbarEntry />` en la sección derecha del header:
     ```tsx
     import { V2VToolbarEntry } from "@/v2v";
     // ...
     <V2VToolbarEntry />
     ```
   - **Regla**: Conservar solo ese import y esa etiqueta JSX.

2. **`apps/web/vite.config.ts` y `.env.example`**:
   - **Modificación**: Configuración de proxy `/api` hacia `127.0.0.1:8000` (`V2V_API_PROXY_TARGET`) y `allowedHosts: true` para admitir dominios dinámicos de Google Colab / Localtunnel.

---

### C. Archivos del Core de OpenReel que están 100% Limpios (NO TOCAR)

> [!IMPORTANT]
> **REGLA DE ORO PARA LLMs Y DESARROLLADORES**: Los siguientes archivos están 100% sincronizados con upstream y **NUNCA DEBEN MODIFICARSE**:
> - `apps/web/src/components/editor/Timeline.tsx` (100% limpio — el z-index `z-[200]` se maneja en `V2VToolbarEntry.tsx`)
> - `apps/web/src/stores/project-store.ts` (100% limpio — la persistencia de proyectos V2V se maneja en `v2v-store.ts` vía `localStorage`)
> - `apps/web/src/components/editor/EditorInterface.tsx` (100% limpio — el modal flotante se aloja en `V2VToolbarEntry.tsx`)
> - `apps/web/src/components/editor/Preview.tsx` (100% limpio — la invalidación de audio se resuelve por nuevo `mediaId`)
> - `apps/web/src/stores/project/media-slice.ts` (100% limpio)
> - `packages/core/src/audio/audio-engine.ts` (100% limpio)
> - `packages/core/src/playback/playback-controller.ts` (100% limpio)
> - `apps/web/src/bridges/playback-bridge.ts` (100% limpio)
> - `apps/web/src/components/editor/AssetsPanel.tsx` (100% limpio)
> - `packages/ui/src/components/dialog.tsx` (100% limpio)

---

## 3. Estrategia de Audio y Caché del Timeline (Desacoplamiento Total)

### El Problema de OpenReel con la Caché de Audio
OpenReel maneja la reproducción de audio en `Preview.tsx` y `PlaybackController` indexando los `AudioBuffer` decodificados en memoria usando el `mediaId` (`${mediaId}:0`). 
Si se regenera un segmento y se sobreescribe el blob manteniendo el mismo `mediaId`, **OpenReel nunca vuelve a decodificar el archivo** porque la clave ya existe en su caché inmutable en RAM. Por eso sonaba el audio original y no el regenerado.

### La Solución Desacoplada (Implementada en `src/v2v/utils/v2v-segment-regen.ts`)
En lugar de parchear las clases internas de OpenReel, la función `applyRegeneratedSegmentToTimeline`:
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

**Resultado**:
- OpenReel detecta un `mediaId` nuevo, no lo encuentra en su caché en RAM y lo decodifica de inmediato: **el Timeline se actualiza al instante**.
- Si el usuario arrastra el medio desde la pestaña Media, arrastra el nuevo audio.
- **Se mantiene el código del core de OpenReel completamente virgen**, garantizando compatibilidad absoluta con futuras versiones.

---

## 4. Sincronización en Backend (`api/routes/render.py` y `api/routes/files.py`)

Al regenerar un segmento desde la UI:
1. Se sube el archivo a `/api/render/upload-media`.
2. En `render.py`, si el nombre coincide con un segmento (`tts_*_NNN.wav`), se escribe tanto en la raíz como en el subdirectorio `Seqs_trg/` y se invoca `register_segment(folder, seg_idx, dest_seqs)` para actualizar el manifiesto de render final.
3. En `files.py`, `serve_file` cuenta con fallback a `Seqs_trg/{filename}` en caso de que se solicite un archivo no presente en la raíz.

---

## 5. Protocolo de Actualización desde Upstream (`Augani/openreel-video`)

Cuando se desee incorporar los últimos cambios del repositorio oficial de OpenReel:

```bash
# 1. Asegurar remote upstream
git remote add openreel-upstream https://github.com/Augani/openreel-video.git 2>/dev/null || true
git fetch openreel-upstream main

# 2. Hacer merge de upstream en la rama monorepo-subtree
git merge openreel-upstream/main --allow-unrelated-histories -m "chore(openreel): merge upstream updates" -X subtree=openreel
```

### Si ocurren conflictos:
1. **Módulo propio de V2V (`openreel/apps/web/src/v2v/*`)**:
   - Tomar nuestra versión (`--ours`). Upstream no tiene este directorio y no habrá conflictos.
2. **Archivos limpios del core (`Timeline.tsx`, `project-store.ts`, `Preview.tsx`, `audio-engine.ts`, `media-slice.ts`, `EditorInterface.tsx`)**:
   - Tomar la versión de upstream (`--theirs`), ya que son archivos upstream puros.
3. **`Toolbar.tsx`**:
   - Aceptar los cambios de upstream y simplemente asegurar que `<V2VToolbarEntry />` esté montado en la barra superior:
     ```tsx
     import { V2VToolbarEntry } from "@/v2v";
     // ...
     <V2VToolbarEntry />
     ```
4. **Validar la compilación**:
   ```bash
   cd openreel/apps/web
   pnpm install
   pnpm run build
   ```
