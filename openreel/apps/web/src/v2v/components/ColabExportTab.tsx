import React, { useCallback, useEffect, useState } from "react";
import {
  Server,
  Download,
  Archive,
  Loader2,
  AlertTriangle,
  CheckCircle,
  Upload,
  Link as LinkIcon,
  Sparkles,
  Save,
} from "lucide-react";
import { Button, Switch, Label, Input } from "@openreel/ui";
import {
  v2vApi,
  type TimelineClipPayload,
  type BatchRenderItemPayload,
} from "../api/v2v-api";
import { useProjectStore } from "@/stores/project-store";
import { useV2VStore } from "../stores/v2v-store";
import { autoSaveManager } from "@/services/auto-save";
import type { AutoSaveMetadata } from "@/services/auto-save";
import type { Project, MediaItem } from "@openreel/core";
import { useColabExportStore, type CatboxVideoResult } from "../stores/colab-export-store";
import { RenderProgressBar } from "./RenderProgressBar";
import { CatboxUploadStatus } from "./CatboxUploadStatus";
import { BatchRenderQueue } from "./BatchRenderQueue";

// ----------------------------------------------------------------
// Types
// ----------------------------------------------------------------

type ClipStatus = "ok" | "upload_needed" | "not_allowed";

interface AnalyzedClip {
  clipId: string;
  mediaId: string;
  mediaName: string;
  type: "video" | "audio";
  start: number;
  end: number;
  trackStart: number;
  volume: number;
  status: ClipStatus;
  blob?: Blob;
}

interface SavedProject {
  meta: AutoSaveMetadata;
  project?: Project;
  selected: boolean;
}

// ----------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------

/** Determine if a media_name belongs to a V2V folder (already in Colab). */
function isInV2VFolder(
  mediaName: string,
  folderRefs: Record<string, any>,
): boolean {
  const norm = mediaName.replace(/\\/g, "/");
  const filename = norm.split("/").pop() || norm;

  for (const folderKey of Object.keys(folderRefs)) {
    const ref = folderRefs[folderKey];
    if (ref.nativeFiles && Array.isArray(ref.nativeFiles)) {
      if (ref.nativeFiles.includes(filename) || ref.nativeFiles.includes(norm)) {
        return true;
      }
    }
  }

  // Detección tolerante de medios que provienen intrínsecamente del pipeline V2V en Colab
  const isV2VStandardAsset =
    filename.startsWith("tts_") ||
    filename.startsWith("seg_") ||
    filename.startsWith("video_only") ||
    filename.startsWith("merged") ||
    filename.includes("tts_") ||
    filename.includes("seg_");

  if (isV2VStandardAsset && Object.keys(folderRefs).length > 0) {
    return true;
  }

  return false;
}

function analyzeProject(
  project: Project,
  folderRefs: Record<string, unknown>,
): AnalyzedClip[] {
  const mediaMap = new Map<string, MediaItem>(
    project.mediaLibrary.items.map((m) => [m.id, m]),
  );

  const clips: AnalyzedClip[] = [];

  for (const track of project.timeline.tracks) {
    if (track.type !== "video" && track.type !== "audio") continue;

    for (const clip of track.clips) {
      const media = mediaMap.get(clip.mediaId);
      if (!media) continue;
      if (media.type === "image") continue;

      const inServer = isInV2VFolder(media.name, folderRefs);
      const hasBlob = !!media.blob;

      let status: ClipStatus;
      if (inServer) {
        status = "ok";
      } else if (hasBlob) {
        status = "upload_needed";
      } else {
        status = "not_allowed";
      }

      clips.push({
        clipId: clip.id,
        mediaId: clip.mediaId,
        mediaName: media.name,
        type: track.type as "video" | "audio",
        start: clip.inPoint ?? 0,
        end: clip.outPoint ?? (clip.inPoint ?? 0) + clip.duration,
        trackStart: clip.startTime,
        volume: clip.volume ?? 1.0,
        status,
        blob: media.blob ?? undefined,
      });
    }
  }

  return clips;
}

async function uploadPendingClips(
  clips: AnalyzedClip[],
  jobId: string,
  videoIndex: number,
  onProgress: (msg: string) => void,
): Promise<Map<string, string>> {
  const nameMap = new Map<string, string>();
  const toUpload = clips.filter((c) => c.status === "upload_needed" && c.blob);

  for (const clip of toUpload) {
    onProgress(`Subiendo ${clip.mediaName}…`);
    const file = clip.blob instanceof File
      ? clip.blob
      : new File([clip.blob!], clip.mediaName.split("/").pop() || "media", {
          type: clip.type === "video" ? "video/mp4" : "audio/wav",
        });
    const parts = clip.mediaName.replace(/\\/g, "/").split("/");
    const subfolder = parts.length > 1 ? parts[0] : "";
    const result = await v2vApi.uploadMediaForRender(jobId, videoIndex, file, subfolder);
    nameMap.set(clip.mediaName, result.media_name);
    
    const folder = subfolder || (result.media_name.includes("/") ? result.media_name.split("/")[0] : "");
    if (folder) {
      await useV2VStore.getState().syncFolderAssets(jobId, videoIndex, folder);
    }
  }

  return nameMap;
}

