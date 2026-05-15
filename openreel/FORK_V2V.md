# Fork V2V sobre OpenReel

Este directorio integra **Video2Video** (API FastAPI en el repo padre), carpetas de medios, clonación de voz en el inspector y persistencia `v2vFolderRefs` en el guardado del proyecto.

## Archivos propios del fork (bajo riesgo en sync)

| Área | Ruta |
|------|------|
| Cliente API | `apps/web/src/lib/v2v-api.ts` |
| Estado V2V | `apps/web/src/stores/v2v-store.ts` |
| Utilidades / IDs | `apps/web/src/utils/v2v-utils.ts`, `apps/web/src/utils/v2v-segment-ids.ts` |
| Import masivo | `apps/web/src/utils/import-media-into-project.ts` |
| UI | `apps/web/src/components/editor/V2VPanel.tsx`, `ColabExportTab.tsx` |
| Inspector | `apps/web/src/components/editor/inspector/CloneVoiceSegmentSection.tsx` |
| Env | `apps/web/.env.example` (bloque `VITE_V2V_API_URL`) |

## Archivos compartidos con upstream (revisar en cada merge)

- `apps/web/src/components/editor/Toolbar.tsx` — icono YouTube, drawer `V2VPanel`, guardado manual.
- `apps/web/src/components/editor/AssetsPanel.tsx` — carpetas `nombre/carpeta`, import V2V, diálogos de carpeta.
- `apps/web/src/components/editor/InspectorPanel.tsx` — sección **Clone Voice (V2V)** en clips de audio.
- `apps/web/src/components/editor/inspector/index.ts` — export de `CloneVoiceSegmentSection`.
- `apps/web/src/stores/project-store.ts` — `v2vFolderRefs` en `forceSave` y al recuperar autosave.
- `apps/web/src/components/editor/GenerateAudioSegmentSection.tsx` — TTS por carpeta y API v2v.

## Cómo actualizar desde `Augani/openreel-video`

El historial del prefijo `openreel/` no comparte ancestros con el upstream; `git subtree pull` puede responder *refusing to merge unrelated histories*. En este repo se usa:

```bash
git fetch openreel-upstream main
git merge openreel-upstream/main --allow-unrelated-histories -m "Merge OpenReel upstream main" -X subtree=openreel
```

Si aparecen muchos conflictos `AA` (add/add), una estrategia que funcionó aquí:

1. `git checkout --theirs openreel` y `git add openreel` para tomar la base upstream.
2. Restaurar desde la rama anterior los archivos **solo V2V** de la tabla de arriba (`git checkout <rama-base>:openreel/apps/web/...`).
3. Reaplicar a mano los parches en Toolbar, InspectorPanel, `inspector/index.ts`, `project-store.ts` y `.env.example`.
4. Para **AssetsPanel**: el upstream añadió pestañas (p. ej. Recipes/Templates) y KieAI; la versión con V2V completo puede ser la anterior del fork — conviene fusionar después las nuevas pestañas si las necesitas.

5. `pnpm install && pnpm run build` dentro de `openreel/`.

## Comprobación rápida

- Build: `cd openreel && pnpm run build`
- Panel Video2Video (toolbar), carpetas en Assets, audio → Clone Voice, proyecto con `v2vFolderRefs` tras guardar y recuperar.
