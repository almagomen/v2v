import React, { useEffect, useCallback } from "react";
import { Youtube, Loader2, AlertCircle, RefreshCw, Download, Share2, FolderDown } from "lucide-react";
import { ScrollArea, Button } from "@openreel/ui";
import { toast } from "../../stores/notification-store";
import { v2vApi } from "../../lib/v2v-api";
import { useProjectStore } from "../../stores/project-store";
import { useV2VStore } from "../../stores/v2v-store";
import { autoSaveManager } from "../../services/auto-save";
import {
  toSafeToken,
  sanitizeFolderName,
  shortProjectToken,
  importKeyFor,
} from "../../utils/v2v-utils";

const TRANSLATE_OPTIONS = [
  { value: "None", label: "Sin traducción" },
  { value: "es", label: "Español" },
  { value: "pt", label: "Portugués" },
  { value: "en", label: "Inglés" },
  { value: "fr", label: "Francés" },
  { value: "de", label: "Alemán" },
  { value: "it", label: "Italiano" },
];

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const STATUS_LABEL: Record<string, string> = {
  pending: "En cola",
  downloading: "Descargando",
  cached: "Caché",
  transcribing: "Transcribiendo",
  tts: "TTS",
  audio_ready: "Audio listo",
  ready: "Listo (STT)",
  done: "Completado",
  error: "Error",
};

function statusToBadgeClass(status: string): string {
  switch (status) {
    case "done":
      return "bg-primary/15 text-primary border border-primary/30";
    case "audio_ready":
    case "tts":
    case "transcribing":
    case "downloading":
      return "bg-blue-500/10 text-blue-400 border border-blue-500/20";
    case "cached":
      return "bg-purple-500/10 text-purple-400 border border-purple-500/20";
    case "error":
      return "bg-red-500/10 text-red-400 border border-red-500/20";
    default:
      return "bg-background-tertiary text-text-muted border border-border";
  }
}

