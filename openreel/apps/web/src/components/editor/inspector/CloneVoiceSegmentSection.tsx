import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import {
  getTranscriptionService,
  initializeTranscriptionService,
} from "@openreel/core";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@openreel/ui";

import { v2vApi, type SpeakerOption, type JobResultResponse } from "../../../lib/v2v-api";
import { useProjectStore } from "../../../stores/project-store";
import { moveClipToTrack, renameMediaInLibrary } from "../../../utils/detached-project-actions";

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


function parseV2VSegmentFromName(name: string): V2VParsedSegment | null {
  const normalized = name.replace(/\\/g, "/");

  // Formato nuevo: tts_{speaker}_{NNNN}.wav
  const matchNew = normalized.match(/^(?:(.+?)\/)?tts_(.+)_(\d{4})\.wav$/);
  if (matchNew) {
    const folder = matchNew[1];
    const speakerToken = matchNew[2];
    const segIdx = parseInt(matchNew[3], 10);
    if (folder && !Number.isNaN(segIdx)) {
      return { folder, speakerToken, segIdx };
    }
  }

  // Formato legacy: vocals_NNNN.wav
  const matchLegacy = normalized.match(/^(?:(.+?)\/)?vocals_(\d{4})\.wav$/);
  if (matchLegacy) {
    const folder = matchLegacy[1];
    const segIdx = parseInt(matchLegacy[2], 10);
    if (folder && !Number.isNaN(segIdx)) {
      return { folder, speakerToken: "SPEAKER_00", segIdx };
    }
  }

  return null;
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

function loadFromLocalStorage(filename: string): { text: string; speaker: string; speed?: number; timestamp: number } | null {
  if (typeof window === "undefined") return null;
  try {
    const key = getLocalStorageKey(filename);
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as { text: string; speaker: string; speed?: number; timestamp: number };
  } catch {
    return null;
  }
}

function saveToLocalStorage(filename: string, data: { text: string; speaker: string; speed?: number; timestamp: number }): void {
  if (typeof window === "undefined") return;
  try {
    const key = getLocalStorageKey(filename);
    localStorage.setItem(key, JSON.stringify(data));
  } catch {
    // ignore quota errors
  }
}


async function getAudioDuration(blob: Blob): Promise<number> {
  const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
  if (!AudioContextClass) {
    throw new Error("AudioContext no soportado");
  }
  const audioContext = new AudioContextClass();
  try {
    const arrayBuffer = await blob.arrayBuffer();
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
    return audioBuffer.duration;
  } finally {
    audioContext.close();
  }
}

export const CloneVoiceSegmentSection: React.FC<{ clipId: string }> = ({ clipId }) => {
  const { getClip, getMediaItem, replaceMediaAsset, forceSave, loadProject } = useProjectStore();
  const clip = getClip(clipId);
  const mediaItem = clip ? getMediaItem(clip.mediaId) : undefined;

  const { translateLang, speaker: defaultSpeaker, getFolderRef, speakers, fetchSpeakers } = useV2VStore();

  useEffect(() => {
    if (speakers.length === 0) {
      fetchSpeakers();
    }
  }, [speakers.length, fetchSpeakers]);


  const parsed = useMemo(() => {
    if (!mediaItem?.name) return null;
    return parseV2VSegmentFromName(mediaItem.name);
  }, [mediaItem?.name]);

  const folderRef = parsed ? getFolderRef(parsed.folder) : undefined;

  const [selectedVoice, setSelectedVoice] = useState<string>("");

  // Resuelve un token (key del backend) al value correcto del Select.
  // Busca por value exacto, luego por label exacto, y por último una normalización agresiva.
  function resolveSpeakerValue(token: string, speakerList: SpeakerOption[], defaultVal?: string): string {
    if (!token || speakerList.length === 0) return defaultVal || token;
    
    // Coincidencia exacta
    const byValue = speakerList.find((s) => s.value === token);
    if (byValue) return byValue.value;
    const byLabel = speakerList.find((s) => s.label === token);
    if (byLabel) return byLabel.value;

    // Función de normalización (remueve todo menos minúsculas/números)
    const normalize = (str: string) => str.toLowerCase().replace(/[^a-z0-9]/g, "");
    const normToken = normalize(token);

    // Búsqueda parcial ultra-tolerante (token puede venir con GUIDs raros, espacios como _, URI encoded, etc)
    const byFuzzy = speakerList.find((s) => {
      const normLabel = normalize(s.label);
      const normValue = normalize(s.value);
      return (
        normLabel.includes(normToken) || normToken.includes(normLabel) ||
        normValue.includes(normToken) || normToken.includes(normValue)
      );
    });

    if (byFuzzy) return byFuzzy.value;

    // Fallback: si es algo como "SPEAKER_00" de diarización, intentamos aplicar
    // la voz seleccionada por defecto en el store global.
    if (defaultVal) {
      const byDefValue = speakerList.find((s) => s.value === defaultVal);
      if (byDefValue) return byDefValue.value;
      const byDefLabel = speakerList.find((s) => s.label === defaultVal);
      if (byDefLabel) return byDefLabel.value;
      return defaultVal;
    }

    return token;
  }


  const [jobLoading, setJobLoading] = useState(false);
  const [jobError, setJobError] = useState<string | null>(null);

  const [segmentText, setSegmentText] = useState<string>("");
  const [segmentTimes, setSegmentTimes] = useState<{ start: number; end: number } | null>(null);

  const [sttLoading, setSttLoading] = useState(false);
  const [sttError, setSttError] = useState<string | null>(null);

  const [regenLoading, setRegenLoading] = useState(false);
  const [regenError, setRegenError] = useState<string | null>(null);
  const [regenStatus, setRegenStatus] = useState<string | null>(null);

  const [backendSpeaker, setBackendSpeaker] = useState<string | null>(null);
  const [speed, setSpeed] = useState<number>(1.0);
  const [speedMode, setSpeedMode] = useState<"x" | "s">("x");
  const [isApplyingSpeed, setIsApplyingSpeed] = useState(false);

  function getSpeakerFilenameToken(): string {
    if (!parsed) return "unknown";
    const speakerChanged = parsed.speakerToken !== selectedVoice;
    if (!speakerChanged) {
      return parsed.speakerToken;
    }
    const speakerLabel = speakers.find((s) => s.value === selectedVoice)?.label || selectedVoice;
    return speakerLabel.replace(/[^a-zA-Z0-9_-]/g, "_");
  }

  function getSpeakerTrackName(): string {
    return speakers.find((s) => s.value === selectedVoice)?.label || selectedVoice;
  }


  // Determinamos estáticamente qué token buscar (el local o el del filename)
  const activeTokenToResolve = useMemo(() => {
    if (!mediaItem?.name) return null;
    const localData = loadFromLocalStorage(mediaItem.name);
    if (localData) return localData.speaker;
    if (backendSpeaker) return backendSpeaker;
    if (parsed) return parsed.speakerToken;
    return null;
  }, [mediaItem?.name, parsed, backendSpeaker]);

  // Evaluamos la voz seleccionada reactivamente frente al store global de speakers
  useEffect(() => {
    if (activeTokenToResolve && speakers.length > 0) {
      setSelectedVoice(resolveSpeakerValue(activeTokenToResolve, speakers, defaultSpeaker));
    } else if (activeTokenToResolve && speakers.length === 0) {
      // Placeholder provisorio si no ha cargado
      setSelectedVoice(activeTokenToResolve);
    }
  }, [activeTokenToResolve, speakers, defaultSpeaker]);


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
          if (typeof localData.speed === "number") {
            setSpeed(localData.speed);
          }
        } else {
          setSegmentText(seg?.text ?? "");
        }
        
        if (seg?.speaker) {
          setBackendSpeaker(seg.speaker);
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


  const handleRegenerate = useCallback(async () => {
    if (!folderRef || !parsed || !clip || !mediaItem) return;
    if (!effectiveTimes) return;
    if (!segmentText.trim()) {
      setRegenError("El texto no puede estar vacío");
      return;
    }

    const currentText = segmentText;
    const currentSpeaker = selectedVoice;
    const oldSpeaker = parsed.speakerToken;

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
          speed,
        );
        return { blob: regenBlob };
      })();

      const newDuration = await getAudioDuration(blob);

      const speakerChanged = oldSpeaker !== currentSpeaker;
      const filenameToken = getSpeakerFilenameToken();
      const trackName = getSpeakerTrackName();

      const newFileName = `tts_${filenameToken}_${String(parsed.segIdx).padStart(4, "0")}.wav`;
      const newMediaName = `${parsed.folder}/${newFileName}`;

      const file = new File([blob], newMediaName, { type: "audio/wav" });
      
      const timestamp = Date.now();
      saveToLocalStorage(newMediaName, {
        text: currentText,
        speaker: currentSpeaker,
        speed,
        timestamp,
      });

      const result = await replaceMediaAsset(mediaItem.id, file);
      if (!result.success) {
        const msg =
          typeof result.error === "string"
            ? result.error
            : result.error?.message || "Error al reemplazar audio";
        throw new Error(msg);
      }

      invalidateAudioCache(mediaItem.id);

      if (speakerChanged) {
        const { project: renamedProject } = useProjectStore.getState();
        const projectAfterRename = renameMediaInLibrary(
          renamedProject,
          mediaItem.id,
          newMediaName,
        );
        const moveResult = await moveClipToTrack(
          projectAfterRename,
          clipId,
          trackName,
          effectiveTimes.start,
        );
        if (moveResult.success) {
          loadProject(moveResult.project);
        } else {
          loadProject(projectAfterRename);
        }
        await forceSave();
      } else {
        await forceSave();
      }

      const { getClip, trimClip } = useProjectStore.getState();
      const currentClip = getClip(clipId);
      if (currentClip) {
        const newOutPoint = currentClip.inPoint + newDuration;
        await trimClip(clipId, currentClip.inPoint, newOutPoint);
      }

      if (segmentTimes) {
        setSegmentTimes({
          start: segmentTimes.start,
          end: segmentTimes.start + newDuration,
        });
      }

      if (speakerChanged) {
        setRegenStatus(`Segmento regenerado y movido a pista "${trackName}"`);
      } else {
        setRegenStatus("Segmento regenerado");
      }
    } catch (e) {
      setRegenError(e instanceof Error ? e.message : "Error al regenerar");
    } finally {
      setRegenLoading(false);
    }
  }, [
    folderRef,
    parsed,
    clip,
    clipId,
    mediaItem,
    effectiveTimes,
    segmentText,
    normalizeTranslateLang,
    selectedVoice,
    replaceMediaAsset,
    segmentTimes,
    speed,
    speakers,
  ]);

  const handleApplySpeedFilter = useCallback(async () => {
    if (!folderRef || !parsed || !mediaItem) return;
    
    setIsApplyingSpeed(true);
    setRegenError(null);
    setRegenStatus(null);
    try {
      let effectiveSpeed = speed;
      if (speedMode === "s" && segmentTimes) {
        const currentDuration = segmentTimes.end - segmentTimes.start;
        if (currentDuration > 0) {
          effectiveSpeed = currentDuration / speed;
        }
      }

      const blob = await v2vApi.applyAudioSpeed(
        folderRef.jobId,
        folderRef.videoIndex,
        parsed.segIdx,
        effectiveSpeed
      );

      const newDuration = await getAudioDuration(blob);
      const file = new File([blob], mediaItem.name, { type: "audio/wav" });
      
      const timestamp = Date.now();
      saveToLocalStorage(mediaItem.name, {
        text: segmentText,
        speaker: selectedVoice,
        speed: effectiveSpeed,
        timestamp,
      });

      const result = await replaceMediaAsset(mediaItem.id, file);
      if (!result.success) throw new Error("Error al reemplazar audio");

      invalidateAudioCache(mediaItem.id);
      await forceSave();

      const { getClip, trimClip } = useProjectStore.getState();
      const currentClip = getClip(clipId);
      if (currentClip) {
        const newOutPoint = currentClip.inPoint + newDuration;
        await trimClip(clipId, currentClip.inPoint, newOutPoint);
      }

      if (segmentTimes) {
        setSegmentTimes({
          start: segmentTimes.start,
          end: segmentTimes.start + newDuration,
        });
      }

      setRegenStatus("Filtro de velocidad aplicado");
    } catch (e) {
      setRegenError(e instanceof Error ? e.message : "Error al aplicar filtro");
    } finally {
      setIsApplyingSpeed(false);
    }
  }, [folderRef, parsed, mediaItem, speed, speedMode, segmentText, selectedVoice, clipId, replaceMediaAsset, segmentTimes]);

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

      {/* Speed Selector */}
      <div className="space-y-2 p-3 bg-background-tertiary border border-border rounded-lg">
        <label className="text-[10px] text-text-secondary block mb-1">
          Speed
        </label>
        
        <div className="flex items-center gap-2 mb-2">
          <div className="flex bg-background-secondary border border-border rounded overflow-hidden">
            <button
              onClick={() => setSpeedMode("x")}
              className={`px-3 py-1 text-[10px] font-medium transition-colors ${
                speedMode === "x"
                  ? "bg-primary/20 text-primary"
                  : "text-text-muted hover:text-text-primary"
              }`}
            >
              x
            </button>
            <button
              onClick={() => setSpeedMode("s")}
              className={`px-3 py-1 text-[10px] font-medium transition-colors border-l border-border ${
                speedMode === "s"
                  ? "bg-primary/20 text-primary"
                  : "text-text-muted hover:text-text-primary"
              }`}
            >
              s
            </button>
          </div>
          <input
            type="number"
            min={speedMode === "x" ? 0.5 : 0.1}
            max={speedMode === "x" ? 2.0 : 60}
            step={speedMode === "x" ? 0.05 : 0.1}
            value={speed}
            onChange={(e) => setSpeed(parseFloat(e.target.value) || (speedMode === "x" ? 1.0 : 1.0))}
            className="flex-1 px-2 py-1 bg-background-secondary border border-border rounded text-[11px] text-text-primary focus:outline-none focus:border-primary"
            placeholder={speedMode === "x" ? "1.0" : "2.0"}
          />
        </div>

        <div className="flex items-center justify-between">
          <p className="text-[9px] text-text-muted">
            {speedMode === "x"
              ? `Multiplicador: ${speed}x`
              : segmentTimes
                ? `Actual: ${(segmentTimes.end - segmentTimes.start).toFixed(2)}s → Objetivo: ${speed}s`
                : "Necesita tiempos del segmento"}
          </p>
          <button
            onClick={handleApplySpeedFilter}
            disabled={isApplyingSpeed || regenLoading || speed === 1.0}
            className="px-3 py-1 bg-background-secondary border border-border rounded text-[10px] text-text-secondary hover:text-text-primary transition-all disabled:opacity-50"
            title="Aplica solo el filtro de velocidad sin regenerar TTS"
          >
            {isApplyingSpeed ? <Loader2 size={12} className="animate-spin" /> : "Aplicar"}
          </button>
        </div>
        <p className="text-[9px] text-text-muted italic">
          {speedMode === "x"
            ? "x = multiplicar velocidad (1.5x = 50% más rápido)"
            : "s = segundos objetivo (el audio durará exactamente X segundos)"}
        </p>
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
