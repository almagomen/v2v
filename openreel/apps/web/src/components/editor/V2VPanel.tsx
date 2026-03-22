import React, { useState, useEffect, useCallback, useRef } from "react";
import { Loader2, AlertCircle, RefreshCw, Download, Share2, FolderDown } from "lucide-react";
import { ScrollArea, Button } from "@openreel/ui";
import { toast } from "../../stores/notification-store";
import { v2vApi, type AudioSegmentItem } from "../../lib/v2v-api";
import { useProjectStore } from "../../stores/project-store";
import { useV2VStore } from "../../stores/v2v-store";
import { autoSaveManager } from "../../services/auto-save";

const TRANSLATE_OPTIONS = [
  { value: "None", label: "Sin traducción" },
  { value: "es", label: "Español" },
  { value: "pt", label: "Portugués" },
  { value: "en", label: "Inglés" },
  { value: "fr", label: "Francés" },
  { value: "de", label: "Alemán" },
  { value: "it", label: "Italiano" },
];

const POLL_INTERVAL = 1500;

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

function toSafeToken(s: string): string {
  const ascii = s
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .replace(/^[\_\.\-\\]+|[\_\.\-\\]+$/g, "")
    .slice(0, 40);
  return ascii || "speaker";
}

function importKeyFor(url: string, index: number): string {
  return `${encodeURIComponent(url)}|${index}`;
}

function sanitizeFolderName(name: string): string {
  // El folder se infiere por `Carpeta/archivo`, así que evitamos `/`.
  const cleaned = (name || "Video").replaceAll("/", "_").replaceAll("\\", "_").trim();
  return cleaned || "Video";
}

function shortProjectToken(name: string): string {
  const s = (name || "video")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9._ -]+/g, " ")
    .trim();
  const firstWords = s.split(/\s+/).filter(Boolean).slice(0, 2).join(" ");
  const compact = firstWords.replace(/\s+/g, "_").slice(0, 16);
  return compact || "video";
}

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