export const V2VPanel: React.FC<{ embedInDrawer?: boolean }> = ({
  embedInDrawer = false,
}) => {
  const {
    urls,
    setUrls,
    translateLang,
    setTranslateLang,
    speaker,
    setSpeaker,
    jobId,
    setJobId,
    log,
    setLog,
    error,
    setError,
    videos,
    setVideos,
    selectedVideoIndex,
    setSelectedVideoIndex,
    segments,
    setSegments,
    selectedRowIndex,
    setSelectedRowIndex,
    isProcessing,
    setIsProcessing,
    regenStatus,
    setRegenStatus,
    shareUrl,
    setShareUrl,
    importStatusByKey,
    urlItems,
    urlLogs,
    jobPhase,
    setJobPhase,
    speakers,
    fetchSpeakers,
    startPolling,
  } = useV2VStore();

  useEffect(() => {
    if (speakers.length === 0) {
      fetchSpeakers();
    }
  }, [speakers.length, fetchSpeakers]);

  // Si ya hay un jobId activo al montar, iniciamos polling por si acaso (recuperación tras refresh)
  useEffect(() => {
    if (jobId && isProcessing) {
      startPolling(jobId);
    }
  }, []);

  const handleProcess = useCallback(async () => {
    const urlList = urls
      .split("\n")
      .map((u) => u.trim())
      .filter(Boolean);
    const normalized = urlList
      .map((u: string) => (/^https?:\/\//i.test(u) ? u : `https://${u}`))
      .filter((u: string) => /^https?:\/\/(www\.)?(youtube\.com\/|youtu\.be\/)/i.test(u));
    if (normalized.length === 0) {
      setError("Introduce al menos una URL de YouTube");
      return;
    }
    const signature = normalized.map((u: string) => encodeURIComponent(u)).join("|");
    const prevSignature = useV2VStore.getState().lastUrlsSignature;
    const keepImports = Boolean(prevSignature && prevSignature === signature);

    useV2VStore.getState().clearJobRunState({ keepImports });
    useV2VStore.setState({ lastUrlsSignature: signature });
    setError(null);
    setLog("");
    setVideos([]);
    setIsProcessing(true);
    setJobPhase("downloading");
    try {
      const res = await v2vApi.processUrls(
        normalized,
        translateLang === "None" ? null : translateLang,
        speaker
      );
      setJobId(res.job_id);
      startPolling(res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al iniciar");
      setIsProcessing(false);
    }
  }, [urls, translateLang, speaker]);

  const handleVideoSelect = useCallback(
    (idx: number) => {
      setSelectedVideoIndex(idx);
      if (videos[idx]) setSegments(videos[idx].segments);
      setShareUrl(null);
    },
    [videos]
  );

  const handleSegmentEdit = useCallback(
    (
      rowIdx: number,
      field: "start" | "end" | "text",
      value: string | number
    ) => {
      setSegments((prev: any[]) =>
        prev.map((s: any, i: number) =>
          i === rowIdx
            ? { ...s, [field]: typeof value === "number" ? value : value }
            : s
        )
      );
    },
    []
  );

  const handleRegenerateSegment = useCallback(async () => {
    if (selectedRowIndex == null || !jobId || !segments[selectedRowIndex]) return;
    const seg = segments[selectedRowIndex];
    setRegenStatus("Regenerando...");
    try {
      await v2vApi.regenerateSegment(
        jobId,
        selectedVideoIndex,
        seg.seg,
        seg.text,
        seg.start,
        seg.end,
        translateLang === "None" ? null : translateLang,
        speaker
      );
      setRegenStatus("Segmento regenerado");
    } catch (e) {
      setRegenStatus(e instanceof Error ? e.message : "Error");
    }
  }, [jobId, selectedVideoIndex, selectedRowIndex, segments, translateLang, speaker]);

  const handleRegenerateVideo = useCallback(async () => {
    if (!jobId) return;
    setRegenStatus("Aplicando cambios y renderizando...");
    try {
      await v2vApi.regenerateVideo(
        jobId,
        selectedVideoIndex,
        segments,
        translateLang === "None" ? null : translateLang,
        speaker
      );
      const result = await v2vApi.getJobResult(jobId);
      setVideos(result.videos);
      if (result.videos[selectedVideoIndex]) {
        setSegments(result.videos[selectedVideoIndex].segments);
      }
      setRegenStatus("Video regenerado");
    } catch (e) {
      setRegenStatus(e instanceof Error ? e.message : "Error");
    }
  }, [jobId, selectedVideoIndex, segments, translateLang, speaker]);

  // Cargar en editor eliminado: ahora se importa automáticamente a Media durante el proceso.

  const handleShare = useCallback(async () => {
    if (!jobId) return;
    setRegenStatus("Subiendo a Catbox...");
    try {
      const u = await v2vApi.shareToCatbox(jobId, selectedVideoIndex);
      setShareUrl(u);
      setRegenStatus("Enlace listo");
    } catch (e) {
      setRegenStatus(e instanceof Error ? e.message : "Error al compartir");
    }
  }, [jobId, selectedVideoIndex]);

  const handleDownloadZip = useCallback(async () => {
    if (!jobId) return;
    setRegenStatus("Preparando ZIP...");
    try {
      const blob = await v2vApi.downloadZipBlob(jobId);
      downloadBlob(blob, "videos_inferidos.zip");
      setRegenStatus("ZIP descargado");
    } catch (e) {
      setRegenStatus(e instanceof Error ? e.message : "Error al descargar ZIP");
    }
  }, [jobId]);

  return (
    <ScrollArea className="h-full min-h-0 flex-1 w-full">
      <div className="p-4 space-y-4 min-w-0">
        {!embedInDrawer && (
          <div className="flex items-center gap-2">
            <Youtube size={20} className="text-red-500" />
            <h2 className="text-sm font-semibold text-text-primary">
              Video2Video – Traducción y doblaje
            </h2>
          </div>
        )}

        <div>
          <label className="text-[10px] text-text-muted block mb-1">
            URLs de YouTube (una por línea)
          </label>
          <textarea
            className="w-full h-24 px-3 py-2 text-xs bg-background-tertiary border border-border rounded-lg resize-none focus:outline-none focus:ring-1 focus:ring-primary whitespace-pre overflow-x-auto"
            placeholder="https://www.youtube.com/watch?v=..."
            value={urls}
            onChange={(e) => setUrls(e.target.value)}
            disabled={isProcessing}
          />
        </div>

        <div className="flex gap-2">
          <div className="flex-1">
            <label className="text-[10px] text-text-muted block mb-1">Idioma</label>
            <select
              className="w-full px-3 py-2 text-xs bg-background-tertiary border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
              value={translateLang}
              onChange={(e) => setTranslateLang(e.target.value)}
              disabled={isProcessing}
            >
              {TRANSLATE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex-1">
            <label className="text-[10px] text-text-muted block mb-1">Voz</label>
            <select
              className="w-full px-3 py-2 text-xs bg-background-tertiary border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
              value={speaker}
              onChange={(e) => setSpeaker(e.target.value)}
              disabled={isProcessing}
            >
              {speakers.length > 0 ? (
                speakers.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))
              ) : (
                <>
                  <option value="mrbeast_lmnt">mrbeast_lmnt</option>
                  <option value="Dionisio Schuyler">Dionisio Schuyler</option>
                </>
              )}
            </select>
          </div>
        </div>

        <Button
          onClick={handleProcess}
          disabled={isProcessing || Object.values(importStatusByKey).some((s) => s === "in_progress")}
          className="w-full"
        >
          {(() => {
            const hasImportsInFlight = Object.values(importStatusByKey).some(
              (s) => s === "in_progress",
            );

            const order: Record<string, number> = {
              downloading: 1,
              cached: 2,
              transcribing: 3,
              tts: 4,
              audio_ready: 5,
              ready: 6,
              done: 100,
              error: 101,
              pending: 1000,
            };

            // Si hay varias URLs, mostramos el "estado más activo" (menor prioridad)
            // entre las que no estén done/error/pending.
            const activeCandidates = urlItems
              .filter((it: any) => it.status && it.status !== "done" && it.status !== "error" && it.status !== "pending");

            const importingCandidates = hasImportsInFlight
              ? urlItems.filter(
                  (it: any) =>
                    typeof it.index === "number" &&
                    importStatusByKey[importKeyFor(it.url, it.index)] === "in_progress",
                )
              : [];

            const activeUrlState =
              importingCandidates.length > 0
                ? importingCandidates[0]
                : activeCandidates.length > 0
                  ? activeCandidates.sort(
                      (a: any, b: any) => (order[a.status] ?? 999) - (order[b.status] ?? 999),
                    )[0]
                  : null;

            const activeStatus = activeUrlState?.status || jobPhase;
            const tagText =
              hasImportsInFlight
                ? "Importando a Media"
                : activeStatus && activeStatus !== "idle"
                  ? STATUS_LABEL[activeStatus] || activeStatus
                  : "Empezar";

            const activePos = activeUrlState
              ? urlItems.findIndex(
                  (it: any) => it.url === activeUrlState.url && it.index === activeUrlState.index,
                )
              : -1;
            const x = urlItems.length || 1;
            const prefix = activePos >= 0 ? `[${activePos + 1}/${x}] ` : "";
            const tag = `${prefix}${tagText}`;

            const showSpin = isProcessing || hasImportsInFlight;
            return (
              <>
                {showSpin && <Loader2 size={14} className="animate-spin mr-2" />}
                {tag}
              </>
            );
          })()}
        </Button>

        {error && (
          <div className="flex items-center gap-2 p-2 rounded-lg bg-red-500/10 text-red-500 text-xs">
            <AlertCircle size={14} />
            {error}
          </div>
        )}

        {urlItems.length > 0 && (
          <div className="space-y-1">
            <p className="text-[10px] text-text-muted">Estado por URL</p>
            <div className="max-h-32 overflow-y-auto border border-border rounded-lg">
              <table className="w-full text-[10px]">
                <thead className="bg-background-tertiary sticky top-0">
                  <tr>
                    <th className="px-2 py-1 text-left">#</th>
                    <th className="px-2 py-1 text-left">Título</th>
                    <th className="px-2 py-1 text-left">tag/state</th>
                  </tr>
                </thead>
                <tbody>
                  {urlItems.map((it: any, i: number) => (
                    <tr key={it.url} className="border-t border-border">
                      <td className="px-2 py-1 tabular-nums">{i + 1}</td>
                      <td className="px-2 py-1 max-w-[220px] truncate" title={it.url}>
                        {it.output_name || it.url}
                        {typeof it.index === "number" &&
                          importStatusByKey[importKeyFor(it.url, it.index)] === "done" && (
                            <span className="ml-1 text-primary">(importado)</span>
                          )}
                      </td>
                      <td className="px-2 py-1">
                        <span
                          className={`inline-flex items-center px-1.5 py-0.5 rounded ${statusToBadgeClass(it.status)}`}
                        >
                          {STATUS_LABEL[it.status] || it.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {log && (
          <div className="space-y-1">
            <p className="text-[10px] text-text-muted">Logs</p>
            <pre className="p-2 rounded-lg bg-background-tertiary font-mono text-[10px] max-h-32 overflow-y-auto overflow-x-auto whitespace-pre">
              {(() => {
                let out = log || "";

                // Antes de la primera tanda de segmentos TTS.
                // (Sin tokens [STATE:...] en pantalla)
                out = out.replace(/^(\s*)0\. Fast:/gm, "$1⚡ TTS:\n$10. Fast:");

                // Import-only: mostramos lo que se registra en `urlLogs` (sin [STATE:...]).
                const importText = urlItems
                  .map((it: any) => (it.url ? urlLogs[it.url] || "" : ""))
                  .filter(Boolean)
                  .join("\n");

                return `${out}${importText ? `\n${importText}` : ""}`;
              })()}
            </pre>
          </div>
        )}

        {videos.length > 0 && (
          <>
            <div>
              <label className="text-[10px] text-text-muted block mb-1">Video procesado</label>
              <div className="flex gap-2">
                <select
                  className="flex-1 min-w-0 truncate px-3 py-2 text-xs bg-background-tertiary border border-border rounded-lg"
                  value={selectedVideoIndex}
                  onChange={(e) => handleVideoSelect(parseInt(e.target.value, 10))}
                >
                  {videos.map((v: any, i: number) => (
                    <option key={i} value={i}>
                      {v.output_name}
                    </option>
                  ))}
                </select>
                <Button
                  size="icon"
                  variant="secondary"
                  title="Re-importar carpeta a Media"
                  onClick={async () => {
                    if (!jobId || selectedVideoIndex < 0 || !videos[selectedVideoIndex]) return;
                    const v = videos[selectedVideoIndex];
                    const folder = sanitizeFolderName(v.output_name || `video_${v.index}`);
                    
                    const currentItems = useV2VStore.getState().urlItems;
                    const pos = currentItems.findIndex(
                      (it) => it.url === v.url && it.index === v.index,
                    );
                    const seq = pos >= 0 ? pos + 1 : v.index + 1;
                    const projectTitle = `${seq}. TTS ${shortProjectToken(v.output_name || folder)}`;
                    
                    setIsProcessing(true);
                    try {
                      const projectStore = useProjectStore.getState();
                      let targetProjectLoaded = false;
                      
                      if (projectStore.project.name === projectTitle) {
                        targetProjectLoaded = true;
                      } else {
                        await autoSaveManager.initialize();
                        const saves = await autoSaveManager.checkForRecovery();
                        const uniqueProjects = saves.reduce((acc: any[], save: any) => {
                          const existing = acc.find((s: any) => s.projectId === save.projectId);
                          if (!existing || save.timestamp > existing.timestamp) {
                            return [...acc.filter((s: any) => s.projectId !== save.projectId), save];
                          }
                          return acc;
                        }, [] as any[]);
                        
                        const targetSave = uniqueProjects.find((s: any) => s.projectName === projectTitle);
                        if (targetSave) {
                          await projectStore.recoverFromAutoSave(targetSave.id);
                          targetProjectLoaded = true;
                        } else {
                          const baseProjectSettings = projectStore.project.settings;
                          projectStore.createNewProject(projectTitle, {
                            width: baseProjectSettings.width,
                            height: baseProjectSettings.height,
                            frameRate: baseProjectSettings.frameRate,
                          });
                          targetProjectLoaded = true;
                        }
                      }
                      
                      if (!targetProjectLoaded) {
                        toast.error("Error", "No se pudo cargar el proyecto destino.");
                        return;
                      }

                      // Obtenemos el store fresco tras el posible cambio de proyecto
                      let freshStore = useProjectStore.getState();
                      
                      // 1) Video
                      const videoMediaName = `${folder}/video.mp4`;
                      const videoExists = freshStore.project.mediaLibrary.items.some((m: any) => m.name === videoMediaName);
                      
                      if (!videoExists) {
                        const vblob = await v2vApi.fetchOutputVideoBlob(jobId!, v.index);
                        const vfile = new File([vblob], videoMediaName, { type: "video/mp4" });
                        await freshStore.importMedia(vfile);
                        // Refresh store reference after import
                        freshStore = useProjectStore.getState();
                      }
                      
                      // 2) Audios por segmento
                      const audioSegs = v.segments.filter((s: any) => s.text?.trim().length > 0);
                      for (const seg of audioSegs) {
                        const speakerToken = toSafeToken(seg.speaker || "speaker");
                        const wavName = `${folder}/tts_${speakerToken}_${String(seg.seg).padStart(4, "0")}.wav`;
                        
                        // Solo importamos si no existe ya
                        if (!freshStore.project.mediaLibrary.items.some((m: any) => m.name === wavName)) {
                          const wavBlob = await v2vApi.fetchAudioSegmentBlob(jobId!, v.index, seg.seg);
                          const wavFile = new File([wavBlob], wavName, { type: "audio/wav" });
                          await freshStore.importMedia(wavFile);
                          // Refresh store reference after each import to see new items
                          freshStore = useProjectStore.getState();
                        }
                      }
                      
                      await freshStore.forceSave();
                      
                      // 3) Vincular carpeta al Job para que AssetsPanel la reconozca
                      useV2VStore.getState().setFolderRef(folder, { jobId: jobId!, videoIndex: v.index });

                      toast.success("Re-importación completa", `Archivos en proyecto "${projectTitle}".`);
                    } catch (e) {
                      toast.error("Error al re-importar", String(e));
                    } finally {
                      setIsProcessing(false);
                    }
                  }}
                  disabled={!jobId || isProcessing}
                >
                  {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <FolderDown size={14} />}
                </Button>
                <Button size="icon" variant="secondary" onClick={handleShare} title="Compartir" disabled={!jobId || isProcessing}>
                  <Share2 size={14} />
                </Button>
              </div>
            </div>

            <div className="flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                className="flex-1"
                onClick={handleDownloadZip}
                disabled={!jobId || isProcessing}
              >
                <Download size={12} className="mr-1" />
                Descargar ZIP
              </Button>
            </div>

            {shareUrl && (
              <div className="p-2 rounded bg-background-tertiary">
                <p className="text-[10px] text-text-muted mb-1">Enlace Catbox:</p>
                <a
                  href={shareUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-primary break-all"
                >
                  {shareUrl}
                </a>
              </div>
            )}

            <div>
              <p className="text-[10px] text-text-muted mb-2">Segmentos (edita y regenera)</p>
              <div className="max-h-48 overflow-y-auto border border-border rounded-lg">
                <table className="w-full text-[10px]">
                  <thead className="bg-background-tertiary sticky top-0">
                    <tr>
                      <th className="px-2 py-1 text-left">#</th>
                      <th className="px-2 py-1 text-left">Inicio</th>
                      <th className="px-2 py-1 text-left">Final</th>
                      <th className="px-2 py-1 text-left">Texto</th>
                    </tr>
                  </thead>
                  <tbody>
                    {segments.map((seg: any, i: number) => (
                      <tr
                        key={i}
                        onClick={() => setSelectedRowIndex(i)}
                        className={`cursor-pointer border-t border-border hover:bg-background-tertiary ${
                          selectedRowIndex === i ? "bg-primary/10" : ""
                        }`}
                      >
                        <td className="px-2 py-1">{seg.seg}</td>
                        <td className="px-2 py-1">
                          <input
                            type="number"
                            step="0.01"
                            value={seg.start}
                            onChange={(e) =>
                              handleSegmentEdit(i, "start", parseFloat(e.target.value) || 0)
                            }
                            className="w-14 bg-transparent border-none p-0 text-inherit"
                            onClick={(e) => e.stopPropagation()}
                          />
                        </td>
                        <td className="px-2 py-1">
                          <input
                            type="number"
                            step="0.01"
                            value={seg.end}
                            onChange={(e) =>
                              handleSegmentEdit(i, "end", parseFloat(e.target.value) || 0)
                            }
                            className="w-14 bg-transparent border-none p-0 text-inherit"
                            onClick={(e) => e.stopPropagation()}
                          />
                        </td>
                        <td className="px-2 py-1 max-w-[120px] truncate">
                          <input
                            type="text"
                            value={seg.text}
                            onChange={(e) => handleSegmentEdit(i, "text", e.target.value)}
                            className="w-full bg-transparent border-none p-0 text-inherit truncate"
                            onClick={(e) => e.stopPropagation()}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={handleRegenerateSegment}
                disabled={selectedRowIndex == null}
              >
                <RefreshCw size={12} className="mr-1" />
                Regenerar segmento
              </Button>
              <Button size="sm" onClick={handleRegenerateVideo}>
                Aplicar cambios y renderizar
              </Button>
            </div>

            {regenStatus && (
              <p
                className={`text-[10px] ${
                  regenStatus.toLowerCase().includes("error") ? "text-red-500" : "text-text-muted"
                }`}
              >
                {regenStatus}
              </p>
            )}
          </>
        )}
      </div>
    </ScrollArea>
  );
};

