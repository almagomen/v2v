import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@openreel/ui";

import { v2vApi, type SpeakerOption } from "../../../lib/v2v-api";
import { useProjectStore } from "../../../stores/project-store";
import { moveClipToTrack, renameMediaInLibrary } from "../../../utils/detached-project-actions";

import { useV2VStore } from "../../../stores/v2v-store";
import { invalidateAudioCache } from "../../../stores/audio-cache-store";
import { generateSegmentId } from "../../../utils/v2v-segment-ids";

type V2VParsedSegment = {
  folder: string;
  speakerToken: string;
  segIdx: number;
};

function parseV2VSegmentFromName(name: string): V2VParsedSegment | null {
  const normalized = name.replace(/\\/g, "/");

  const match = normalized.match(/^(?:(.+?)\/)?tts_(.+)_(\d{3})\.wav$/);
  if (match) {
    const folder = match[1];
    const speakerToken = match[2];
    const segIdx = parseInt(match[3], 10);
    if (folder && !Number.isNaN(segIdx)) {
      return { folder, speakerToken, segIdx };
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

  const { translateLang, speaker: defaultSpeaker, getFolderRef, getSegmentByMediaId, speakers, fetchSpeakers } = useV2VStore();

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
  
  const segmentInfo = useMemo(() => {
    if (!folderRef || !parsed || !mediaItem) return undefined;
    return getSegmentByMediaId(parsed.folder, mediaItem.id);
  }, [folderRef, parsed, mediaItem, getSegmentByMediaId]);

  const [selectedVoice, setSelectedVoice] = useState<string>("");

  function resolveSpeakerValue(token: string, speakerList: SpeakerOption[], defaultVal?: string): string {
    if (!token || speakerList.length === 0) return defaultVal || token;
    
    const byValue = speakerList.find((s) => s.value === token);
    if (byValue) return byValue.value;
    const byLabel = speakerList.find((s) => s.label === token);
    if (byLabel) return byLabel.value;

    const normalize = (str: string) => str.toLowerCase().replace(/[^a-z0-9]/g, "");
    const normToken = normalize(token);

    const byFuzzy = speakerList.find((s) => {
      const normLabel = normalize(s.label);
      const normValue = normalize(s.value);
      return (
        normLabel.includes(normToken) || normToken.includes(normLabel) ||
        normValue.includes(normToken) || normToken.includes(normValue)
      );
    });

    if (byFuzzy) return byFuzzy.value;

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
  const [speedInput, setSpeedInput] = useState<string>("");
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

  const activeTokenToResolve = useMemo(() => {
    if (!mediaItem?.name) return null;
    if (segmentInfo?.speaker) return segmentInfo.speaker;
    if (backendSpeaker) return backendSpeaker;
    if (parsed) return parsed.speakerToken;
    return null;
  }, [mediaItem?.name, parsed, backendSpeaker, segmentInfo]);

  useEffect(() => {
    if (activeTokenToResolve && speakers.length > 0) {
      setSelectedVoice(resolveSpeakerValue(activeTokenToResolve, speakers, defaultSpeaker));
    } else if (activeTokenToResolve && speakers.length === 0) {
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
        const job = await v2vApi.getJobResult(folderRef.jobId);
        if (cancelled) return;

        const video = job.videos.find((v) => v.index === folderRef.videoIndex);
        const seg = video?.segments.find((s) => s.seg === parsed.segIdx);

        const start = seg?.start ?? clip.startTime;
        const end = seg?.end ?? clip.startTime + clip.duration;

        setSegmentTimes({ start, end });
        
        if (segmentInfo?.editedText) {
          setSegmentText(segmentInfo.editedText);
        } else if (segmentInfo?.originalText) {
          setSegmentText(segmentInfo.originalText);
        } else {
          setSegmentText(seg?.text ?? "");
        }
        
        if (typeof segmentInfo?.speed === "number" && segmentInfo.speed !== 1.0) {
          setSpeed(segmentInfo.speed);
          setSpeedInput(segmentInfo.speed.toFixed(3));
        } else {
          setSpeed(1.0);
          setSpeedInput(""); // Empty input explicitly defaults to 1x or original dur
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
  }, [folderRef, parsed, clip, mediaItem, segmentInfo]);

  const effectiveTimes = useMemo(() => {
    if (segmentTimes) return segmentTimes;
    if (!clip) return null;
    return { start: clip.startTime, end: clip.startTime + clip.duration };
  }, [segmentTimes, clip]);

  const normalizeTranslateLang = useMemo(() => {
    return translateLang === "None" ? null : translateLang;
  }, [translateLang]);

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
    const segmentId = generateSegmentId(folderRef.jobId, folderRef.videoIndex, parsed.segIdx);

    let effectiveSpeed = parseFloat(speedInput) || (speedMode === "x" ? 1.0 : (effectiveTimes ? effectiveTimes.end - effectiveTimes.start : 1.0));
    let targetDuration: number | undefined;
    if (speedMode === "s" && effectiveSpeed > 0) {
      targetDuration = effectiveSpeed;
      effectiveSpeed = 1.0;
    }

    setRegenLoading(true);
    setRegenError(null);
    setRegenStatus(null);
    try {
      const regenBlob = await v2vApi.regenerateSegment(
        folderRef.jobId,
        folderRef.videoIndex,
        parsed.segIdx,
        segmentText,
        effectiveTimes.start,
        effectiveTimes.end,
        normalizeTranslateLang,
        selectedVoice,
        effectiveSpeed,
        targetDuration,
      );

      const newDuration = await getAudioDuration(regenBlob);

      const speakerChanged = oldSpeaker !== currentSpeaker;
      const filenameToken = getSpeakerFilenameToken();
      const trackName = getSpeakerTrackName();

      const newFileName = `tts_${filenameToken}_${String(parsed.segIdx).padStart(3, "0")}.wav`;
      const newMediaName = `${parsed.folder}/${newFileName}`;

      const file = new File([regenBlob], newMediaName, { type: "audio/wav" });
      
      const { updateSegmentText, updateSegmentSpeaker, updateSegmentSpeed } = useV2VStore.getState();
      updateSegmentText(parsed.folder, segmentId, currentText);
      updateSegmentSpeaker(parsed.folder, segmentId, currentSpeaker);
      updateSegmentSpeed(parsed.folder, segmentId, effectiveSpeed);

      const result = await replaceMediaAsset(mediaItem.id, file);
      if (!result.success) {
        const msg =
          typeof result.error === "string"
            ? result.error
            : result.error?.message || "Error al reemplazar audio";
        throw new Error(msg);
      }

      invalidateAudioCache(mediaItem.id);

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
        setRegenStatus(`Segmento regenerado y movido a pista "${trackName}"`);
      } else {
        setRegenStatus("Segmento regenerado");
      }
      await forceSave();
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
    speedMode,
    speakers,
  ]);

  const handleApplySpeedFilter = useCallback(async () => {
    if (!clip || !folderRef || !parsed || !mediaItem) return;
    
    setIsApplyingSpeed(true);
    setRegenError(null);
    setRegenStatus(null);
    try {
      let actualInputVal = parseFloat(speedInput) || (speedMode === "x" ? 1.0 : clip.duration);
      let effectiveSpeed = actualInputVal;
      if (speedMode === "s") {
        const currentDuration = clip.duration;
        if (currentDuration > 0 && actualInputVal > 0) {
          effectiveSpeed = currentDuration / actualInputVal;
        }
      }

      const blob = await v2vApi.applyAudioSpeed(
        folderRef.jobId,
        folderRef.videoIndex,
        parsed.segIdx,
        Number(effectiveSpeed.toFixed(3))
      );

      const newDuration = await getAudioDuration(blob);
      const file = new File([blob], mediaItem.name, { type: "audio/wav" });
      
      const segmentId = generateSegmentId(folderRef.jobId, folderRef.videoIndex, parsed.segIdx);
      const { updateSegmentSpeed } = useV2VStore.getState();
      updateSegmentSpeed(parsed.folder, segmentId, effectiveSpeed);

      const result = await replaceMediaAsset(mediaItem.id, file);
      if (!result.success) throw new Error("Error al reemplazar audio");

      invalidateAudioCache(mediaItem.id);

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

      await forceSave();
      setRegenStatus("Filtro de velocidad aplicado");
    } catch (e) {
      setRegenError(e instanceof Error ? e.message : "Error al aplicar filtro");
    } finally {
      setIsApplyingSpeed(false);
    }
  }, [folderRef, parsed, mediaItem, speed, speedInput, speedMode, segmentText, selectedVoice, clipId, replaceMediaAsset, segmentTimes]);

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

      <div className="space-y-2 p-3 bg-background-tertiary border border-border rounded-lg">
        <label className="text-[10px] text-text-secondary block mb-1">
          Speed
        </label>
        
        <div className="flex items-center gap-2 mb-2">
          <div className="flex bg-background-secondary border border-border rounded overflow-hidden">
            <button
              onClick={() => {
                setSpeedMode("x");
                setSpeedInput(String(speed));
              }}
              className={`px-3 py-1 text-[10px] font-medium transition-colors ${
                speedMode === "x"
                  ? "bg-primary/20 text-primary"
                  : "text-text-muted hover:text-text-primary"
              }`}
            >
              x
            </button>
            <button
              onClick={() => {
                setSpeedMode("s");
                setSpeedInput(String(speed));
              }}
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
            value={speedInput}
            onChange={(e) => {
              setSpeedInput(e.target.value);
            }}
            onBlur={() => {
              // Permitimos que quede vacío
              const parsed = parseFloat(speedInput);
              if (!isNaN(parsed) && parsed > 0) {
                setSpeedInput(parsed.toFixed(2));
              } else if (speedInput !== "") {
                setSpeedInput("");
              }
            }}
            className="flex-1 min-w-[60px] px-2 py-1 bg-background-secondary border border-border rounded text-[11px] text-text-primary focus:outline-none focus:border-primary placeholder:text-text-muted/40 font-medium"
            placeholder={speedMode === "x" ? "1.00" : clip.duration.toFixed(2)}
          />
          <button
            onClick={handleApplySpeedFilter}
            disabled={isApplyingSpeed || regenLoading || (!speedInput && speedMode === "x")}
            className="px-3 py-1 bg-primary/10 border border-primary/30 rounded text-[10px] text-primary hover:bg-primary/20 transition-all disabled:opacity-50 h-[24px]"
            title="Aplica solo el filtro de velocidad sin regenerar TTS"
          >
            {isApplyingSpeed ? <Loader2 size={12} className="animate-spin" /> : "Aplicar"}
          </button>
        </div>

        <div className="flex items-center justify-between">
          <p className="text-[9px] text-text-muted">
            {speedMode === "x"
              ? `Multiplicador: ${speed.toFixed(2)}x`
              : segmentTimes
                ? `Actual: ${clip.duration.toFixed(2)}s → Objetivo: ${speed.toFixed(2)}s`
                : "Necesita tiempos del segmento"}
          </p>
        </div>
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

        <button
          onClick={handleTranscribeWithBackend}
          disabled={sttLoading || regenLoading}
          className="w-full py-2 bg-background-secondary border border-border rounded-lg text-[10px] text-text-secondary hover:text-text-primary transition-colors disabled:opacity-50"
          title="Transcribe audio usando Whisper con diarización"
        >
          {sttLoading ? (
            <>
              <Loader2 size={12} className="animate-spin mr-2 inline" />
              Transcribiendo...
            </>
          ) : (
            "Whisper + diarización"
          )}
        </button>
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
