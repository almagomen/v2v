import React, { useCallback, useEffect, useState } from "react";
import {
  Server,
  Download,
  Archive,
  CheckSquare,
  Square,
  Loader2,
  AlertTriangle,
  CheckCircle,
  Upload,
  Link as LinkIcon,
  Copy,
  ExternalLink,
} from "lucide-react";
import { Button, Switch, Label } from "@openreel/ui";
import {
  v2vApi,
  type TimelineClipPayload,
  type BatchRenderItemPayload,
} from "../../lib/v2v-api";
import { useProjectStore } from "../../stores/project-store";
import { useV2VStore } from "../../stores/v2v-store";
import { autoSaveManager } from "../../services/auto-save";
import type { AutoSaveMetadata } from "../../services/auto-save";
import type { Project, MediaItem } from "@openreel/core";

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

interface CatboxVideoResult {
  filename: string;
  url: string;
  status: string;
}

// ----------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------

/** Determine if a media_name belongs to a V2V folder (already in Colab). */
function isInV2VFolder(
  mediaName: string,
  folderRefs: Record<string, any>,
): boolean {
  let folder = "";
  let filename = "";

  const norm = mediaName.replace(/\\/g, "/");

  if (norm.includes("__")) {
    const parts = norm.split("__");
    folder = parts[0];
    filename = parts[parts.length - 1];
  } else if (norm.includes("/")) {
    const parts = norm.split("/");
    folder = parts[0];
    filename = parts[parts.length - 1];
  }

  if (!folder || !(folder in folderRefs)) return false;

  const ref = folderRefs[folder];
  
  if (ref.nativeFiles && Array.isArray(ref.nativeFiles)) {
    return ref.nativeFiles.includes(filename);
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
        volume: 1.0,
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

  const [isBatch, setIsBatch] = useState(false);
  const [uploadToCatbox, setUploadToCatbox] = useState(false);
  const [savedProjects, setSavedProjects] = useState<SavedProject[]>([]);
  const [loadingSaved, setLoadingSaved] = useState(false);

  const [status, setStatus] = useState<"idle" | "uploading" | "rendering" | "done" | "error">("idle");
  const [statusMsg, setStatusMsg] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  // Catbox results
  const [catboxUrl, setCatboxUrl] = useState<string | null>(null);
  const [catboxVideos, setCatboxVideos] = useState<CatboxVideoResult[]>([]);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  // ── Analyze current project ──────────────────────────────────
  const analyzed = React.useMemo(
    () => analyzeProject(project, folderRefs),
    [project, folderRefs],
  );

  const notAllowed = analyzed.filter((c) => c.status === "not_allowed");
  const needUpload = analyzed.filter((c) => c.status === "upload_needed");
  const totalClips = analyzed.filter((c) => c.status !== "not_allowed").length;

  // Get job/video context and a descriptive name from folderRefs matching media names
  const jobContext = React.useMemo(() => {
    for (const clip of analyzed) {
      if (clip.status !== "not_allowed") {
        const norm = clip.mediaName.replace(/\\/g, "/");
        let folder = "";
        if (norm.includes("__")) {
          folder = norm.split("__")[0];
        } else if (norm.includes("/")) {
          folder = norm.split("/")[0];
        }
        
        const ref = (folderRefs as Record<string, { jobId: string; videoIndex: number; outputName?: string }>)[folder];
        if (ref) return { ...ref, longName: ref.outputName || folder };
      }
    }
    return null;
  }, [analyzed, folderRefs]);

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

      setSavedProjects(
        Array.from(uniqueProjects.values()).map((meta) => ({ meta, selected: true })),
      );
      setLoadingSaved(false);
    });
  }, [isBatch]);

  const toggleProject = (id: string) => {
    setSavedProjects((prev) =>
      prev.map((p) =>
        p.meta.id === id ? { ...p, selected: !p.selected } : p,
      ),
    );
  };

  const toggleAll = () => {
    const allSelected = savedProjects.every((p) => p.selected);
    setSavedProjects((prev) => prev.map((p) => ({ ...p, selected: !allSelected })));
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

  // ── Single export ────────────────────────────────────────────
  const handleSingleExport = useCallback(async () => {
    if (!jobContext) {
      setErrorMsg("No se pudo determinar el job de Colab. Asegúrate de que el proyecto tiene medios V2V.");
      setStatus("error");
      return;
    }

    setStatus("uploading");
    setErrorMsg("");
    setCatboxUrl(null);
    setCatboxVideos([]);

    try {
      const uploadedMap = await uploadPendingClips(
        analyzed,
        jobContext.jobId,
        jobContext.videoIndex,
        (msg) => setStatusMsg(msg),
      );

      setStatus("rendering");
      setStatusMsg(uploadToCatbox ? "Renderizando y subiendo a Catbox…" : "Renderizando en Colab…");

      const clips = buildPayloadClips(analyzed, uploadedMap);
      // Usar el título completo de TikTok (con hashtags) en lugar del nombre simplificado del proyecto
      const rawName = jobContext.longName || project.name || "export";
      const outName = rawName.replace(/^\d+[._\s]*/, "");
      
      const result = await v2vApi.renderTimeline({
        job_id: jobContext.jobId,
        video_index: jobContext.videoIndex,
        clips,
        output_name: outName,
        upload_to_catbox: uploadToCatbox,
      });

      // Check if result is Catbox upload response
      if (uploadToCatbox && result && typeof result === "object" && "url" in result) {
        const catboxResult = result as { url: string; filename: string };
        setCatboxUrl(catboxResult.url);
        setStatus("done");
        setStatusMsg("¡Video subido a Catbox!");
      } else {
        // Normal download — usar el título completo TikTok para el nombre del archivo
        downloadBlob(result as Blob, `${outName}.mp4`);
        setStatus("done");
        setStatusMsg("¡Exportación completada!");
      }
    } catch (e) {
      setStatus("error");
      setErrorMsg(e instanceof Error ? e.message : "Error desconocido");
    }
  }, [analyzed, jobContext, project.name, uploadToCatbox]);

  // ── Batch export ─────────────────────────────────────────────
  const handleBatchExport = useCallback(async () => {
    const selected = savedProjects.filter((p) => p.selected);
    if (selected.length === 0) {
      setErrorMsg("Selecciona al menos un proyecto.");
      setStatus("error");
      return;
    }

    setStatus("uploading");
    setErrorMsg("");
    setCatboxUrl(null);
    setCatboxVideos([]);

    try {
      const renders: BatchRenderItemPayload[] = [];

      for (const sp of selected) {
        setStatusMsg(`Preparando: ${sp.meta.projectName}…`);
        const fullProject = await autoSaveManager.recover(sp.meta.id);
        if (!fullProject) continue;

        const clips = analyzeProject(fullProject, folderRefs);
        const ctx = clips.reduce<{ jobId: string; videoIndex: number } | null>((acc, c) => {
          if (acc) return acc;
          if (c.status !== "not_allowed") {
            const folder = c.mediaName.replace(/\\/g, "/").split("/")[0];
            const ref = (folderRefs as Record<string, { jobId: string; videoIndex: number; outputName?: string }>)[folder];
            if (ref) return { ...ref, longName: ref.outputName || folder };
            return null;
          }
          return null;
        }, null);

        if (!ctx) continue;

        const uploadedMap = await uploadPendingClips(
          clips,
          ctx.jobId,
          ctx.videoIndex,
          (msg) => setStatusMsg(msg),
        );

        renders.push({
          job_id: ctx.jobId,
          video_index: ctx.videoIndex,
          clips: buildPayloadClips(clips, uploadedMap),
          // Usar el título completo de TikTok (con hashtags) en lugar del nombre simplificado
          output_name: ((ctx as any).longName || fullProject.name || sp.meta.projectName || "export").replace(/^\d+[._\s]*/, ""),
        });
      }

      if (renders.length === 0) {
        throw new Error("Ningún proyecto tiene medios de Colab disponibles.");
      }

      setStatus("rendering");
      setStatusMsg(uploadToCatbox
        ? `Renderizando y subiendo ${renders.length} videos a Catbox…`
        : `Renderizando ${renders.length} proyectos en Colab…`
      );

      const result = await v2vApi.renderBatch({
        renders,
        zip_name: "batch_export",
        upload_to_catbox: uploadToCatbox,
      });

      // Check if result is Catbox upload response
      if (uploadToCatbox && result && typeof result === "object" && "videos" in result) {
        const batchResult = result as { videos: CatboxVideoResult[] };
        setCatboxVideos(batchResult.videos);
        setStatus("done");
        setStatusMsg(`¡${batchResult.videos.length} video(s) subido(s) a Catbox!`);
      } else {
        // Normal download
        downloadBlob(result as Blob, "batch_export.zip");
        setStatus("done");
        setStatusMsg(`¡${renders.length} videos exportados!`);
      }
    } catch (e) {
      setStatus("error");
      setErrorMsg(e instanceof Error ? e.message : "Error desconocido");
    }
  }, [savedProjects, folderRefs, uploadToCatbox]);

  const isRunning = status === "uploading" || status === "rendering";

  // ── Render ───────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Server size={16} className="text-primary" />
        <span className="text-sm font-semibold text-text-primary">Colab FFmpeg Export</span>
        <span className="ml-auto text-[10px] text-text-muted bg-background-tertiary px-2 py-0.5 rounded-full">
          GPU T4 · sin re-encode
        </span>
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
          onCheckedChange={(checked) => {
            setUploadToCatbox(checked);
    setCatboxUrl(null);
    setCatboxVideos([]);
          }}
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
          <div className="p-3 bg-background-tertiary rounded-lg text-xs space-y-1">
            <div className="flex justify-between text-text-secondary">
              <span>Proyecto actual</span>
              <span className="font-medium text-text-primary">{project.name}</span>
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
        <div className="space-y-2">
          {loadingSaved ? (
            <div className="flex items-center gap-2 text-xs text-text-muted p-3">
              <Loader2 size={14} className="animate-spin" />
              Cargando proyectos guardados…
            </div>
          ) : savedProjects.length === 0 ? (
            <div className="text-xs text-text-muted p-3 text-center">No hay proyectos guardados.</div>
          ) : (
            <>
              <button
                onClick={toggleAll}
                className="text-[10px] text-primary hover:underline px-1"
                disabled={isRunning}
              >
                {savedProjects.every((p) => p.selected) ? "Deseleccionar todo" : "Seleccionar todo"}
              </button>
              <div className="max-h-48 overflow-y-auto space-y-1 border border-border rounded-lg p-2">
                {savedProjects.map((sp) => (
                  <button
                    key={sp.meta.id}
                    onClick={() => toggleProject(sp.meta.id)}
                    disabled={isRunning}
                    className="w-full flex items-center gap-2 px-2 py-1.5 rounded hover:bg-background-tertiary text-left"
                  >
                    {sp.selected ? (
                      <CheckSquare size={14} className="text-primary shrink-0" />
                    ) : (
                      <Square size={14} className="text-text-muted shrink-0" />
                    )}
                    <span className="text-xs text-text-primary truncate">{sp.meta.projectName}</span>
                    <span className="ml-auto text-[10px] text-text-muted shrink-0">
                      {new Date(sp.meta.timestamp).toLocaleDateString()}
                    </span>
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-text-muted px-1">
                {savedProjects.filter((p) => p.selected).length} de {savedProjects.length} seleccionados
              </p>
            </>
          )}
        </div>
      )}

      {/* Status */}
      {isRunning && (
        <div className="flex items-center gap-2 p-3 bg-primary/10 border border-primary/30 rounded-lg">
          <Loader2 size={14} className="animate-spin text-primary" />
          <span className="text-xs text-primary">{statusMsg}</span>
        </div>
      )}
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

      {/* Catbox Results - Single */}
      {!isBatch && catboxUrl && status === "done" && (
        <div className="space-y-2 p-3 bg-green-500/10 border border-green-500/30 rounded-lg">
          <div className="flex items-center gap-2">
            <CheckCircle size={14} className="text-green-400" />
            <span className="text-xs text-green-300 font-medium">Video subido a Catbox</span>
            <span className="text-[10px] text-text-muted ml-auto">Expira en 24h</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex-1 flex items-center gap-2 px-2 py-1.5 bg-background-secondary rounded border border-border">
              <LinkIcon size={12} className="text-text-muted shrink-0" />
              <span className="text-[10px] text-text-primary truncate flex-1">{catboxUrl}</span>
            </div>
            <button
              onClick={() => copyToClipboard(catboxUrl!)}
              className="p-1.5 bg-background-secondary border border-border rounded hover:bg-background-tertiary transition-colors"
              title="Copiar enlace"
            >
              {copiedIndex !== null ? <CheckCircle size={12} className="text-green-400" /> : <Copy size={12} className="text-text-muted" />}
            </button>
            <a
              href={catboxUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="p-1.5 bg-background-secondary border border-border rounded hover:bg-background-tertiary transition-colors"
              title="Abrir enlace"
            >
              <ExternalLink size={12} className="text-text-muted" />
            </a>
          </div>
        </div>
      )}

      {/* Catbox Results - Batch */}
      {isBatch && catboxVideos.length > 0 && status === "done" && (
        <div className="space-y-2 p-3 bg-green-500/10 border border-green-500/30 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle size={14} className="text-green-400" />
            <span className="text-xs text-green-300 font-medium">{catboxVideos.length} video(s) subido(s) a Catbox</span>
            <span className="text-[10px] text-text-muted ml-auto">Expira en 24h</span>
          </div>
          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {catboxVideos.map((v, i) => (
              <div key={i} className="flex items-center gap-2">
                <div className="flex-1 min-w-0">
                  <p className="text-[10px] text-text-secondary truncate">{v.filename}</p>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <LinkIcon size={10} className="text-text-muted shrink-0" />
                    <span className="text-[10px] text-text-primary truncate">{v.url}</span>
                  </div>
                </div>
                <button
                  onClick={() => copyToClipboard(v.url, i)}
                  className="p-1.5 bg-background-secondary border border-border rounded hover:bg-background-tertiary transition-colors shrink-0"
                  title="Copiar enlace"
                >
                  {copiedIndex === i ? <CheckCircle size={12} className="text-green-400" /> : <Copy size={12} className="text-text-muted" />}
                </button>
                <a
                  href={v.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="p-1.5 bg-background-secondary border border-border rounded hover:bg-background-tertiary transition-colors shrink-0"
                  title="Abrir enlace"
                >
                  <ExternalLink size={12} className="text-text-muted" />
                </a>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action button */}
      <Button
        className="w-full"
        onClick={isBatch ? handleBatchExport : handleSingleExport}
        disabled={isRunning || totalClips === 0 || (!isBatch && !jobContext)}
      >
        {isRunning ? (
          <>
            <Loader2 size={16} className="animate-spin" />
            {status === "uploading" ? "Subiendo…" : "Renderizando…"}
          </>
        ) : isBatch ? (
          <>
            {uploadToCatbox ? <Upload size={16} /> : <Archive size={16} />}
            {uploadToCatbox ? "Subir todos a Catbox" : "Exportar como ZIP"}
          </>
        ) : (
          <>
            {uploadToCatbox ? <Upload size={16} /> : <Download size={16} />}
            {uploadToCatbox ? "Subir a Catbox" : "Exportar MP4 en Colab"}
          </>
        )}
      </Button>
    </div>
  );
};

export default ColabExportTab;
