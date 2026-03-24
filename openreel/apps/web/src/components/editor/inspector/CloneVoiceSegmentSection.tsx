import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, History, Loader2, RefreshCw } from "lucide-react";
import {
  getTranscriptionService,
  initializeTranscriptionService,
} from "@openreel/core";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@openreel/ui";

import { v2vApi, type SpeakerOption, type JobResultResponse } from "../../../lib/v2v-api";
import { useProjectStore } from "../../../stores/project-store";

// Cache en memoria para resultados de jobs
const jobResultCache = new Map<string, JobResultResponse>();
function getCachedJobResult(jobId: string): JobResultResponse | undefined {
  return jobResultCache.get(jobId);
}
function setCachedJobResult(jobId: string, result: JobResultResponse): void {
  jobResultCache.set(jobId, result);
}
import { useV2VStore } from "../../../stores/v2v-store";
import { invalidateAudioCache } from "../../../stores/audio-cache-store";

type V2VParsedSegment = {
  folder: string;
  speakerToken: string;
  segIdx: number;
};

type TextVersion = {
  text: string;
  speaker: string;
  timestamp: number;
  isCurrent: boolean;
};

function parseV2VSegmentFromName(name: string): V2VParsedSegment | null {
  const normalized = name.replace(/\\/g, "/");
  const match = normalized.match(/^(?:(.+?)\/)?tts_(.+)_(\d+)\.wav$/);
  if (!match) return null;

  const folder = match[1];
  const speakerToken = match[2];
  const segIdx = parseInt(match[3], 10);

  if (!folder || Number.isNaN(segIdx)) return null;
  return { folder, speakerToken, segIdx };
}

