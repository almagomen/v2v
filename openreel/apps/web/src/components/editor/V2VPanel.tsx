import React, { useState, useEffect, useCallback } from "react";
import { Youtube, Loader2, AlertCircle, RefreshCw, Download, Share2 } from "lucide-react";
import { ScrollArea, Button } from "@openreel/ui";
import { v2vApi, type Segment, type VideoResult } from "../../lib/v2v-api";
import { useProjectStore } from "../../stores/project-store";

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

export const V2VPanel: React.FC = () => {
  const importMedia = useProjectStore((state) => state.importMedia);

  const [urls, setUrls] = useState("");
  const [translateLang, setTranslateLang] = useState("None");
  const [speaker, setSpeaker] = useState("mrbeast_lmnt");
  const [speakers, setSpeakers] = useState<{ label: string; value: string }[]>(
    []
  );
  const [jobId, setJobId] = useState<string | null>(null);
  const [log, setLog] = useState("");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [videos, setVideos] = useState<VideoResult[]>([]);
  const [selectedVideoIndex, setSelectedVideoIndex] = useState(0);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [selectedRowIndex, setSelectedRowIndex] = useState<number | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [regenStatus, setRegenStatus] = useState("");
  const [shareUrl, setShareUrl] = useState<string | null>(null);

  useEffect(() => {
    v2vApi.getSpeakers().then(setSpeakers);
  }, []);

  useEffect(() => {
    if (!jobId || !isProcessing) return;
    const t = setInterval(async () => {
      try {
        const s = await v2vApi.getJobStatus(jobId);
        setProgress(s.progress * 100);
        if (s.status === "done") {
          setIsProcessing(false);
          const result = await v2vApi.getJobResult(jobId);
          setVideos(result.videos);
          if (result.videos.length > 0) {
            setSegments(result.videos[0].segments);
            setSelectedVideoIndex(0);
          }
          if (result.log) setLog(result.log);
        } else if (s.status === "error") {
          setIsProcessing(false);
          setError(s.message || "Error en el procesamiento");
          const jobLog = await v2vApi.getJobLog(jobId);
          if (jobLog) setLog(jobLog);
        }
      } catch {
        // ignore
      }
    }, POLL_INTERVAL);
    return () => clearInterval(t);
  }, [jobId, isProcessing]);

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

  const handleLoadInEditor = useCallback(async () => {
    if (!jobId || !videos[selectedVideoIndex]) return;
    const v = videos[selectedVideoIndex];
    setRegenStatus("Cargando en editor...");
    try {
      const filename = v.output_filename || `${v.output_name}.mp4`;
      const blob = await v2vApi.fetchFileBlob(jobId, selectedVideoIndex, filename);
      const file = new File([blob], filename, { type: "video/mp4" });
      const result = await importMedia(file);
      if (result.success && result.actionId) {
        const { addClipToNewTrack } = useProjectStore.getState();
        await addClipToNewTrack(result.actionId, 0);
        setRegenStatus("Video cargado en la timeline");
      } else {
        setRegenStatus("Error al cargar");
      }
    } catch (e) {
      setRegenStatus(e instanceof Error ? e.message : "Error");
    }
  }, [jobId, selectedVideoIndex, videos, importMedia]);

  const handleShare = useCallback(async () => {
    if (!jobId) return;
    setRegenStatus("Subiendo a Catbox...");
    try {
      const u = await v2vApi.shareToCatbox(jobId, selectedVideoIndex);
      setShareUrl(u);
      setRegenStatus("Enlace listo");
    } catch (e) {
      setRegenStatus(e instanceof Error ? e.message : "Error");
    }
  }, [jobId, selectedVideoIndex]);

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

        <Button onClick={handleProcess} disabled={isProcessing} className="w-full">
          {isProcessing ? (
            <>
              <Loader2 size={14} className="animate-spin mr-2" />
              Procesando... {Math.round(progress)}%
            </>
          ) : (
            "Procesar"
          )}
        </Button>

        {error && (
          <div className="flex items-center gap-2 p-2 rounded-lg bg-red-500/10 text-red-500 text-xs">
            <AlertCircle size={14} />
            {error}
          </div>
        )}

        {log && (
          <div className="p-2 rounded-lg bg-background-tertiary font-mono text-[10px] max-h-32 overflow-y-auto whitespace-pre-wrap">
            {log}
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
              <Button size="sm" variant="secondary" onClick={handleLoadInEditor} className="flex-1">
                Cargar en editor
              </Button>
              <Button size="sm" variant="secondary" onClick={handleShare} className="flex-1">
                <Share2 size={12} className="mr-1" />
                Compartir
              </Button>
              <a href={jobId ? v2vApi.getZipUrl(jobId) : "#"} download className="flex-1">
                <Button size="sm" variant="secondary" className="w-full">
                  <Download size={12} className="mr-1" />
                  ZIP
                </Button>
              </a>
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

            {regenStatus && <p className="text-[10px] text-text-muted">{regenStatus}</p>}
          </>
        )}
      </div>
    </ScrollArea>
  );
};