export const V2VPanel: React.FC = () => {
  // Lock para evitar ejecuciones concurrentes del bloque de auto-import/creación de proyectos.
  const importingRef = useRef(false);

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
    setProgress,
    progress,
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
    setImportStatus,
    urlItems,
    setUrlItems,
    urlLogs,
    appendUrlLog,
    jobPhase,
    setJobPhase,
  } = useV2VStore();

  const [speakers, setSpeakers] = useState<{ label: string; value: string }[]>(
    []
  );

  useEffect(() => {
    v2vApi.getSpeakers().then(setSpeakers);
  }, []);



  useEffect(() => {
    if (!jobId || !isProcessing) return;
    const t = setInterval(async () => {
      try {
        const s = await v2vApi.getJobStatus(jobId);
        setProgress(s.progress * 100);
        setJobPhase(s.status);

        // Log en tiempo real (sin esperar a done/error)
        const jobLog = await v2vApi.getJobLog(jobId);
        if (jobLog && jobLog.length > log.length) setLog(jobLog);

        const items = await v2vApi.getJobItems(jobId);
        if (items.length) setUrlItems(items);

        // Mientras procesa, intentamos leer resultado parcial (videos ya listos)
        try {
          const partial = await v2vApi.getJobResult(jobId);
          if (partial.videos?.length) {
            setVideos(partial.videos);
            if (partial.videos[selectedVideoIndex]) setSegments(partial.videos[selectedVideoIndex].segments);
          }
        } catch {
          // ignore (puede fallar si aún no hay videos)
        }

        // Auto-import incremental: por cada video aparecido en `videos`, importar video+audios a Media.
        // Usamos importingRef como lock para evitar que ticks concurrentes procesen imports en paralelo.
        if (!importingRef.current) {
          const currentVideos = useV2VStore.getState().videos;
          const pendingVideos = currentVideos.filter(
            (v) => !useV2VStore.getState().importStatusByKey[importKeyFor(v.url, v.index)],
          );
          if (pendingVideos.length > 0) {
            importingRef.current = true;
          try {
        const baseProjectSettings = useProjectStore.getState().project.settings;
        for (const v of pendingVideos) {
          const key = importKeyFor(v.url, v.index);
          // Re-check por si otro tick lo marcó mientras esperábamos
          if (useV2VStore.getState().importStatusByKey[key]) continue;
          // Marcamos INMEDIATO como in_progress para evitar duplicación
          setImportStatus(key, "in_progress");

          // Sólo importamos cuando el backend ya tiene WAVs en Seqs_trg (si no, esperamos al siguiente tick)
          let audioSegs: AudioSegmentItem[] = [];
          try {
            audioSegs = await v2vApi.getAudioSegments(jobId, v.index);
          } catch {
            setImportStatus(key, "error");
            continue;
          }
          if (!audioSegs.length) {
            // Audios aún no listos; re-poner como pendiente y esperar al siguiente tick
            useV2VStore.setState((st) => {
              const next = { ...st.importStatusByKey };
              delete next[key];
              return { importStatusByKey: next };
            });
            continue;
          }

          const folder = sanitizeFolderName(v.output_name || `video_${v.index}`);
          const urlForLog = v.url || "";
          const currentItems = useV2VStore.getState().urlItems;
          const pos = currentItems.findIndex(
            (it) => it.url === v.url && it.index === v.index,
          );
          const seq = pos >= 0 ? pos + 1 : v.index + 1;
          const projectTitle = `${seq}. TTS ${shortProjectToken(v.output_name || folder)}`;

          // Buscamos si el proyecto ya existe en IndexedDB
          await autoSaveManager.initialize();
          const saves = await autoSaveManager.checkForRecovery();
          const targetSave = saves.find(s => s.projectName === projectTitle);
          let targetId = targetSave?.projectId || targetSave?.id;

          if (!targetId) {
            // Un proyecto nuevo por cada video (SILENCIOSO)
            targetId = await useProjectStore.getState().createProjectSilent(projectTitle, {
              width: baseProjectSettings.width,
              height: baseProjectSettings.height,
              frameRate: baseProjectSettings.frameRate,
            });
          }

          const isTargetActive = useProjectStore.getState().project.id === targetId || useProjectStore.getState().project.name === projectTitle;
          
          setRegenStatus(`Importando a Media (${projectTitle}): ${folder}...`);
          if (urlForLog) appendUrlLog(urlForLog, `🚀 Importando a Media...`);

          // Evita duplicados: si ya existe el archivo con el mismo nombre en Media, no lo re-importamos.
          const existingNames = new Set(
            useProjectStore.getState().project.mediaLibrary.items.map((m) => m.name),
          );

          // 1) Video (sin audio, servido por /files/{index})
          const vblob = await v2vApi.fetchOutputVideoBlob(jobId, v.index);
          const videoMediaName = `${folder}/video.mp4`;
          if (existingNames.has(videoMediaName)) {
            if (urlForLog) appendUrlLog(urlForLog, `✅ Video importado`);
          } else {
            const vfile = new File([vblob], videoMediaName, { type: "video/mp4" });
            
            const vimport = isTargetActive 
              ? await useProjectStore.getState().importMedia(vfile)
              : await useProjectStore.getState().importMediaToProjectSilent(targetId!, vfile);

            if (!vimport.success) {
              setRegenStatus(
                (vimport.error as any)?.message || `Error importando video: ${folder}`
              );
              if (urlForLog)
                appendUrlLog(
                  urlForLog,
                  `❌ ${(vimport.error as any)?.message || "Error importando video"}`,
                );
              setImportStatus(key, "error");
              continue;
            }
            existingNames.add(videoMediaName);
            if (urlForLog) appendUrlLog(urlForLog, `✅ Video importado`);
          }

          // 2) Audios por segmento
          for (let i = 0; i < audioSegs.length; i++) {
            const seg = audioSegs[i];
            setRegenStatus(`Importando audio ${folder} (${i + 1}/${audioSegs.length})...`);
            const wavBlob = await v2vApi.fetchAudioSegmentBlob(jobId, v.index, seg.seg);
            const wavName = `${folder}/tts_${toSafeToken(seg.speaker || "speaker")}_${String(seg.seg).padStart(4, "0")}.wav`;
            if (existingNames.has(wavName)) {
              continue;
            }

            const wavFile = new File([wavBlob], wavName, { type: "audio/wav" });
            
            const wres = isTargetActive
              ? await useProjectStore.getState().importMedia(wavFile)
              : await useProjectStore.getState().importMediaToProjectSilent(targetId!, wavFile);

            if (!wres.success) {
              if (urlForLog)
                appendUrlLog(
                  urlForLog,
                  `❌ WAV seg ${seg.seg}: ${(wres.error as any)?.message || "falló"}`,
                );
              setImportStatus(key, "error");
              break;
            }
            existingNames.add(wavName);
          }

          if (useV2VStore.getState().importStatusByKey[key] !== "error" && isTargetActive) {
            setImportStatus(key, "done");
            // Auto-import al timeline SOLO SI ES EL PROYECTO SELECCIONADO.
            // (Si no es el activo, no tocamos el timeline para no interrumpir al usuario)
            const { addTrack, addClip } = useProjectStore.getState();
            const currentProject = useProjectStore.getState().project;

            const videoMediaName = `${folder}/video.mp4`;
            const videoMedia = currentProject.mediaLibrary.items.find(
              (m) => m.name === videoMediaName,
            );

            // Video track
            const beforeVideoTrackIds = new Set(
              currentProject.timeline.tracks.map((t) => t.id),
            );
            const videoAddRes = await addTrack("video");
            if (!videoAddRes.success) {
              setRegenStatus(`Importado en Media, pero falló crear video track: ${folder}`);
              useV2VStore.getState().setFolderRef(folder, {
                jobId,
                videoIndex: v.index,
              });
              continue;
            }

            const afterVideoProject = useProjectStore.getState().project;
            const videoTrack = afterVideoProject.timeline.tracks.find(
              (t) => t.type === "video" && !beforeVideoTrackIds.has(t.id),
            );

            if (videoTrack && videoMedia) {
              await addClip(videoTrack.id, videoMedia.id, 0);
            }

            // Audio tracks (1 por speaker)
            const bySpeaker: Record<string, AudioSegmentItem[]> = {};
            for (const seg of audioSegs) {
              const token = toSafeToken(seg.speaker || "speaker");
              (bySpeaker[token] ||= []).push(seg);
            }
            for (const speakerToken of Object.keys(bySpeaker)) {
              const beforeAudioTrackIds = new Set(
                useProjectStore.getState().project.timeline.tracks.map((t) => t.id),
              );
              const audioAddRes = await addTrack("audio");
              if (!audioAddRes.success) continue;

              const afterAudioProject = useProjectStore.getState().project;
              const audioTrack = afterAudioProject.timeline.tracks.find(
                (t) =>
                  t.type === "audio" && !beforeAudioTrackIds.has(t.id),
              );
              if (!audioTrack) continue;

              // Renombramos el track para que sea fácil identificar el speaker.
              useProjectStore.setState((state) => ({
                project: {
                  ...state.project,
                  timeline: {
                    ...state.project.timeline,
                    tracks: state.project.timeline.tracks.map((t) =>
                      t.id === audioTrack.id ? { ...t, name: `TTS_${speakerToken}` } : t,
                    ),
                  },
                },
              }));

              const orderedSegs = bySpeaker[speakerToken]
                .slice()
                .sort((a, b) => a.seg - b.seg);

              for (const seg of orderedSegs) {
                const wavName = `${folder}/tts_${toSafeToken(seg.speaker || "speaker")}_${String(
                  seg.seg,
                ).padStart(4, "0")}.wav`;
                const wavMedia = useProjectStore.getState().project.mediaLibrary.items.find(
                  (m) => m.name === wavName,
                );
                if (!wavMedia) continue;

                await addClip(audioTrack.id, wavMedia.id, seg.start);
              }
            }

            // Fuerza guardado para que cada URL quede como proyecto recuperable.
            await useProjectStore.getState().forceSave();

            setRegenStatus(`Importado y pegado al timeline: ${folder}`);
            if (urlForLog) appendUrlLog(urlForLog, `✅ Audios importados`);
            // Referencia para el botón "Añadir a la timeline" desde la carpeta.
            } // end if importStatus !== "error"
          } // end for
        } finally {
          importingRef.current = false;
        }
        } // cierra if pendingVideos
        } // cierra if !importingRef.current
        
        if (s.status === "done") {
          setIsProcessing(false);
          setJobPhase("done");
          const result = await v2vApi.getJobResult(jobId);
          setVideos(result.videos);
          if (result.videos.length > 0) {
            setSegments(result.videos[0].segments);
            setSelectedVideoIndex(0);
          }
          if (result.log) setLog(result.log);
        } else if (s.status === "error") {
          setIsProcessing(false);
          setJobPhase("error");
          setError(s.message || "Error en el procesamiento");
          const finalLog = await v2vApi.getJobLog(jobId);
          if (finalLog) setLog(finalLog);
        }
      } catch {
        // ignore
      }
    }, POLL_INTERVAL);
    return () => clearInterval(t);
  }, [jobId, isProcessing, log.length, selectedVideoIndex]);

  const handleProcess = useCallback(async () => {
    const urlList = urls
      .split("\n")
      .map((u) => u.trim())
      .filter(Boolean);
    const normalized = urlList
      .map((u) => (/^https?:\/\//i.test(u) ? u : `https://${u}`))
      .filter((u) => /^https?:\/\/(www\.)?(youtube\.com\/|youtu\.be\/)/i.test(u));
    if (normalized.length === 0) {
      setError("Introduce al menos una URL de YouTube");
      return;
    }
    const signature = normalized.map((u) => encodeURIComponent(u)).join("|");
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
      setSegments((prev) =>
        prev.map((s, i) =>
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
    <div className="h-full flex flex-col bg-background-secondary min-w-[300px]">
      <ScrollArea className="flex-1">
        <div className={`p-4 space-y-6 transition-opacity duration-300 ${isProcessing ? "opacity-60 pointer-events-none select-none" : ""}`}>
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
                    <option value="openai_shimmer">openai_shimmer</option>
                    <option value="dionisio_schuyler">Dionisio Schuyler</option>
                  </>
                )}
              </select>
            </div>
          </div>

          <Button
            className="w-full"
            onClick={handleProcess}
            disabled={!urls.trim() || isProcessing}
          >
            {isProcessing ? (
              <>
                <Loader2 size={16} className="mr-2 animate-spin" />
                {jobPhase === "pending"
                  ? "Enviando..."
                  : `Procesando (${jobPhase}): ${Math.round(progress)}%`}
              </>
            ) : (
              "Iniciar Proceso V2V"
            )}
          </Button>

          {isProcessing && (
            <div className="space-y-1">
              <div className="h-1 bg-background-tertiary rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="text-[9px] text-text-muted text-right">
                {Math.round(progress)}% completado
              </p>
            </div>
          )}

          {error && (
            <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg flex items-start gap-2 text-red-400">
              <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
              <p className="text-xs">{error}</p>
            </div>
          )}

          {videos.length > 0 && (
            <div className="space-y-4 border-t border-border pt-4">
              <div className="space-y-1">
                <label className="text-[10px] text-text-muted block">Video Procesado</label>
                <div className="flex gap-2">
                  <select
                    className="flex-1 min-w-0 truncate px-3 py-2 text-xs bg-background-tertiary border border-border rounded-lg"
                    value={selectedVideoIndex}
                    onChange={(e) => handleVideoSelect(parseInt(e.target.value, 10))}
                  >
                    {videos.map((v, i) => (
                      <option key={i} value={i}>
                        {v.output_name}
                      </option>
                    ))}
                  </select>
                  <Button
                    size="icon"
                    variant="secondary"
                    className="h-8 w-8"
                    title="Re-importar a Media"
                    onClick={async () => {
                      const v = videos[selectedVideoIndex];
                      if (!v || !jobId) return;
                      setIsProcessing(true);
                      setRegenStatus("Re-importando archivos...");
                      try {
                        const folder = sanitizeFolderName(v.output_name || `video_${v.index}`);
                        const projectStore = useProjectStore.getState();
                        const currentItems = useV2VStore.getState().urlItems;
                        const pos = currentItems.findIndex(it => it.url === v.url && it.index === v.index);
                        const seq = pos >= 0 ? pos + 1 : v.index + 1;
                        const projectTitle = `${seq}. TTS ${shortProjectToken(v.output_name || folder)}`;
                        
                        await autoSaveManager.initialize();
                        const saves = await autoSaveManager.checkForRecovery();
                        const targetSave = saves.find(s => s.projectName === projectTitle);
                        let targetId = targetSave?.projectId || targetSave?.id;

                        if (!targetId) {
                          targetId = await projectStore.createProjectSilent(projectTitle, projectStore.project.settings);
                        }

                        const isTargetActive = projectStore.project.id === targetId || projectStore.project.name === projectTitle;
                        
                        // Video
                        const videoMediaName = `${folder}/video.mp4`;
                        const vblob = await v2vApi.fetchOutputVideoBlob(jobId, v.index);
                        const vfile = new File([vblob], videoMediaName, { type: "video/mp4" });
                        
                        if (isTargetActive) await projectStore.importMedia(vfile);
                        else await projectStore.importMediaToProjectSilent(targetId, vfile);

                        // Audios
                        const audioSegs = v.segments.filter((s) => s.text?.trim().length > 0);
                        for (const seg of audioSegs) {
                          const speakerToken = toSafeToken(seg.speaker || "speaker");
                          const wavName = `${folder}/tts_${speakerToken}_${String(seg.seg).padStart(4, "0")}.wav`;
                          const wavBlob = await v2vApi.fetchAudioSegmentBlob(jobId, v.index, seg.seg);
                          const wavFile = new File([wavBlob], wavName, { type: "audio/wav" });
                          
                          if (isTargetActive) await projectStore.importMedia(wavFile);
                          else await projectStore.importMediaToProjectSilent(targetId, wavFile);
                        }
                        
                        toast.success("Importado", `Archivos en proyecto "${projectTitle}"`);
                      } catch (e) {
                        toast.error("Error", String(e));
                      } finally {
                        setIsProcessing(false);
                        setRegenStatus("");
                      }
                    }}
                    disabled={isProcessing}
                  >
                    {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <FolderDown size={14} />}
                  </Button>
                  <Button size="icon" variant="secondary" className="h-8 w-8" onClick={handleShare} title="Compartir" disabled={isProcessing}>
                    <Share2 size={14} />
                  </Button>
                </div>
              </div>

              <Button
                size="sm"
                variant="secondary"
                className="w-full"
                onClick={handleDownloadZip}
                disabled={isProcessing}
              >
                <Download size={14} className="mr-2" />
                Descargar ZIP
              </Button>

              {shareUrl && (
                <div className="p-3 bg-background-tertiary rounded-lg border border-border">
                  <p className="text-[10px] text-text-muted mb-1">Enlace para compartir:</p>
                  <a href={shareUrl} target="_blank" rel="noreferrer" className="text-xs text-primary underline truncate block">
                    {shareUrl}
                  </a>
                </div>
              )}

              <div className="space-y-2">
                <p className="text-[10px] text-text-muted">Segmentos (edita y regenera)</p>
                <div className="max-h-60 overflow-y-auto border border-border rounded-lg bg-background-tertiary">
                  <table className="w-full text-[10px] border-collapse">
                    <thead className="bg-background-elevated sticky top-0 z-10">
                      <tr>
                        <th className="px-2 py-1.5 text-left font-medium border-b border-border w-10">#</th>
                        <th className="px-2 py-1.5 text-left font-medium border-b border-border w-16">Inicio</th>
                        <th className="px-2 py-1.5 text-left font-medium border-b border-border w-16">Final</th>
                        <th className="px-2 py-1.5 text-left font-medium border-b border-border">Texto</th>
                      </tr>
                    </thead>
                    <tbody>
                      {segments.map((seg, i) => (
                        <tr
                          key={i}
                          onClick={() => setSelectedRowIndex(i)}
                          className={`cursor-pointer hover:bg-background-elevated transition-colors ${selectedRowIndex === i ? "bg-primary/10" : "border-t border-border/50"}`}
                        >
                          <td className="px-2 py-1.5 text-text-muted">{seg.seg}</td>
                          <td className="px-2 py-1.5">
                            <input
                              type="number"
                              step="0.01"
                              className="w-full bg-transparent border-none p-0 focus:ring-0"
                              value={seg.start}
                              onChange={(e) => handleSegmentEdit(i, "start", parseFloat(e.target.value) || 0)}
                              onClick={(e) => e.stopPropagation()}
                            />
                          </td>
                          <td className="px-2 py-1.5">
                            <input
                              type="number"
                              step="0.01"
                              className="w-full bg-transparent border-none p-0 focus:ring-0"
                              value={seg.end}
                              onChange={(e) => handleSegmentEdit(i, "end", parseFloat(e.target.value) || 0)}
                              onClick={(e) => e.stopPropagation()}
                            />
                          </td>
                          <td className="px-2 py-1.5">
                            <input
                              type="text"
                              className="w-full bg-transparent border-none p-0 focus:ring-0 truncate"
                              value={seg.text}
                              onChange={(e) => handleSegmentEdit(i, "text", e.target.value)}
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
                  className="flex-1 text-[11px]"
                  onClick={handleRegenerateSegment}
                  disabled={selectedRowIndex === null || isProcessing}
                >
                  <RefreshCw size={12} className="mr-1.5" />
                  Regenerar Segmento
                </Button>
                <Button size="sm" className="flex-1 text-[11px]" onClick={handleRegenerateVideo} disabled={isProcessing}>
                  Aplicar cambios y renderizar
                </Button>
              </div>

              {regenStatus && (
                <p className={`text-[10px] text-center ${regenStatus.toLowerCase().includes("error") ? "text-red-400" : "text-text-muted animate-pulse"}`}>
                  {regenStatus}
                </p>
              )}
            </div>
          )}

          {urlItems.length > 0 && (
            <div className="space-y-2 border-t border-border pt-4">
              <p className="text-[10px] text-text-muted">Estado del Proceso</p>
              <div className="bg-black/20 rounded-lg p-3 font-mono text-[10px] max-h-48 overflow-y-auto space-y-2">
                {urlItems.map((item, i) => (
                  <div key={i} className="flex flex-col gap-1 pb-2 border-b border-white/5 last:border-0 last:pb-0">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-white truncate flex-1" title={item.url}>
                        {i + 1}. {item.output_name || item.url}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold uppercase whitespace-nowrap ${statusToBadgeClass(item.status)}`}>
                        {STATUS_LABEL[item.status] || item.status}
                      </span>
                    </div>
                    {urlLogs[item.url] && urlLogs[item.url].split("\n").slice(-2).map((msg, j) => (
                      <p key={j} className="text-text-muted/60 pl-3 border-l border-white/10 italic text-[9px]">
                        {msg}
                      </p>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
};

export default V2VPanel;