function joinNonEmpty(parts: string[]): string {
  return parts
    .map((p) => p.trim())
    .filter(Boolean)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

function getLocalStorageKey(filename: string): string {
  return `v2v_cloned_text_${filename}`;
}

function loadFromLocalStorage(filename: string): { text: string; speaker: string; timestamp: number } | null {
  if (typeof window === "undefined") return null;
  try {
    const key = getLocalStorageKey(filename);
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as { text: string; speaker: string; timestamp: number };
  } catch {
    return null;
  }
}

function saveToLocalStorage(filename: string, data: { text: string; speaker: string; timestamp: number }): void {
  if (typeof window === "undefined") return;
  try {
    const key = getLocalStorageKey(filename);
    localStorage.setItem(key, JSON.stringify(data));
  } catch {
    // ignore quota errors
  }
}

function loadHistoryFromLocalStorage(filename: string): TextVersion[] {
  if (typeof window === "undefined") return [];
  try {
    const key = `v2v_cloned_history_${filename}`;
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const history = JSON.parse(raw) as TextVersion[];
    return history.filter(v => !v.isCurrent);
  } catch {
    return [];
  }
}

function saveHistoryToLocalStorage(filename: string, history: TextVersion[]): void {
  if (typeof window === "undefined") return;
  try {
    const key = `v2v_cloned_history_${filename}`;
    localStorage.setItem(key, JSON.stringify(history));
  } catch {
    // ignore
  }
}

export const CloneVoiceSegmentSection: React.FC<{ clipId: string }> = ({ clipId }) => {
  const { getClip, getMediaItem, replaceMediaAsset, forceSave } = useProjectStore();
  const clip = getClip(clipId);
  const mediaItem = clip ? getMediaItem(clip.mediaId) : undefined;

  const { translateLang, speaker: defaultSpeaker, getFolderRef } = useV2VStore();

  const parsed = useMemo(() => {
    if (!mediaItem?.name) return null;
    return parseV2VSegmentFromName(mediaItem.name);
  }, [mediaItem?.name]);

  const folderRef = parsed ? getFolderRef(parsed.folder) : undefined;

  const [speakers, setSpeakers] = useState<SpeakerOption[]>([]);
  const [selectedVoice, setSelectedVoice] = useState<string>("");
  const [initialized, setInitialized] = useState(false);

  const [jobLoading, setJobLoading] = useState(false);
  const [jobError, setJobError] = useState<string | null>(null);

  const [segmentText, setSegmentText] = useState<string>("");
  const [segmentTimes, setSegmentTimes] = useState<{ start: number; end: number } | null>(null);

  const [sttLoading, setSttLoading] = useState(false);
  const [sttError, setSttError] = useState<string | null>(null);

  const [regenLoading, setRegenLoading] = useState(false);
  const [regenError, setRegenError] = useState<string | null>(null);
  const [regenStatus, setRegenStatus] = useState<string | null>(null);

  const [textVersions, setTextVersions] = useState<TextVersion[]>([]);

  useEffect(() => {
    if (!initialized && defaultSpeaker) {
      setSelectedVoice(defaultSpeaker);
      setInitialized(true);
    }
  }, [defaultSpeaker, initialized]);

  useEffect(() => {
    v2vApi.getSpeakers().then(setSpeakers).catch(() => setSpeakers([]));
  }, []);

  useEffect(() => {
    if (mediaItem?.name) {
      const history = loadHistoryFromLocalStorage(mediaItem.name);
      setTextVersions(history);
    }
  }, [mediaItem?.name]);

  useEffect(() => {
    let cancelled = false;

    async function loadFromJob() {
      if (!folderRef || !parsed || !clip || !mediaItem) return;
      if (!folderRef.jobId) return;

      setJobLoading(true);
      setJobError(null);

      try {
        const localData = loadFromLocalStorage(mediaItem.name);
        
        let job = getCachedJobResult(folderRef.jobId);
        if (!job) {
          job = await v2vApi.getJobResult(folderRef.jobId);
          setCachedJobResult(folderRef.jobId, job);
        }
        if (cancelled) return;

        const video = job.videos.find((v) => v.index === folderRef.videoIndex);
        const seg = video?.segments.find((s) => s.seg === parsed.segIdx);

        const start = seg?.start ?? clip.startTime;
        const end = seg?.end ?? clip.startTime + clip.duration;

        setSegmentTimes({ start, end });
        
        if (localData) {
          setSegmentText(localData.text);
          setSelectedVoice(localData.speaker);
        } else {
          setSegmentText(seg?.text ?? "");
        }
      } catch (e) {
        if (cancelled) return;
        setJobError(e instanceof Error ? e.message : "Error al cargar texto del segmento");
      } finally {
        if (!cancelled) setJobLoading(false);
      }
    }

    loadFromJob();
    return () => {
      cancelled = true;
    };
  }, [folderRef, parsed, clip, mediaItem]);

  const effectiveTimes = useMemo(() => {
    if (segmentTimes) return segmentTimes;
    if (!clip) return null;
    return { start: clip.startTime, end: clip.startTime + clip.duration };
  }, [segmentTimes, clip]);

  const normalizeTranslateLang = useMemo(() => {
    return translateLang === "None" ? null : translateLang;
  }, [translateLang]);

  const handleTranscribeWithOpenReel = useCallback(async () => {
    if (!clip || !mediaItem) return;
    if (!mediaItem.blob) {
      setSttError("No hay blob de audio disponible para transcribir");
      return;
    }

    setSttLoading(true);
    setSttError(null);
    try {
      let transcriptionService = getTranscriptionService();
      if (!transcriptionService) {
        transcriptionService = initializeTranscriptionService({
          apiEndpoint: "https://transcribe.openreel.video",
        });
      }

      const subtitles = await transcriptionService.transcribeClip(clip, mediaItem);
      const text = joinNonEmpty(subtitles.map((s) => s.text || ""));
      setSegmentText(text);

      if (!segmentTimes) {
        setSegmentTimes({
          start: clip.startTime,
          end: clip.startTime + clip.duration,
        });
      }
    } catch (e) {
      setSttError(e instanceof Error ? e.message : "STT falló");
    } finally {
      setSttLoading(false);
    }
  }, [clip, mediaItem, segmentTimes]);

  const handleTranscribeWithBackend = useCallback(async () => {
    if (!mediaItem?.blob) return;

    setSttLoading(true);
    setSttError(null);
    try {
      const apiBase = (import.meta.env.VITE_V2V_API_URL || "").replace(/\/$/, "");
      const isLocalhostLikeHost = (hostname: string) =>
        hostname === "localhost" || hostname === "127.0.0.1" || hostname === "0.0.0.0";
      const apiBaseTargetsLocalhost = (base: string) =>
        /\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?/i.test(base);

      const url = (path: string) => {
        if (!apiBase) return path;
        if (typeof window !== "undefined") {
          const currentHost = window.location.hostname;
          if (apiBaseTargetsLocalhost(apiBase) && !isLocalhostLikeHost(currentHost)) {
            return path;
          }
        }
        return `${apiBase}${path}`;
      };

      const blob = mediaItem.blob;
      const fileLike =
        blob instanceof File
          ? blob
          : new File([blob], "audio.wav", { type: "audio/wav" });

      const formData = new FormData();
      formData.append("audio", fileLike);

      const res = await fetch(url("/api/transcribe-audio"), {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const errText = await res.text().catch(() => "");
        throw new Error(errText || `HTTP ${res.status}`);
      }

      const data = (await res.json()) as {
        segments?: Array<{ start: number; end: number; text: string }>;
      };

      const segments = data.segments || [];
      const text = joinNonEmpty(segments.map((s) => s.text || ""));
      setSegmentText(text);
    } catch (e) {
      setSttError(e instanceof Error ? e.message : "STT backend falló");
    } finally {
      setSttLoading(false);
    }
  }, [mediaItem]);

  const handleRestoreVersion = useCallback((version: TextVersion) => {
    setSegmentText(version.text);
    setSelectedVoice(version.speaker);
  }, []);

  const handleRegenerate = useCallback(async () => {
    if (!folderRef || !parsed || !clip || !mediaItem) return;
    if (!effectiveTimes) return;
    if (!segmentText.trim()) {
      setRegenError("El texto no puede estar vacío");
      return;
    }

    const currentText = segmentText;
    const currentSpeaker = selectedVoice;

    setRegenLoading(true);
    setRegenError(null);
    setRegenStatus(null);
    try {
      const { blob } = await (async () => {
        const regenBlob = await v2vApi.regenerateSegment(
          folderRef.jobId,
          folderRef.videoIndex,
          parsed.segIdx,
          segmentText,
          effectiveTimes.start,
          effectiveTimes.end,
          normalizeTranslateLang,
          selectedVoice,
        );
        return { blob: regenBlob };
      })();

      const file = new File([blob], mediaItem.name, { type: "audio/wav" });
      const result = await replaceMediaAsset(mediaItem.id, file);
      if (!result.success) {
        const msg =
          typeof result.error === "string"
            ? result.error
            : result.error?.message || "Error al reemplazar audio";
        throw new Error(msg);
      }

        invalidateAudioCache(mediaItem.id);
        await forceSave();

      const timestamp = Date.now();
      saveToLocalStorage(mediaItem.name, {
        text: currentText,
        speaker: currentSpeaker,
        timestamp,
      });

      const newVersion: TextVersion = {
        text: currentText,
        speaker: currentSpeaker,
        timestamp,
        isCurrent: true,
      };
      const updatedHistory = [newVersion, ...textVersions.slice(0, 9)];
      setTextVersions(updatedHistory);
      saveHistoryToLocalStorage(mediaItem.name, updatedHistory);

      setRegenStatus("Segmento regenerado");
    } catch (e) {
      setRegenError(e instanceof Error ? e.message : "Error al regenerar");
    } finally {
      setRegenLoading(false);
    }
  }, [
    folderRef,
    parsed,
    clip,
    mediaItem,
    effectiveTimes,
    segmentText,
    normalizeTranslateLang,
    selectedVoice,
    replaceMediaAsset,
    textVersions,
  ]);

  if (!clip || !mediaItem) {
    return (
      <div className="p-3 bg-background-tertiary border border-border rounded-lg text-[10px] text-text-muted">
        No clip seleccionado
      </div>
    );
  }

  if (!parsed) {
    return (
      <div className="p-3 bg-background-tertiary border border-border rounded-lg text-[10px] text-text-muted">
        Este clip no parece provenir de Video2Video (V2V), por lo que no hay
        "clonar voz" disponible.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <RefreshCw size={14} className="text-primary" />
        </div>
        {jobLoading && (
          <div className="flex items-center gap-2 text-[10px] text-text-muted">
            <Loader2 size={12} className="animate-spin" />
            Cargando texto
          </div>
        )}
      </div>

      {jobError && (
        <div className="flex items-center gap-2 p-2 bg-red-500/10 border border-red-500/30 rounded-lg">
          <AlertCircle size={14} className="text-red-400" />
          <span className="text-[10px] text-red-400">{jobError}</span>
        </div>
      )}

      {!folderRef && (
        <div className="flex items-center gap-2 p-2 bg-background-tertiary border border-border rounded-lg">
          <span className="text-[10px] text-text-muted">
            No se encontró referencia del job para este segmento. Es probable
            que no esté importado vía `video2video`.
          </span>
        </div>
      )}

      <div className="space-y-2">
        <label className="text-[10px] text-text-secondary block mb-1">
          Speaker (voz LMNT)
        </label>
        <Select
          value={selectedVoice}
          onValueChange={(v) => setSelectedVoice(v)}
          disabled={regenLoading || speakers.length === 0}
        >
          <SelectTrigger className="w-full bg-background-secondary border-border text-text-primary text-[11px]">
            <SelectValue placeholder={speakers.length === 0 ? "Cargando voces..." : "Seleccionar voz..."} />
          </SelectTrigger>
          <SelectContent className="bg-background-secondary border-border">
            {speakers.map((s) => (
              <SelectItem key={s.value} value={s.value}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <label className="text-[10px] text-text-secondary block mb-1">
          Texto a editar
        </label>
        <textarea
          value={segmentText}
          onChange={(e) => setSegmentText(e.target.value)}
          className="w-full min-h-[96px] px-3 py-2 bg-background-tertiary border border-border rounded-lg text-xs text-text-primary resize-none focus:outline-none focus:border-primary"
          placeholder="Edita el texto del segmento antes de regenerar..."
          disabled={regenLoading}
        />
      </div>

      {textVersions.length > 0 && (
        <div className="space-y-2">
          <label className="text-[10px] text-text-secondary block mb-1 flex items-center gap-1">
            <History size={10} />
            Versiones anteriores
          </label>
          <Select
            onValueChange={(value) => {
              const version = textVersions.find((v) => v.timestamp.toString() === value);
              if (version) {
                handleRestoreVersion(version);
              }
            }}
            value=""
            disabled={regenLoading}
          >
            <SelectTrigger className="w-full bg-background-secondary border-border text-text-primary text-[11px]">
              <SelectValue placeholder="Restaurar versión anterior..." />
            </SelectTrigger>
            <SelectContent className="bg-background-secondary border-border max-h-[200px]">
              {textVersions.map((version) => (
                <SelectItem key={version.timestamp} value={version.timestamp.toString()}>
                  <span className="text-[10px]">
                    {version.text.slice(0, 30)}
                    {version.text.length > 30 ? "..." : ""}
                    {" "}({version.speaker}) - {new Date(version.timestamp).toLocaleTimeString()}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      <div className="space-y-2">
        {sttError && (
          <div className="flex items-center gap-2 p-2 bg-red-500/10 border border-red-500/30 rounded-lg">
            <AlertCircle size={14} className="text-red-400" />
            <span className="text-[10px] text-red-400">{sttError}</span>
          </div>
        )}

        <div className="flex gap-2">
          <button
            onClick={handleTranscribeWithOpenReel}
            disabled={sttLoading || regenLoading}
            className="flex-1 py-2 bg-background-secondary border border-border rounded-lg text-[10px] text-text-secondary hover:text-text-primary transition-colors disabled:opacity-50"
          >
            {sttLoading ? (
              <>
                <Loader2 size={12} className="animate-spin mr-2 inline" />
                Transcribiendo...
              </>
            ) : (
              "STT OpenReel"
            )}
          </button>

          <button
            onClick={handleTranscribeWithBackend}
            disabled={sttLoading || regenLoading}
            className="flex-1 py-2 bg-background-secondary border border-border rounded-lg text-[10px] text-text-secondary hover:text-text-primary transition-colors disabled:opacity-50"
            title="Fallback backend (requiere endpoint /api/transcribe-audio)"
          >
            Whisper+diar.
          </button>
        </div>
      </div>

      <div className="space-y-2 pt-2 border-t border-border">
        {regenError && (
          <div className="flex items-center gap-2 p-2 bg-red-500/10 border border-red-500/30 rounded-lg">
            <AlertCircle size={14} className="text-red-400" />
            <span className="text-[10px] text-red-400">{regenError}</span>
          </div>
        )}

        {regenStatus && (
          <div className="flex items-center gap-2 p-2 bg-green-500/10 border border-green-500/30 rounded-lg">
            <span className="text-[10px] text-green-400">{regenStatus}</span>
          </div>
        )}

        <button
          onClick={handleRegenerate}
          disabled={!folderRef || regenLoading || !segmentText.trim()}
          className="w-full py-2.5 bg-primary hover:bg-primary/80 text-black rounded-lg text-[11px] font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {regenLoading ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              Regenerando...
            </>
          ) : (
            <>
              <RefreshCw size={14} />
              Clonar voz del segmento
            </>
          )}
        </button>
      </div>
    </div>
  );
};
