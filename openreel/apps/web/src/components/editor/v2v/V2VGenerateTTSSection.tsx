import React, { useState, useCallback, useRef, useEffect, useMemo } from "react";
import {
  Mic,
  Sparkles,
  Play,
  Square,
  Loader2,
  Plus,
  Volume2,
  SlidersHorizontal,
  ChevronDown,
  ChevronUp,
  Clock,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { Button } from "@openreel/ui";

import { v2vApi, type GeneratedAudioResult } from "../../../lib/v2v-api";
import { useV2VStore } from "../../../stores/v2v-store";
import { useProjectStore } from "../../../stores/project-store";
import { useTimelineStore } from "../../../stores/timeline-store";
import { toast } from "../../../stores/notification-store";
import { folderNameFromTitle } from "../../../utils/v2v-utils";

export const V2VGenerateTTSSection: React.FC<{ inDrawer?: boolean }> = ({
  inDrawer = false,
}) => {
  const { project, importMedia, addClip, addTrack } = useProjectStore();
  const {
    jobId,
    videos,
    selectedVideoIndex,
    speakers,
    fetchSpeakers,
    speaker: defaultSpeaker,
    getFolderRef,
    syncFolderAssets,
  } = useV2VStore();

  const playheadPosition = useTimelineStore((s) => s.playheadPosition);

  // Cargar speakers al montar si aún no se han obtenido
  useEffect(() => {
    if (speakers.length === 0) {
      fetchSpeakers();
    }
  }, [speakers.length, fetchSpeakers]);

  // Resolver el video y carpeta activos
  const effectiveDropdownValue = useMemo(() => {
    for (let i = 0; i < videos.length; i++) {
      const v = videos[i] as any;
      const projectTitle = folderNameFromTitle(v.output_name || `video_${v.index}`);
      if (project.name === projectTitle) return i;
    }
    return selectedVideoIndex >= 0 ? selectedVideoIndex : 0;
  }, [videos, project.name, selectedVideoIndex]);

  const activeVideo = videos[effectiveDropdownValue] as
    | { index: number; output_name?: string }
    | undefined;
  const activeVideoIndex = activeVideo ? activeVideo.index : 0;
  const activeFolder = activeVideo
    ? folderNameFromTitle(activeVideo.output_name || `video_${activeVideo.index}`)
    : "";

  // Estados del formulario
  const [text, setText] = useState("");
  const [selectedVoice, setSelectedVoice] = useState(defaultSpeaker || "mrbeast");
  const [speed, setSpeed] = useState(1.0);
  const [temperature, setTemperature] = useState(0.7);
  const [volume, setVolume] = useState(0.0);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Estados de generación y preview
  const [isGenerating, setIsGenerating] = useState(false);
  const [isPlayingPreview, setIsPlayingPreview] = useState(false);
  const [cachedAudio, setCachedAudio] = useState<{
    result: GeneratedAudioResult;
    text: string;
    voice: string;
    speed: number;
  } | null>(null);

  const previewAudioRef = useRef<HTMLAudioElement | null>(null);

  // Limpiar preview al desmontar
  useEffect(() => {
    return () => {
      if (previewAudioRef.current) {
        previewAudioRef.current.pause();
        previewAudioRef.current = null;
      }
    };
  }, []);

  const speakerLabel = useMemo(() => {
    return (
      speakers.find((s) => s.value === selectedVoice)?.label ||
      selectedVoice ||
      "Voz"
    );
  }, [speakers, selectedVoice]);

  // Generar audio invocando la API
  const generateAudio = useCallback(async (): Promise<GeneratedAudioResult> => {
    if (!text.trim()) {
      throw new Error("Por favor escribe un texto para generar el audio.");
    }
    if (!jobId && !activeFolder) {
      throw new Error("No hay un proyecto activo de Video2Video seleccionado.");
    }

    const res = await v2vApi.generateNewAudioSegment(
      jobId,
      activeVideoIndex,
      text.trim(),
      selectedVoice,
      {
        start: playheadPosition,
        speed,
        temperature,
        volume,
      },
    );

    setCachedAudio({
      result: res,
      text: text.trim(),
      voice: selectedVoice,
      speed,
    });

    return res;
  }, [
    text,
    jobId,
    activeFolder,
    activeVideoIndex,
    selectedVoice,
    playheadPosition,
    speed,
    temperature,
    volume,
  ]);

  // Preescucha del audio generado
  const handlePreview = useCallback(async () => {
    if (isPlayingPreview) {
      if (previewAudioRef.current) {
        previewAudioRef.current.pause();
        previewAudioRef.current.currentTime = 0;
      }
      setIsPlayingPreview(false);
      return;
    }

    try {
      setIsGenerating(true);
      let audioResult: GeneratedAudioResult;

      // Reutilizar si ya se generó exactamente lo mismo
      if (
        cachedAudio &&
        cachedAudio.text === text.trim() &&
        cachedAudio.voice === selectedVoice &&
        cachedAudio.speed === speed
      ) {
        audioResult = cachedAudio.result;
      } else {
        audioResult = await generateAudio();
      }

      if (previewAudioRef.current) {
        previewAudioRef.current.pause();
      }

      const audioUrl = URL.createObjectURL(audioResult.blob);
      const audio = new Audio(audioUrl);
      previewAudioRef.current = audio;

      audio.onended = () => {
        setIsPlayingPreview(false);
        URL.revokeObjectURL(audioUrl);
      };
      audio.onerror = () => {
        setIsPlayingPreview(false);
        URL.revokeObjectURL(audioUrl);
        toast.error("Error", "No se pudo reproducir el audio de preescucha.");
      };

      await audio.play();
      setIsPlayingPreview(true);
    } catch (err: any) {
      toast.error("Error al preescuchar", err?.message || "Ocurrió un error");
    } finally {
      setIsGenerating(false);
    }
  }, [isPlayingPreview, cachedAudio, text, selectedVoice, speed, generateAudio]);

  // Insertar en Timeline y Media Library
  const handleInsertToTimeline = useCallback(async () => {
    if (!text.trim()) {
      toast.error("Texto requerido", "Escribe una frase antes de insertarla.");
      return;
    }

    try {
      setIsGenerating(true);
      if (previewAudioRef.current) {
        previewAudioRef.current.pause();
        setIsPlayingPreview(false);
      }

      let audioResult: GeneratedAudioResult;
      if (
        cachedAudio &&
        cachedAudio.text === text.trim() &&
        cachedAudio.voice === selectedVoice &&
        cachedAudio.speed === speed
      ) {
        audioResult = cachedAudio.result;
      } else {
        audioResult = await generateAudio();
      }

      const { blob, segIdx, duration, filename } = audioResult;
      const file = new File([blob], filename, { type: "audio/wav" });

      // 1. Importar a la biblioteca de medios
      const importRes = await importMedia(file);
      if (!importRes.success || !importRes.actionId) {
        throw new Error(
          typeof importRes.error === "string"
            ? importRes.error
            : "No se pudo importar el archivo a la biblioteca de medios.",
        );
      }
      const mediaId = importRes.actionId;

      // 2. Encontrar o crear la pista de audio destino
      const currentProject = useProjectStore.getState().project;
      const audioTracks = currentProject.timeline.tracks.filter(
        (t) => t.type === "audio",
      );

      const startTime = Math.max(0, playheadPosition);
      const endTime = startTime + duration;

      // Buscar si existe pista con el nombre del speaker
      let targetTrack = audioTracks.find((t) =>
        (t as any).name?.toLowerCase().includes(speakerLabel.toLowerCase()),
      );

      // Si no existe o tiene colisión en ese timestamp, buscar cualquier pista de audio libre
      if (!targetTrack || hasCollision(targetTrack, startTime, endTime)) {
        const freeTrack = audioTracks.find(
          (t) => !hasCollision(t, startTime, endTime),
        );
        if (freeTrack) {
          targetTrack = freeTrack;
        } else {
          // Crear una nueva pista de audio dedicada
          const addTrackRes = await addTrack("audio", undefined, {
            name: speakerLabel,
          });
          if (addTrackRes.success) {
            const updated = useProjectStore.getState().project.timeline.tracks;
            targetTrack = updated.filter((t) => t.type === "audio").pop();
          }
        }
      }

      if (!targetTrack) {
        throw new Error("No se pudo asignar una pista de audio en el Timeline.");
      }

      // 3. Añadir el clip al Timeline
      await addClip(targetTrack.id, mediaId, startTime);

      // 4. Sincronizar el archivo con Colab para renderizado de fondo
      if (jobId) {
        try {
          await v2vApi.uploadMediaForRender(jobId, activeVideoIndex, file);
          if (activeFolder) {
            await syncFolderAssets(jobId, activeVideoIndex, activeFolder);
          }
        } catch (syncErr) {
          console.warn("[V2V] Error sincronizando asset en servidor:", syncErr);
        }
      }

      // 5. Notificar éxito e invalidar caché visual de waveforms
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("openreel:preview-invalidate", {
            detail: { mediaId },
          }),
        );
      }

      toast.success(
        "Segmento insertado",
        `Segmento #${segIdx} añadido al timeline en ${startTime.toFixed(2)}s (${duration.toFixed(1)}s)`,
      );

      // Limpiar texto para el siguiente segmento
      setText("");
      setCachedAudio(null);
    } catch (err: any) {
      toast.error(
        "Error al insertar",
        err?.message || "No se pudo insertar el segmento en el Timeline.",
      );
    } finally {
      setIsGenerating(false);
    }
  }, [
    text,
    cachedAudio,
    selectedVoice,
    speed,
    generateAudio,
    importMedia,
    playheadPosition,
    speakerLabel,
    addTrack,
    addClip,
    jobId,
    activeVideoIndex,
    activeFolder,
    syncFolderAssets,
  ]);

  return (
    <div className="bg-bg-2/70 border border-border/80 rounded-xl p-4 space-y-3.5 shadow-sm">
      {/* Cabecera */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-red-500/15 text-red-500 flex items-center justify-center">
            <Mic size={16} />
          </div>
          <div>
            <h4 className="text-xs font-bold text-fg flex items-center gap-1.5">
              Generar Segmento TTS
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
                IA N+1
              </span>
            </h4>
            <p className="text-[11px] text-fg-3">
              Crea una locución a partir de texto y colócala en el Timeline
            </p>
          </div>
        </div>
      </div>

      {/* Selector de Voz */}
      <div className="space-y-1">
        <label className="text-[11px] font-semibold text-fg-2 flex items-center justify-between">
          <span>Voz / Hablante</span>
          <span className="text-[10px] text-fg-3 font-normal">
            {speakers.length} disponibles
          </span>
        </label>
        <select
          value={selectedVoice}
          onChange={(e) => setSelectedVoice(e.target.value)}
          className="w-full h-8 px-2.5 text-xs bg-bg-1 border border-border rounded-lg text-fg focus:outline-none focus:ring-1 focus:ring-primary"
        >
          {speakers.length > 0 ? (
            speakers.map((s) => (
              <option key={s.value || s.label} value={s.value || s.label}>
                {s.label}
              </option>
            ))
          ) : (
            <>
              <option value="mrbeast">mrbeast</option>
              <option value="default_fish">default_fish</option>
            </>
          )}
        </select>
      </div>

      {/* Área de texto */}
      <div className="space-y-1">
        <label className="text-[11px] font-semibold text-fg-2">
          Texto a sintetizar
        </label>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Escribe el diálogo o locución que deseas generar..."
          rows={3}
          className="w-full text-xs p-2.5 rounded-lg bg-bg-1 border border-border text-fg placeholder:text-fg-4 focus:outline-none focus:ring-1 focus:ring-primary resize-none transition-colors"
        />
      </div>

      {/* Indicador de posición de inserción */}
      <div className="flex items-center justify-between px-2.5 py-1.5 rounded-md bg-bg-3/50 text-[11px] text-fg-3 border border-border/40">
        <span className="flex items-center gap-1">
          <Clock size={12} className="text-primary" /> Posición en Timeline:
        </span>
        <span className="font-mono font-semibold text-fg">
          {formatTime(playheadPosition)} ({playheadPosition.toFixed(2)}s)
        </span>
      </div>

      {/* Controles avanzados desplegables */}
      <div className="border-t border-border/50 pt-2">
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="w-full flex items-center justify-between text-[11px] text-fg-3 hover:text-fg py-1 transition-colors"
        >
          <span className="flex items-center gap-1.5 font-medium">
            <SlidersHorizontal size={12} />
            Ajustes avanzados ({speed.toFixed(1)}x)
          </span>
          {showAdvanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>

        {showAdvanced && (
          <div className="pt-2 pb-1 space-y-3 animate-in fade-in duration-150">
            {/* Velocidad */}
            <div className="space-y-1">
              <div className="flex justify-between text-[10px] text-fg-3">
                <span>Velocidad de habla</span>
                <span className="font-mono">{speed.toFixed(2)}x</span>
              </div>
              <input
                type="range"
                min="0.5"
                max="2.0"
                step="0.05"
                value={speed}
                onChange={(e) => setSpeed(parseFloat(e.target.value))}
                className="w-full accent-primary h-1 bg-border rounded-lg cursor-pointer"
              />
            </div>

            {/* Expresividad (Temperatura) */}
            <div className="space-y-1">
              <div className="flex justify-between text-[10px] text-fg-3">
                <span>Expresividad (Temp)</span>
                <span className="font-mono">{temperature.toFixed(2)}</span>
              </div>
              <input
                type="range"
                min="0.2"
                max="1.0"
                step="0.05"
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value))}
                className="w-full accent-primary h-1 bg-border rounded-lg cursor-pointer"
              />
            </div>

            {/* Volumen */}
            <div className="space-y-1">
              <div className="flex justify-between text-[10px] text-fg-3">
                <span>Ganancia de volumen</span>
                <span className="font-mono">{volume > 0 ? `+${volume} dB` : `${volume} dB`}</span>
              </div>
              <input
                type="range"
                min="-6.0"
                max="6.0"
                step="0.5"
                value={volume}
                onChange={(e) => setVolume(parseFloat(e.target.value))}
                className="w-full accent-primary h-1 bg-border rounded-lg cursor-pointer"
              />
            </div>
          </div>
        )}
      </div>

      {/* Botones de acción */}
      <div className="flex items-center gap-2 pt-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handlePreview}
          disabled={isGenerating || !text.trim()}
          className="flex-1 text-xs h-8 gap-1.5 border-border bg-bg-1 hover:bg-bg-3"
          title="Escuchar cómo suena antes de insertarlo en el timeline"
        >
          {isGenerating ? (
            <Loader2 size={13} className="animate-spin text-primary" />
          ) : isPlayingPreview ? (
            <Square size={13} className="text-red-500 fill-red-500" />
          ) : (
            <Play size={13} className="text-fg-2" />
          )}
          <span>{isPlayingPreview ? "Detener" : "Preescuchar"}</span>
        </Button>

        <Button
          type="button"
          size="sm"
          onClick={handleInsertToTimeline}
          disabled={isGenerating || !text.trim()}
          className="flex-1 text-xs h-8 gap-1.5 bg-primary hover:bg-primary/90 text-primary-foreground font-semibold shadow"
        >
          {isGenerating ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Plus size={14} />
          )}
          <span>Insertar al Timeline</span>
        </Button>
      </div>
    </div>
  );
};

function hasCollision(track: any, start: number, end: number): boolean {
  if (!track || !track.clips || !Array.isArray(track.clips)) return false;
  return track.clips.some((clip: any) => {
    const cStart = clip.startTime;
    const cEnd = clip.startTime + (clip.duration || 0);
    // Hay solapamiento si los rangos se intersecan
    return !(end <= cStart || start >= cEnd);
  });
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 10);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${ms}`;
}