function buildPayloadClips(
  clips: AnalyzedClip[],
  uploadedMap: Map<string, string>,
): TimelineClipPayload[] {
  return clips
    .filter((c) => c.status !== "not_allowed")
    .map((c) => ({
      type: c.type,
      media_name: uploadedMap.get(c.mediaName) ?? c.mediaName,
      start: c.start,
      end: c.end,
      track_start: c.trackStart,
      volume: c.volume,
    }));
}

function downloadBlob(blob: Blob, filename: string) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 10000);
}

// ----------------------------------------------------------------
// Component
// ----------------------------------------------------------------

export const ColabExportTab: React.FC = () => {
  const { project } = useProjectStore();
  const { folderRefs, syncFolderAssets } = useV2VStore();

  const {
    isBatch,
    setIsBatch,
    uploadToCatbox,
    setUploadToCatbox,
    deselectedProjectIds,
    toggleProjectId,
    selectAllProjects,
    deselectAllProjects,
    status,
    setStatus,
    statusMsg,
    setStatusMsg: _setStatusMsg,
    errorMsg,
    setErrorMsg,
    progress,
    currentStep,
    currentVideoName,
    currentIdx,
    totalVideos,
    setProgressData,
    catboxUrl,
    setCatboxUrl,
    catboxVideos,
    setCatboxVideos,
    getActiveGeminiModel,
    exportLogs: _exportLogs,
    appendExportLog,
    clearExportLogs,
    openExportLogs,
    resetStatus,
  } = useColabExportStore();

  const [savedMetas, setSavedMetas] = useState<AutoSaveMetadata[]>([]);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  // ── Viral Title states ────────────────────────────────────────
  const [customTitleInput, setCustomTitleInput] = useState<string>("");
  const [isRegeneratingTitle, setIsRegeneratingTitle] = useState(false);
  const [isSavingTitle, setIsSavingTitle] = useState(false);
  const [titleFeedback, setTitleFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);
  const [batchRegeneratingId, setBatchRegeneratingId] = useState<string | null>(null);

  // ── Analyze current project ──────────────────────────────────
  const analyzed = React.useMemo(
    () => analyzeProject(project, folderRefs),
    [project, folderRefs],
  );

  const notAllowed = analyzed.filter((c) => c.status === "not_allowed");
  const needUpload = analyzed.filter((c) => c.status === "upload_needed");
  const totalClips = analyzed.filter((c) => c.status !== "not_allowed").length;

  // Get job/video context and a descriptive name from folderRefs matching media names, projectId o session
  const jobContext = React.useMemo(() => {
    const refs = folderRefs as Record<string, any>;
    const refEntries = Object.entries(refs);
    if (refEntries.length === 0) {
      // Fallback si no hay folderRefs aún en storage pero hay sesión activa en V2V store
      const v2vState = useV2VStore.getState();
      if (v2vState.jobId) {
        const currentIdx = v2vState.selectedVideoIndex ?? 0;
        const curVid = v2vState.videos?.[currentIdx];
        return {
          jobId: v2vState.jobId,
          videoIndex: currentIdx,
          outputName: curVid?.output_name || project?.name || "export",
          longName: curVid?.output_name || project?.name || "export",
          nativeFiles: [],
        };
      }
      return null;
    }

    // Estrategia 1: Coincidencia por nativeFiles con clips válidos
    for (const clip of analyzed) {
      const filename = clip.mediaName.split("/").pop() || clip.mediaName;
      for (const [folderKey, ref] of refEntries) {
        if (
          ref.nativeFiles &&
          Array.isArray(ref.nativeFiles) &&
          (ref.nativeFiles.includes(filename) || ref.nativeFiles.includes(clip.mediaName))
        ) {
          return { ...ref, longName: ref.outputName || folderKey };
        }
      }
    }

    // Estrategia 2: Coincidencia por projectId (el ID del proyecto actual en OpenReel)
    if (project?.id) {
      for (const [folderKey, ref] of refEntries) {
        if (ref.projectId === project.id) {
          return { ...ref, longName: ref.outputName || folderKey };
        }
      }
    }

    // Estrategia 3: Coincidencia por nombre de proyecto o carpeta
    const projNameNorm = (project?.name || "").trim().toLowerCase();
    if (projNameNorm) {
      for (const [folderKey, ref] of refEntries) {
        const outNorm = (ref.outputName || "").trim().toLowerCase();
        const fKeyNorm = folderKey.trim().toLowerCase();
        if (
          (outNorm && (outNorm === projNameNorm || projNameNorm.includes(outNorm) || outNorm.includes(projNameNorm))) ||
          (fKeyNorm && (fKeyNorm === projNameNorm || projNameNorm.includes(fKeyNorm) || fKeyNorm.includes(projNameNorm)))
        ) {
          return { ...ref, longName: ref.outputName || folderKey };
        }
      }
    }

    // Estrategia 4: Coincidencia por sesión activa de V2V store
    const v2vState = useV2VStore.getState();
    if (v2vState.jobId) {
      const currentIdx = v2vState.selectedVideoIndex ?? 0;
      for (const [folderKey, ref] of refEntries) {
        if (ref.jobId === v2vState.jobId && ref.videoIndex === currentIdx) {
          return { ...ref, longName: ref.outputName || folderKey };
        }
      }
      const curVid = v2vState.videos?.[currentIdx];
      return {
        jobId: v2vState.jobId,
        videoIndex: currentIdx,
        outputName: curVid?.output_name || project?.name || "export",
        longName: curVid?.output_name || project?.name || "export",
        nativeFiles: [],
      };
    }

    // Estrategia 5: Si sólo hay una carpeta registrada en folderRefs
    if (refEntries.length === 1) {
      const [folderKey, ref] = refEntries[0];
      return { ...ref, longName: ref.outputName || folderKey };
    }

    return null;
  }, [analyzed, folderRefs, project]);

  // Detectar si el timeline conserva el video continuo sin cortes de video (Stream Copy directo)
  const isStreamCopyCandidate = React.useMemo(() => {
    if (!project?.timeline?.tracks) return false;
    const vTracks = project.timeline.tracks.filter((t) => t.type === "video");
    const vClips = vTracks.flatMap((t) => t.clips || []);
    return (
      vClips.length === 1 &&
      (vClips[0].startTime || 0) <= 0.05 &&
      (vClips[0].inPoint || 0) <= 0.05
    );
  }, [project]);

  // Modo de exportación: 'auto' (Stream Copy si es posible) o 'reencode' (Forzar GPU NVENC)
  const [exportMode, setExportMode] = useState<"auto" | "reencode">("auto");
  const effectiveMode = isStreamCopyCandidate && exportMode === "auto" ? "stream_copy" : "reencode";

  // ── Auto-sync with backend manifest ──────────────────────────
  useEffect(() => {
    if (jobContext && !isBatch) {
      const parts = jobContext.longName?.replace(/\\/g, "/").split("/");
      const folder = parts ? parts[0] : "";
      if (folder) {
        syncFolderAssets(jobContext.jobId, jobContext.videoIndex, folder);
      }
    }
  }, [jobContext?.jobId, jobContext?.videoIndex, isBatch]);

  // ── Load saved projects for batch mode ──────────────────────
  useEffect(() => {
    if (!isBatch) return;
    setLoadingSaved(true);
    autoSaveManager.checkForRecovery().then((metas) => {
      const uniqueProjects = new Map<string, AutoSaveMetadata>();
      for (const meta of metas) {
        if (!uniqueProjects.has(meta.projectId)) {
          uniqueProjects.set(meta.projectId, meta);
        }
      }
      setSavedMetas(Array.from(uniqueProjects.values()));
      setLoadingSaved(false);
    });
  }, [isBatch]);

  const savedProjects: SavedProject[] = React.useMemo(() => {
    return savedMetas.map((meta) => ({
      meta,
      selected: !deselectedProjectIds.includes(meta.id),
    }));
  }, [savedMetas, deselectedProjectIds]);

  const toggleProject = (id: string) => {
    toggleProjectId(id);
  };

  const toggleAll = () => {
    const allSelected = savedProjects.length > 0 && savedProjects.every((p) => p.selected);
    if (allSelected) {
      deselectAllProjects(savedMetas.map((m) => m.id));
    } else {
      selectAllProjects();
    }
  };

  const copyToClipboard = async (text: string, index?: number) => {
    try {
      await navigator.clipboard.writeText(text);
      if (index !== undefined) {
        setCopiedIndex(index);
        setTimeout(() => setCopiedIndex(null), 2000);
      }
    } catch {
      // fallback
    }
  };

  // ── Gemini & Viral Title Effects & Handlers ──────────────────
  useEffect(() => {
    const raw = (jobContext?.longName || project.name || "").replace(/^\d+[._\s]*/, "");
    setCustomTitleInput(raw);
  }, [jobContext?.longName, project.name]);

  const handleRegenerateViralTitle = async (
    targetJobId?: string,
    targetVideoIndex?: number,
    targetFolderName?: string,
  ) => {
    const jId = targetJobId || jobContext?.jobId;
    const vIdx = targetVideoIndex !== undefined ? targetVideoIndex : jobContext?.videoIndex;
    const fName =
      targetFolderName || (jobContext?.longName ? jobContext.longName.split("/")[0] : undefined);

    if (!jId && !fName) {
      setTitleFeedback({
        type: "error",
        msg: "No se encontró el job o carpeta de Colab asociado a este video.",
      });
      return;
    }

    setIsRegeneratingTitle(true);
    setTitleFeedback(null);
    try {
      const activeModel = getActiveGeminiModel();
      const res = await v2vApi.regenerateTitle({
        job_id: jId,
        video_index: vIdx ?? 0,
        folder_name: fName,
        model_name: activeModel,
      });

      if (res && res.output_name) {
        setCustomTitleInput(res.output_name);
        await useV2VStore.getState().updateVideoOutputName(vIdx ?? 0, res.output_name, jId);

        setTitleFeedback({
          type: "success",
          msg: `¡Título viral generado con ${res.model_used || activeModel}!`,
        });
        setTimeout(() => setTitleFeedback(null), 5000);
      }
    } catch (err: any) {
      setTitleFeedback({
        type: "error",
        msg: err.message || "Error al regenerar título viral con IA",
      });
    } finally {
      setIsRegeneratingTitle(false);
    }
  };

  const handleSaveManualTitle = async () => {
    if (!customTitleInput.trim()) return;
    const jId = jobContext?.jobId;
    const vIdx = jobContext?.videoIndex;
    const fName = jobContext?.longName ? jobContext.longName.split("/")[0] : undefined;

    setIsSavingTitle(true);
    setTitleFeedback(null);
    try {
      const res = await v2vApi.regenerateTitle({
        job_id: jId,
        video_index: vIdx ?? 0,
        folder_name: fName,
        custom_title: customTitleInput.trim(),
      });

      if (res && res.output_name) {
        setCustomTitleInput(res.output_name);
        await useV2VStore.getState().updateVideoOutputName(vIdx ?? 0, res.output_name, jId);

        setTitleFeedback({
          type: "success",
          msg: "¡Título guardado y actualizado con éxito!",
        });
        setTimeout(() => setTitleFeedback(null), 3500);
      }
    } catch (err: any) {
      setTitleFeedback({
        type: "error",
        msg: err.message || "Error al guardar título",
      });
    } finally {
      setIsSavingTitle(false);
    }
  };

  const handleBatchRegenerateViralTitle = async (sp: SavedProject) => {
    setBatchRegeneratingId(sp.meta.id);
    try {
      const fullProj = await autoSaveManager.recover(sp.meta.id);
      const mediaMap = new Map<string, MediaItem>(
        (fullProj?.mediaLibrary?.items || []).map((m: MediaItem) => [m.id, m]),
      );
      let targetJobId: string | undefined;
      let targetVideoIndex: number | undefined;
      let targetFolderName: string | undefined;

      for (const t of fullProj?.timeline?.tracks || []) {
        for (const c of t.clips || []) {
          const m = mediaMap.get(c.mediaId);
          if (m) {
            const fname = m.name.split("/").pop() || m.name;
            for (const [fKey, ref] of Object.entries(folderRefs as Record<string, any>)) {
              if (ref.nativeFiles && Array.isArray(ref.nativeFiles) && ref.nativeFiles.includes(fname)) {
                targetJobId = ref.jobId;
                targetVideoIndex = ref.videoIndex;
                targetFolderName = ref.outputName || fKey;
                break;
              }
            }
          }
          if (targetJobId) break;
        }
        if (targetJobId) break;
      }

      const activeModel = getActiveGeminiModel();
      const res = await v2vApi.regenerateTitle({
        job_id: targetJobId,
        video_index: targetVideoIndex ?? 0,
        folder_name: targetFolderName,
        model_name: activeModel,
      });

      if (res && res.output_name && fullProj) {
        await useV2VStore.getState().updateVideoOutputName(
          targetVideoIndex ?? 0,
          res.output_name,
          targetJobId,
        );
        // refrescar lista
        const metas = await autoSaveManager.checkForRecovery();
        const unique = new Map<string, AutoSaveMetadata>();
        for (const meta of metas) {
          if (!unique.has(meta.projectId)) unique.set(meta.projectId, meta);
        }
        setSavedMetas(Array.from(unique.values()));
      }
    } catch (e: any) {
      console.error("Error regenerando título en batch:", e);
    } finally {
      setBatchRegeneratingId(null);
    }
  };


  // ── Single export ────────────────────────────────────────────
  const handleSingleExport = useCallback(async () => {
    if (!jobContext) {
      setErrorMsg("No se pudo determinar el job de Colab. Asegúrate de que el proyecto tiene medios V2V.");
      setStatus("error");
      return;
    }

    clearExportLogs();
    openExportLogs();
    const tExportStart = performance.now();
    const rawName = jobContext.longName || project.name || "export";
    const outName = rawName.replace(/^\d+[._\s]*/, "");

    appendExportLog(`🎬 [Export Single] Iniciando exportación de "${outName}"...`);
    setStatus("uploading");
    setErrorMsg("");
    setCatboxUrl(null);
    setCatboxVideos([]);
    setProgressData({
      progress: 10,
      currentStep: "Paso 1/3: Preparando clips...",
      currentVideoName: project.name,
      currentIdx: 1,
      totalVideos: 1,
      statusMsg: "Analizando proyecto...",
    });

    try {
      const tPrepStart = performance.now();
      const tUploadStart = performance.now();
      const uploadedMap = await uploadPendingClips(
        analyzed,
        jobContext.jobId,
        jobContext.videoIndex,
        (msg) => {
          setProgressData({
            progress: 30,
            currentStep: "Paso 2/3: Subiendo medios a Colab...",
            statusMsg: msg,
          });
        },
      );
      const tUploadSec = ((performance.now() - tUploadStart) / 1000).toFixed(1);
      if (needUpload.length > 0) {
        appendExportLog(`⏱️ [Etapa: Subida de Medios] ${needUpload.length} archivo(s) subidos en ${tUploadSec}s`);
      } else {
        appendExportLog(`⚡ [Medios] Activos listos en Colab (sin subida requerida)`);
      }

      setStatus("rendering");
      setProgressData({
        progress: 60,
        currentStep: uploadToCatbox
          ? "Paso 3/3: Renderizando y subiendo a Catbox…"
          : effectiveMode === "stream_copy"
            ? "Paso 3/3: Empaquetando MP4 en Colab (Stream Copy)…"
            : "Paso 3/3: Renderizando MP4 en Colab (GPU T4 NVENC)…",
        currentVideoName: outName,
        statusMsg: uploadToCatbox
          ? "Renderizando y subiendo a Catbox…"
          : effectiveMode === "stream_copy"
            ? "Empaquetando en Colab (Stream Copy)…"
            : "Renderizando en Colab (GPU NVENC)…",
      });

      const clips = buildPayloadClips(analyzed, uploadedMap);
      const tPrepSec = ((performance.now() - tPrepStart) / 1000).toFixed(1);
      appendExportLog(`⏱️ [Etapa: Preparación] ${clips.length} clip(s) analizados en ${tPrepSec}s`);

      appendExportLog(`🚀 [Etapa: Render Colab] Procesando timeline en Colab...`);
      const tRenderColabStart = performance.now();
      const result = await v2vApi.renderTimeline({
        job_id: jobContext.jobId,
        video_index: jobContext.videoIndex,
        clips,
        output_name: outName,
        upload_to_catbox: uploadToCatbox,
        mode: effectiveMode,
      });
      const tRenderColabSec = ((performance.now() - tRenderColabStart) / 1000).toFixed(1);

      // Check if result is Catbox upload response
      if (uploadToCatbox && result && typeof result === "object" && "url" in result) {
        const catboxResult = result as any;
        setCatboxUrl(catboxResult.url);
        setStatus("done");
        setProgressData({
          progress: 100,
          currentStep: "¡Completado!",
          statusMsg: "¡Video subido a Catbox!",
        });
        if (catboxResult.timings) {
          const mode = catboxResult.mode || catboxResult.timings?.mode || "FFmpeg";
          appendExportLog(`⏱️ [Colab Backend] Modo: ${mode} | FFmpeg: ${catboxResult.timings.ffmpeg}s | Catbox: ${catboxResult.timings.catbox}s`);
        }
        appendExportLog(`⏱️ [Etapa: Render + Catbox] Completado en ${tRenderColabSec}s`);
        appendExportLog(`🔗 Enlace Catbox: ${catboxResult.url}`);
      } else {
        downloadBlob(result as Blob, `${outName}.mp4`);
        setStatus("done");
        setProgressData({
          progress: 100,
          currentStep: "¡Completado!",
          statusMsg: "¡Exportación completada!",
        });
        const bTimings = (result as any)?.timings;
        if (bTimings?.ffmpeg !== undefined) {
          const modeLabel = bTimings.mode ? ` [${bTimings.mode}]` : "";
          appendExportLog(`⏱️ [Colab Backend] Modo:${modeLabel} | FFmpeg: ${bTimings.ffmpeg}s ${bTimings.cached ? '(Caché)' : ''}`);
        }
        appendExportLog(`⏱️ [Etapa: Render Colab] Descarga MP4 completada en ${tRenderColabSec}s`);
      }

      const tTotalSec = ((performance.now() - tExportStart) / 1000).toFixed(1);
      appendExportLog("=".repeat(50));
      appendExportLog(`🏁 RESUMEN EXPORTACIÓN VIDEO: ${outName}`);
      appendExportLog(`• Tiempo total: ${tTotalSec}s`);
      appendExportLog("=".repeat(50));
    } catch (e) {
      setStatus("error");
      const err = e instanceof Error ? e.message : "Error desconocido";
      setErrorMsg(err);
      appendExportLog(`❌ Error en exportación: ${err}`);
    }
  }, [analyzed, jobContext, project.name, uploadToCatbox, setStatus, setErrorMsg, setCatboxUrl, setCatboxVideos, setProgressData, appendExportLog, clearExportLogs, openExportLogs, needUpload.length, effectiveMode]);

  // ── Batch export ─────────────────────────────────────────────
  const handleBatchExport = useCallback(async () => {
    const selected = savedProjects.filter((p) => p.selected);
    if (selected.length === 0) {
      setErrorMsg("Selecciona al menos un proyecto.");
      setStatus("error");
      return;
    }

    clearExportLogs();
    openExportLogs();
    const tBatchStart = performance.now();

    const totalSelected = selected.length;
    appendExportLog(`🚀 [Batch Export] Iniciando exportación de ${totalSelected} proyectos...`);
    setStatus("uploading");
    setErrorMsg("");
    setCatboxUrl(null);
    setCatboxVideos([]);
    setProgressData({
      progress: 5,
      currentStep: `Paso 1/2: Preparando proyectos (0/${totalSelected})`,
      currentVideoName: selected[0]?.meta.projectName || "",
      currentIdx: 0,
      totalVideos: totalSelected,
      statusMsg: "Iniciando preparación...",
    });

    let progressInterval: ReturnType<typeof setInterval> | null = null;

    try {
      const renders: BatchRenderItemPayload[] = [];

      for (let i = 0; i < selected.length; i++) {
        const sp = selected[i];
        const currentNum = i + 1;
        const prepPct = Math.round((i / totalSelected) * 20);
        const tProjStart = performance.now();

        setProgressData({
          progress: prepPct,
          currentStep: `Paso 1/2: Preparando proyecto (${currentNum}/${totalSelected})`,
          currentVideoName: sp.meta.projectName,
          currentIdx: currentNum,
          totalVideos: totalSelected,
          statusMsg: `Preparando: ${sp.meta.projectName}…`,
        });

        const fullProject = await autoSaveManager.recover(sp.meta.id);
        if (!fullProject) continue;

        const clips = analyzeProject(fullProject, folderRefs);
        const ctx = clips.reduce<{ jobId: string; videoIndex: number } | null>((acc, c) => {
          if (acc) return acc;
          if (c.status !== "not_allowed") {
            const filename = c.mediaName.split("/").pop() || c.mediaName;
            for (const [folderKey, ref] of Object.entries(folderRefs as Record<string, any>)) {
              if (ref.nativeFiles && Array.isArray(ref.nativeFiles) && ref.nativeFiles.includes(filename)) {
                return { ...ref, longName: ref.outputName || folderKey };
              }
            }
          }
          return null;
        }, null);

        if (!ctx) continue;

        const uploadedMap = await uploadPendingClips(
          clips,
          ctx.jobId,
          ctx.videoIndex,
          (msg) => {
            setProgressData({
              progress: prepPct + 1,
              currentStep: `Paso 1/2: Subiendo medios (${currentNum}/${totalSelected})`,
              currentVideoName: sp.meta.projectName,
              statusMsg: msg,
            });
          },
        );

        const outName = ((ctx as any).longName || fullProject.name || sp.meta.projectName || "export").replace(/^\d+[._\s]*/, "");
        const tProjSec = ((performance.now() - tProjStart) / 1000).toFixed(1);
        appendExportLog(`📁 [${currentNum}/${totalSelected}] Preparado: "${outName}" (${tProjSec}s)`);

        renders.push({
          job_id: ctx.jobId,
          video_index: ctx.videoIndex,
          clips: buildPayloadClips(clips, uploadedMap),
          output_name: outName,
          mode: exportMode === "reencode" ? "reencode" : "auto",
        });
      }

      if (renders.length === 0) {
        throw new Error("Ningún proyecto tiene medios de Colab disponibles.");
      }

      const batchId = `batch_${Date.now()}`;

      setStatus("rendering");
      setProgressData({
        progress: 20,
        currentStep: `Paso 2/2: Renderizando videos en Colab (1/${renders.length})`,
        currentVideoName: renders[0]?.output_name || "",
        currentIdx: 1,
        totalVideos: renders.length,
        statusMsg: uploadToCatbox
          ? `Renderizando y subiendo ${renders.length} videos a Catbox…`
          : `Renderizando ${renders.length} proyectos en Colab…`,
      });

      appendExportLog(`🚀 [Batch Colab] Iniciando render paralelo de ${renders.length} videos en Colab...`);

      // Polling activo de progreso y logs al backend
      const seenBackendLogs = new Set<string>();
      progressInterval = setInterval(async () => {
        try {
          const p = await v2vApi.getBatchProgress(batchId);
          if (p) {
            if (p.logs && Array.isArray(p.logs)) {
              for (const line of p.logs) {
                if (!seenBackendLogs.has(line)) {
                  seenBackendLogs.add(line);
                  appendExportLog(line);
                }
              }
            }

            if (p.total > 0) {
              const scaled = Math.min(95, Math.max(20, Math.round(20 + (p.percentage * 0.75))));
              useColabExportStore.getState().setProgressData({
                progress: scaled,
                currentStep: p.step || `Renderizando (${p.current}/${p.total})`,
                currentVideoName: p.current_name || "",
                currentIdx: p.current,
                totalVideos: p.total,
                statusMsg: p.step || `Renderizando ${p.current} de ${p.total}`,
              });
            }
          }
        } catch {
          // ignore polling errors
        }
      }, 1000);

      const result = await v2vApi.renderBatch({
        renders,
        zip_name: "batch_export",
        upload_to_catbox: uploadToCatbox,
        batch_id: batchId,
        mode: exportMode === "reencode" ? "reencode" : "auto",
      });

      if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
      }

      // Check if result is Catbox upload response
      if (uploadToCatbox && result && typeof result === "object" && "videos" in result) {
        const batchResult = result as { videos: CatboxVideoResult[]; logs?: string[]; total_time?: number };
        setCatboxVideos(batchResult.videos);
        setStatus("done");
        setProgressData({
          progress: 100,
          currentStep: "¡Completado!",
          statusMsg: `¡${batchResult.videos.length} video(s) subido(s) a Catbox!`,
        });
      } else {
        // Normal download
        downloadBlob(result as Blob, "batch_export.zip");
        setStatus("done");
        setProgressData({
          progress: 100,
          currentStep: "¡Completado!",
          statusMsg: `¡${renders.length} videos exportados!`,
        });
      }

      const tBatchTotalSec = ((performance.now() - tBatchStart) / 1000).toFixed(1);
      const mins = Math.floor(parseFloat(tBatchTotalSec) / 60);
      const secs = Math.floor(parseFloat(tBatchTotalSec) % 60);
      const fmt = mins > 0 ? `${tBatchTotalSec}s (${mins}m ${secs}s)` : `${tBatchTotalSec}s`;
      appendExportLog("=".repeat(50));
      appendExportLog(`🏁 RESUMEN LOTE COMPLETO: ${renders.length} videos exportados`);
      appendExportLog(`• Tiempo total del lote: ${fmt}`);
      appendExportLog(`• Promedio por video: ${(parseFloat(tBatchTotalSec) / Math.max(1, renders.length)).toFixed(1)}s`);
      appendExportLog("=".repeat(50));
    } catch (e) {
      if (progressInterval) {
        clearInterval(progressInterval);
      }
      setStatus("error");
      const err = e instanceof Error ? e.message : "Error desconocido";
      setErrorMsg(err);
      appendExportLog(`❌ Error en exportación por lotes: ${err}`);
    }
  }, [savedProjects, folderRefs, uploadToCatbox, setStatus, setErrorMsg, setCatboxUrl, setCatboxVideos, setProgressData, appendExportLog, clearExportLogs, openExportLogs, exportMode]);

  const isRunning = status === "uploading" || status === "rendering";

  // ── Render ───────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Server size={16} className="text-primary" />
          <span className="text-sm font-semibold text-text-primary">Colab FFmpeg Export</span>
        </div>

        {/* Selector de modo: Stream Copy vs Forzar Re-encode (o GPU T4 fijo si hay cortes) */}
        {isStreamCopyCandidate ? (
          <div className="inline-flex items-center p-0.5 rounded-lg bg-background-tertiary border border-border/60 text-[10px]">
            <button
              type="button"
              onClick={() => setExportMode("auto")}
              disabled={isRunning}
              className={`px-2 py-0.5 rounded-md transition-all font-medium flex items-center gap-1 ${
                exportMode === "auto"
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shadow-xs"
                  : "text-text-muted hover:text-text-primary"
              }`}
              title="Modo ultrarrápido: copia el video sin re-codificar y mezcla el audio. Cero pérdida de calidad."
            >
              <span>⚡ Stream Copy</span>
            </button>
            <button
              type="button"
              onClick={() => setExportMode("reencode")}
              disabled={isRunning}
              className={`px-2 py-0.5 rounded-md transition-all font-medium flex items-center gap-1 ${
                exportMode === "reencode"
                  ? "bg-amber-500/20 text-amber-300 border border-amber-500/30 shadow-xs"
                  : "text-text-muted hover:text-text-primary"
              }`}
              title="Fuerza la recodificación completa del video con GPU T4 NVENC (H.264 CQ 28)."
            >
              <span>🔥 Forzar Re-encode</span>
            </button>
          </div>
        ) : (
          <span
            className="text-[10px] px-2 py-0.5 rounded-full font-medium text-amber-400 bg-amber-500/10 border border-amber-500/20"
            title="El timeline contiene cortes o transiciones de video: requiere renderizado con GPU NVENC."
          >
            🔥 GPU T4 (NVENC H.264)
          </span>
        )}
      </div>

      {/* Catbox toggle */}
      <div className="flex items-center gap-3 p-3 bg-background-tertiary rounded-lg">
        <div className="flex items-center gap-2 flex-1">
          <LinkIcon size={14} className="text-primary" />
          <Label htmlFor="catbox-switch" className="text-xs text-text-secondary">
            Subir a Catbox (link compartible 24h)
          </Label>
        </div>
        <Switch
          id="catbox-switch"
          checked={uploadToCatbox}
          onCheckedChange={setUploadToCatbox}
          disabled={isRunning}
        />
      </div>

      {/* Mode toggle */}
      <div className="flex items-center gap-3 p-3 bg-background-tertiary rounded-lg">
        <Label htmlFor="batch-switch" className="text-xs text-text-secondary flex-1">
          Multi-export (varios proyectos → ZIP)
        </Label>
        <Switch
          id="batch-switch"
          checked={isBatch}
          onCheckedChange={setIsBatch}
          disabled={isRunning}
        />
      </div>

      {/* ── Single Mode ── */}
      {!isBatch && (
        <div className="space-y-3">
          {/* Título Viral del Video (TikTok / Shorts) */}
          <div className="p-3 bg-gradient-to-b from-primary/5 to-background-tertiary rounded-lg border border-primary/20 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Sparkles size={14} className="text-yellow-400" />
                <span className="text-xs font-semibold text-text-primary">Título Viral (TikTok / Shorts)</span>
              </div>
              <span className="text-[10px] text-text-muted">Nombre del MP4</span>
            </div>

            <div className="space-y-1.5">
              <Input
                value={customTitleInput}
                onChange={(e) => setCustomTitleInput(e.target.value)}
                placeholder="Título llamativo con emojis y hashtags..."
                className="text-xs bg-background-secondary border-border"
                disabled={isRunning || isRegeneratingTitle || isSavingTitle}
              />
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleRegenerateViralTitle()}
                  disabled={isRunning || isRegeneratingTitle || !jobContext}
                  className="flex-1 h-7 text-xs bg-primary/10 border-primary/30 text-primary hover:bg-primary/20 gap-1.5"
                >
                  {isRegeneratingTitle ? (
                    <>
                      <Loader2 size={12} className="animate-spin" />
                      Generando con Gemini…
                    </>
                  ) : (
                    <>
                      <Sparkles size={12} className="text-yellow-400" />
                      Regenerar con IA
                    </>
                  )}
                </Button>

                <Button
                  size="sm"
                  variant="ghost"
                  onClick={handleSaveManualTitle}
                  disabled={isRunning || isSavingTitle || !customTitleInput.trim()}
                  className="h-7 text-xs px-2.5 gap-1 text-text-muted hover:text-text-primary shrink-0"
                  title="Guardar nombre editado a mano"
                >
                  {isSavingTitle ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                  Guardar
                </Button>
              </div>
            </div>

            {titleFeedback && (
              <div
                className={`text-[10px] px-2 py-1 rounded flex items-center gap-1.5 ${
                  titleFeedback.type === "success"
                    ? "bg-green-500/10 text-green-300 border border-green-500/30"
                    : "bg-red-500/10 text-red-300 border border-red-500/30"
                }`}
              >
                {titleFeedback.type === "success" ? <CheckCircle size={12} /> : <AlertTriangle size={12} />}
                <span>{titleFeedback.msg}</span>
              </div>
            )}
          </div>

          <div className="p-3 bg-background-tertiary rounded-lg text-xs space-y-1">
            <div className="flex justify-between text-text-secondary">
              <span>Proyecto actual</span>
              <span className="font-medium text-text-primary truncate max-w-[200px]">{project.name}</span>
            </div>
            <div className="flex justify-between text-text-secondary">
              <span>Clips renderizables</span>
              <span className="font-medium text-green-400">{totalClips}</span>
            </div>
            {needUpload.length > 0 && (
              <div className="flex justify-between text-text-secondary">
                <span className="flex items-center gap-1">
                  <Upload size={10} /> Por subir primero
                </span>
                <span className="font-medium text-yellow-400">{needUpload.length}</span>
              </div>
            )}
          </div>

          {/* Warnings */}
          {notAllowed.length > 0 && (
            <div className="flex items-start gap-2 p-2 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
              <AlertTriangle size={14} className="text-yellow-400 mt-0.5 shrink-0" />
              <div className="text-[10px] text-yellow-300 space-y-0.5">
                <p className="font-medium">{notAllowed.length} clip(s) no se incluirán:</p>
                {notAllowed.slice(0, 3).map((c) => (
                  <p key={c.clipId} className="text-yellow-400/70 truncate max-w-[280px]">• {c.mediaName}</p>
                ))}
                {notAllowed.length > 3 && <p className="text-yellow-400/70">y {notAllowed.length - 3} más…</p>}
              </div>
            </div>
          )}

          {!jobContext && (
            <div className="flex items-center gap-2 p-2 bg-red-500/10 border border-red-500/30 rounded-lg">
              <AlertTriangle size={14} className="text-red-400" />
              <span className="text-[10px] text-red-300">
                No se encontró ningún job de Colab asociado a este proyecto. Importa un video V2V primero.
              </span>
            </div>
          )}
        </div>
      )}

      {/* ── Batch Mode ── */}
      {isBatch && (
        <BatchRenderQueue
          loadingSaved={loadingSaved}
          savedProjects={savedProjects}
          isRunning={isRunning}
          batchRegeneratingId={batchRegeneratingId}
          onToggleAll={toggleAll}
          onToggleProject={toggleProject}
          onBatchRegenerateTitle={handleBatchRegenerateViralTitle}
        />
      )}

      {/* Status con Barra de Progreso Mejorada */}
      <RenderProgressBar
        isRunning={isRunning}
        currentStep={currentStep}
        status={status}
        progress={progress}
        currentVideoName={currentVideoName}
        statusMsg={statusMsg}
        isBatch={isBatch}
        totalVideos={totalVideos}
        currentIdx={currentIdx}
      />
      {status === "done" && !catboxUrl && catboxVideos.length === 0 && (
        <div className="flex items-center gap-2 p-3 bg-green-500/10 border border-green-500/30 rounded-lg">
          <CheckCircle size={14} className="text-green-400" />
          <span className="text-xs text-green-300">{statusMsg}</span>
        </div>
      )}
      {status === "error" && (
        <div className="flex items-start gap-2 p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
          <AlertTriangle size={14} className="text-red-400 shrink-0 mt-0.5" />
          <span className="text-xs text-red-300">{errorMsg}</span>
        </div>
      )}

      {/* Catbox Results */}
      <CatboxUploadStatus
        catboxUrl={catboxUrl}
        catboxVideos={catboxVideos}
        isBatch={isBatch}
        onCopyUrl={copyToClipboard}
        copiedIndex={copiedIndex}
      />


      {/* Action button */}
      <div className="flex flex-col gap-1.5">
        <Button
          className="w-full"
          onClick={isBatch ? handleBatchExport : handleSingleExport}
          disabled={isRunning || totalClips === 0 || (!isBatch && !jobContext)}
        >
          {isRunning ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              {isBatch && totalVideos > 0
                ? `Exportando (${currentIdx || 1}/${totalVideos})…`
                : status === "uploading"
                  ? "Subiendo medios…"
                  : effectiveMode === "stream_copy"
                    ? "Empaquetando en Colab (Stream Copy)…"
                    : "Renderizando en Colab (GPU NVENC)…"}
            </>
          ) : isBatch ? (
            <>
              {uploadToCatbox ? <Upload size={16} /> : <Archive size={16} />}
              {uploadToCatbox ? "Subir todos a Catbox" : "Exportar como ZIP"}
            </>
          ) : (
            <>
              {uploadToCatbox ? <Upload size={16} /> : <Download size={16} />}
              {uploadToCatbox
                ? "Subir a Catbox"
                : effectiveMode === "stream_copy"
                  ? "Exportar MP4 (Stream Copy)"
                  : "Renderizar MP4 (GPU NVENC)"}
            </>
          )}
        </Button>

        {isRunning && (
          <button
            type="button"
            onClick={resetStatus}
            className="text-[10px] text-text-muted hover:text-red-400 text-center py-0.5 transition-colors underline cursor-pointer"
            title="Restablece el estado si la conexión se interrumpió"
          >
            ¿Proceso bloqueado? Cancelar / Reiniciar estado
          </button>
        )}
      </div>
    </div>
  );
};

export default ColabExportTab;
