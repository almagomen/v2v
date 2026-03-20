import React, { useState, useEffect, useCallback } from "react";
import { Youtube, Loader2, AlertCircle, RefreshCw, Download, Share2 } from "lucide-react";
import { ScrollArea, Button } from "@openreel/ui";
import { v2vApi, type AudioSegmentItem } from "../../lib/v2v-api";
import { useProjectStore } from "../../stores/project-store";
import { useV2VStore } from "../../stores/v2v-store";

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

function deriveMainTag(jobPhase: string, hasImportsInFlight: boolean): string {
  if (hasImportsInFlight) return "Importando a Media";
  if (!jobPhase || jobPhase === "idle") return "Procesar";
  return STATUS_LABEL[jobPhase] || jobPhase;
}

function toSafeToken(s: string): string {
  const ascii = s
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .replace(/^[_\-.]+|[_\-.]+$/g, "")
    .slice(0, 40);
  return ascii || "speaker";
}

function sanitizeFolderName(name: string): string {
  // El folder se infiere por `Carpeta/archivo`, así que evitamos `/`.
  const cleaned = (name || "Video").replaceAll("/", "_").replaceAll("\\", "_").trim();
  return cleaned || "Video";
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
  const importMedia = useProjectStore((state) => state.importMedia);

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
        // Reflejar mensajes de estado también en el log por URL (sin spamear duplicados)
        for (const it of items) {
          if (!it.url || !it.message) continue;
          const marker = `[STATE:${it.status}]${it.message}`;
          const prev = useV2VStore.getState().urlLogs[it.url] || "";
          if (!prev.includes(marker)) appendUrlLog(it.url, marker);
        }

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

        // Auto-import incremental: por cada video aparecido en `videos`, importar video+audios a Media
        const currentVideos = useV2VStore.getState().videos;
        for (const v of currentVideos) {
          const key = `${jobId}:${v.index}`;
          if (useV2VStore.getState().importStatusByKey[key]) continue;
          // Marcamos INMEDIATO como in_progress para evitar duplicación por ticks solapados
          setImportStatus(key, "in_progress");

          // Sólo importamos cuando el backend ya tiene WAVs en Seqs_trg (si no, esperamos al siguiente tick)
          let audioSegs: AudioSegmentItem[] = [];
          try {
            audioSegs = await v2vApi.getAudioSegments(jobId, v.index);
          } catch {
            setImportStatus(key, "error");
            continue;
          }
          if (!audioSegs.length) continue;

          const folder = sanitizeFolderName(v.output_name || `video_${v.index}`);
          const urlForLog = v.url || "";
          setRegenStatus(`Importando a Media: ${folder}...`);
          if (urlForLog) appendUrlLog(urlForLog, `[STATE:import]🚀 Importando a Media...`);

          // 1) Video (sin audio, servido por /files/{index})
          const vblob = await v2vApi.fetchOutputVideoBlob(jobId, v.index);
          const vfile = new File([vblob], `${folder}/video.mp4`, { type: "video/mp4" });
          const vimport = await importMedia(vfile);
          if (!vimport.success) {
            setRegenStatus(vimport.error?.message || `Error importando video: ${folder}`);
            if (urlForLog) appendUrlLog(urlForLog, `[STATE:import][ERROR] ${vimport.error?.message || "Error importando video"}`);
            setImportStatus(key, "error");
            continue;
          }
          if (urlForLog) appendUrlLog(urlForLog, `[STATE:video]✅ Video importado`);

          // 2) Audios por segmento
          for (let i = 0; i < audioSegs.length; i++) {
            const seg = audioSegs[i];
            setRegenStatus(`Importando audio ${folder} (${i + 1}/${audioSegs.length})...`);
            if (urlForLog) appendUrlLog(urlForLog, `Importando audio seg ${seg.seg} (${i + 1}/${audioSegs.length})...`);
            const wavBlob = await v2vApi.fetchAudioSegmentBlob(jobId, v.index, seg.seg);
            const wavName = `${folder}/tts_${toSafeToken(seg.speaker || "speaker")}_${String(seg.seg).padStart(4, "0")}.wav`;
            const wavFile = new File([wavBlob], wavName, { type: "audio/wav" });
            const wres = await importMedia(wavFile);
            if (!wres.success) {
              if (urlForLog) appendUrlLog(urlForLog, `[STATE:audio][ERROR] WAV seg ${seg.seg}: ${wres.error?.message || "falló"}`);
              setImportStatus(key, "error");
              break;
            }
          }

          if (useV2VStore.getState().importStatusByKey[key] !== "error") {
            setImportStatus(key, "done");
            setRegenStatus(`Importado en Media: ${folder}`);
            if (urlForLog) appendUrlLog(urlForLog, `[STATE:audio]✅ Audios importados`);
            // Referencia para el botón "Añadir a la timeline" desde la carpeta.
            useV2VStore.getState().setFolderRef(folder, { jobId, videoIndex: v.index });
          }
        }

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
  }, [jobId, isProcessing, importMedia, log.length, selectedVideoIndex]);

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
    <ScrollArea className="flex-1 w-full">
      <div className="p-4 space-y-4 min-w-0">
        <div className="flex items-center gap-2">
          <Youtube size={20} className="text-red-500" />
          <h2 className="text-sm font-semibold text-text-primary">
            Video2Video – Traducción y doblaje
          </h2>
        </div>

        <div>
          <label className="text-[10px] text-text-muted block mb-1">
            URLs de YouTube (una por línea)
          </label>
          <textarea
            className="w-full h-24 px-3 py-2 text-xs bg-background-tertiary border border-border rounded-lg resize-none focus:outline-none focus:ring-1 focus:ring-primary"
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
          disabled={isProcessing}
          className="w-full"
        >
          {(() => {
            const hasImportsInFlight = Object.values(importStatusByKey).some(
              (s) => s === "in_progress"
            );
            const tag = deriveMainTag(jobPhase, hasImportsInFlight);
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
                  {urlItems.map((it, i) => (
                    <tr key={it.url} className="border-t border-border">
                      <td className="px-2 py-1 tabular-nums">{i + 1}</td>
                      <td className="px-2 py-1 max-w-[220px] truncate" title={it.url}>
                        {it.output_name || it.url}
                        {typeof it.index === "number" &&
                          importStatusByKey[`${jobId}:${it.index}`] === "done" && (
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

                // Inyectamos tags [STATE:...] directamente en el log general
                // para que se vea "un solo panel" con el patrón deseado.
                for (const it of urlItems) {
                  if (!it.url) continue;
                  out = out.replaceAll(
                    `⚙️ Procesando: ${it.url}`,
                    `[STATE:downloading]⚙️ Procesando: ${it.url}`,
                  );
                }
                out = out.replaceAll(
                  "📝 Transcribiendo (Whisper + diarización)...",
                  "[STATE:transcribing]📝 Transcribiendo (Whisper + diarización)...",
                );

                // Antes de la primera tanda de segmentos TTS.
                out = out.replace(
                  /^(\s*)0\. Fast:/gm,
                  "$1[STATE:tts]⚡ TTS:\n$10. Fast:",
                );

                // Import-only: mostramos solo los pasos de "Media import"
                // que se registran en `urlLogs`.
                const importLines: string[] = [];
                for (const it of urlItems) {
                  const raw = urlLogs[it.url] || "";
                  for (const line of raw.split("\n")) {
                    if (
                      line.startsWith("[STATE:import]") ||
                      line.startsWith("[STATE:video]") ||
                      line.startsWith("[STATE:audio]")
                    ) {
                      importLines.push(line);
                    }
                  }
                }

                return `${out}${importLines.length ? `\n${importLines.join("\n")}` : ""}`;
              })()}
            </pre>
          </div>
        )}

        {videos.length > 0 && (
          <>
            <div>
              <label className="text-[10px] text-text-muted block mb-1">Video procesado</label>
              <select
                className="w-full px-3 py-2 text-xs bg-background-tertiary border border-border rounded-lg"
                value={selectedVideoIndex}
                onChange={(e) => handleVideoSelect(parseInt(e.target.value, 10))}
              >
                {videos.map((v, i) => (
                  <option key={i} value={i}>
                    {v.output_name}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex gap-2">
              <Button size="sm" variant="secondary" disabled className="flex-1">
                Se importa a Media automáticamente
              </Button>
              <Button size="sm" variant="secondary" onClick={handleShare} className="flex-1">
                <Share2 size={12} className="mr-1" />
                Compartir
              </Button>
              <Button
                size="sm"
                variant="secondary"
                className="flex-1"
                onClick={handleDownloadZip}
                disabled={!jobId}
              >
                <Download size={12} className="mr-1" />
                ZIP
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
                    {segments.map((seg, i) => (
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

