# Fork V2V sobre OpenReel

Este directorio integra **Video2Video** (API FastAPI en el repo padre), carpetas de medios, clonación de voz en el panel V2V y persistencia `v2vFolderRefs` en el guardado del proyecto.

## Archivos propios del fork (bajo riesgo en sync)

| Área | Ruta |
|------|------|
| Cliente API | `apps/web/src/lib/v2v-api.ts` |
| Estado V2V | `apps/web/src/stores/v2v-store.ts` |
| Utilidades / IDs | `apps/web/src/utils/v2v-utils.ts` (`segmentLogicalName`, `findSegmentMediaInLibrary`, `parseV2VSegmentFromName`), `apps/web/src/utils/v2v-segment-ids.ts` |
| Import masivo | `apps/web/src/utils/import-media-into-project.ts` |
| UI principal | `apps/web/src/components/editor/V2VPanel.tsx`, `ColabExportTab.tsx` |
| Clonar voz segmento | `apps/web/src/components/editor/v2v/CloneVoiceSegmentSection.tsx` |
| Editor masivo segmentos | `apps/web/src/components/editor/v2v/V2VSegmentBulkEditor.tsx`, `apps/web/src/utils/v2v-segment-regen.ts` |
| Caché audio preview | `apps/web/src/stores/audio-cache-store.ts` (dispara `openreel:preview-invalidate`) |
| Env / dev | `apps/web/.env.example` (`VITE_V2V_API_URL`), `apps/web/vite.config.ts` (`allowedHosts`, proxy `/api` → FastAPI) |
| Carpetas / timeline V2V en Assets | `apps/web/src/v2v/assets-integration/` |

## Archivos compartidos con upstream (revisar en cada merge)

- `apps/web/src/components/editor/Toolbar.tsx` — icono YouTube, drawer `V2VPanel`, guardado manual. *(Nota: Se removió el Dialog flotante del Bulk Editor de aquí para reducir huella y minimizar conflictos futuros con upstream).*
- `apps/web/src/components/editor/EditorInterface.tsx` — contenedor principal que ahora aloja el panel absoluto/flotante del editor masivo de V2V justo debajo de la barra superior y sobre el timeline, sincronizando `timelineHeight`.
- `packages/ui/src/components/dialog.tsx` — se añadió la propiedad genérica `hideOverlay` para soportar diálogos transparentes no obstructivos.
- `apps/web/src/components/editor/AssetsPanel.tsx` — enganches en pestaña Media (`useV2VMediaFolders`, import/drop V2V).
- `apps/web/src/stores/project-store.ts` — `v2vFolderRefs` en `forceSave`; `replaceMediaAsset` persiste blob + invalida preview.
- `apps/web/src/components/editor/GenerateAudioSegmentSection.tsx` — TTS por carpeta y API v2v.
- Repo padre: `api/routes/render.py` — resolución de medios TTS por índice en `v2v_assets.json` (prioridad sobre copias obsoletas).
- Repo padre: `api/routes/segments.py` — editor masivo (`GET segments-editor`, `POST retranslate-segments`); `src/translation.py` modos `shorter` / `similar_length`.

**Ya no tocar en upstream:** `InspectorPanel.tsx` no incluye Clone Voice (vive solo en `V2VPanel`).

## Comportamiento V2V relevante

### Dev / Colab

- Vite (`:5173`) hace proxy de `/api/*` a FastAPI (`V2V_API_PROXY_TARGET`, por defecto `http://127.0.0.1:8000`).
- `allowedHosts: true` evita bloqueo del host variable de Colab/Codatalab.

### Import automático al timeline (tras inferencia)

1. Al terminar el job (`status === done`), `v2v-store` descarga video, instrumental y segmentos TTS.
2. Los WAV TTS usan el **`filename` real** del API (`GET /audio-segments`), vía `segmentLogicalName()` — no se reconstruye solo desde `speaker`.
3. Se montan pistas por speaker con `addClip` en `seg.start`; si falla la descarga de todos los TTS, el import queda en `error` (no `done` con timeline incompleto).
4. El proyecto se guarda en **autosave**. Si el proyecto activo ya se llama igual que la carpeta V2V, se aplica `loadProject` al editor; si no, toast para abrir/recuperar ese proyecto.
5. Al elegir el video en el dropdown V2V, se recupera el **autosave más reciente** de ese nombre (también si ya era el proyecto activo).

### Clonar voz de un segmento

1. Seleccionar clip de audio TTS en el timeline → panel **Video2Video** → sección **Clonar voz del segmento**.
2. Tras regenerar: `replaceMediaAsset` actualiza blob/waveform, invalida caché de preview (`openreel:preview-invalidate`), sube WAV a Colab (`uploadMediaForRender`) y `syncFolderAssets`.
3. Export FFmpeg en Colab resuelve segmentos por índice en `segments` del manifiesto, no por copias antiguas en otras claves.

### Editor masivo de segmentos

1. Con job activo y video importado (`v2vFolderRefs`), panel **Video2Video** → **Editar segmentos** (entre “Video procesado” y “Clonar voz”).
2. `GET /api/job/{job_id}/segments-editor/{video_index}` lee `result.pkl`: columna **Original (STT)** vs **TTS**; fusiona textos editados del store.
3. **Proponer traducción** → `POST /api/retranslate-segments` con modo **Más corto** o **Longitud similar** (solo filas seleccionadas).
4. **Aplicar** llama `regenerate-segment` por fila modificada y `applyRegeneratedSegmentToTimeline` (misma lógica que Clone Voice). **Encajar slot** usa `target_duration` (modo velocidad `s`).
5. Filtro “Solo problemáticos”: ratio texto TTS/original > 1.15 o speed > 1.05.

## Cómo actualizar desde `Augani/openreel-video`

```bash
git fetch openreel-upstream main
git merge openreel-upstream/main --allow-unrelated-histories -m "Merge OpenReel upstream main" -X subtree=openreel
```

Si aparecen muchos conflictos `AA` (add/add):

1. `git checkout --theirs openreel` y `git add openreel` para tomar la base upstream.
2. Restaurar desde la rama anterior los archivos **solo V2V** de la tabla de arriba.
3. Reaplicar parches en Toolbar, `project-store.ts`, `.env.example`, `vite.config.ts`.
4. **AssetsPanel**: conservar upstream e insertar bloque V2V en `case "media"`.
5. **No reintroducir** Clone Voice en `InspectorPanel`.
6. `pnpm install && pnpm run build` dentro de `openreel/`.

## Comprobación rápida

- Build: `cd openreel && pnpm run build`
- Panel Video2Video: procesar URL → al completar, timeline con Video + INSTRUMENTAL + pistas TTS por speaker.
- Clonar voz en clip TTS → preview y export Colab con audio nuevo.
- `v2vFolderRefs` tras guardar y recuperar autosave.
