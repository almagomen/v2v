import React, { useState, useCallback, useRef, useEffect, useMemo } from "react";
import {
  Mic,
  Sparkles,
  Play,
  Square,
  Loader2,
  Plus,
  RefreshCw,
  Clock,
  ListChecks,
  X,
  SlidersHorizontal,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { Button } from "@openreel/ui";

import { v2vApi, type GeneratedAudioResult } from "../../../lib/v2v-api";
import { useV2VStore } from "../../../stores/v2v-store";
import { useProjectStore } from "../../../stores/project-store";
import { useTimelineStore } from "../../../stores/timeline-store";
import { useUIStore } from "../../../stores/ui-store";
import { toast } from "../../../stores/notification-store";
import { folderNameFromTitle, parseV2VSegmentFromName, toSafeToken } from "../../../utils/v2v-utils";
import { applyRegeneratedSegmentToTimeline } from "../../../utils/v2v-segment-regen";
import {
  V2V_EMOTIONS,
  EMOTION_CATEGORIES,
  getEmotionsByCategory,
  formatEmotionLabel,
} from "../../../utils/v2v-emotions";

export const V2VGenerateTTSSection: React.FC<{ inDrawer?: boolean }> = ({
  inDrawer = false,
}) => {
  const { project, importMedia, addClip, addTrack, getClip, getMediaItem } = useProjectStore();
  const {
    jobId,
    videos,
    selectedVideoIndex,
    speakers,
    fetchSpeakers,
    speaker: defaultSpeaker,
    getFolderRef,
    syncFolderAssets,
    setBulkEditorOpen,
    setIsV2VOpen,
    getSegmentByMediaId,
  } = useV2VStore();

  const playheadPosition = useTimelineStore((s) => s.playheadPosition);
  const selectedItems = useUIStore((s) => s.selectedItems);
  const clearSelection = useUIStore((s) => s.clearSelection);

  // Cargar lista de speakers al montar
  useEffect(() => {
    if (speakers.length === 0) {
      fetchSpeakers();
    }
  }, [speakers.length, fetchSpeakers]);

  // Resolver video y carpeta activos
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

  // Detección robusta de clip seleccionado en el Timeline para modo "Edición Individual"
  const selectedClipItem = selectedItems?.find(
    (it) => it.type === "clip" || (it as any).type === "audio-clip"
  ) ?? selectedItems?.[0];
  const selectedClipId = selectedClipItem
    ? (typeof selectedClipItem === "string" ? selectedClipItem : selectedClipItem.id)
    : null;
  const selectedClip = selectedClipId ? getClip(selectedClipId) : null;
  const selectedMediaItem = selectedClip ? getMediaItem(selectedClip.mediaId) : null;

  const clipCandidateName = selectedMediaItem?.name || (selectedClip as any)?.name || (selectedClip as any)?.label || "";

  const parsedSelectedSegment = useMemo(() => {
    if (!clipCandidateName) return null;
    return parseV2VSegmentFromName(clipCandidateName);
  }, [clipCandidateName]);

  const isEditingExistingSegment = Boolean(parsedSelectedSegment && selectedClip);

  // Referencia al textarea para insertar emociones en la posición del cursor
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Estados del formulario
  const [text, setText] = useState("");
  const [selectedVoice, setSelectedVoice] = useState(defaultSpeaker || "mrbeast");
  const [temperature, setTemperature] = useState(0.7);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Estados para ajuste de velocidad sin regenerar TTS
  const [speedMode, setSpeedMode] = useState<"x" | "s">("x");
  const [speedInput, setSpeedInput] = useState<string>("1.000");
  const [isApplyingSpeed, setIsApplyingSpeed] = useState<boolean>(false);

  // Estados de proceso y preescucha
  const [isProcessing, setIsProcessing] = useState(false);
  const [isPlayingPreview, setIsPlayingPreview] = useState(false);
  const [cachedAudio, setCachedAudio] = useState<{
    result: GeneratedAudioResult;
    finalText: string;
    voice: string;
  } | null>(null);

  const previewAudioRef = useRef<HTMLAudioElement | null>(null);

  // Inserción de emoción en la posición de la barra de texto / cursor
  const insertEmotionAtCursor = useCallback((tag: string) => {
    if (!tag || tag === "none") return;
    const formattedTag = tag.startsWith("[") ? tag : `[${tag}]`;
    const el = textareaRef.current;
    if (!el) {
      setText((prev) => (prev ? `${prev} ${formattedTag}` : formattedTag));
      return;
    }
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    const current = text;
    const inserted = current.substring(0, start) + `${formattedTag} ` + current.substring(end);
    setText(inserted);
    setTimeout(() => {
      el.focus();
      const pos = start + formattedTag.length + 1;
      el.setSelectionRange(pos, pos);
    }, 0);
  }, [text]);

  // Sincronizar campos cuando cambia el clip seleccionado en la Timeline
  useEffect(() => {
    if (parsedSelectedSegment && selectedClip) {
      let rawText = "";

      // 1. Buscar en folderRefs
      const folderRef = getFolderRef(activeFolder);
      if (folderRef) {
        if (selectedMediaItem?.id) {
          const segInfo = getSegmentByMediaId(activeFolder, selectedMediaItem.id);
          if (segInfo?.editedText || segInfo?.originalText) {
            rawText = segInfo.editedText || segInfo.originalText || "";
          }
        }
        if (!rawText && folderRef.segments) {
          const segByNumber = Object.values(folderRef.segments).find(
            (s: any) => s.segIdx === parsedSelectedSegment.segIdx
          );
          if (segByNumber?.editedText || segByNumber?.originalText) {
            rawText = segByNumber.editedText || segByNumber.originalText || "";
          }
        }
      }

      // 2. Buscar en activeVideo.segments
      if (!rawText && activeVideo && (activeVideo as any).segments) {
        const vSeg = (activeVideo as any).segments.find(
          (s: any) => s.seg === parsedSelectedSegment.segIdx
        );
        if (vSeg?.text) rawText = vSeg.text;
      }

      // 3. Buscar en todos los videos del store
      if (!rawText && videos && videos.length > 0) {
        for (const v of videos) {
          const s = (v as any).segments?.find(
            (seg: any) => seg.seg === parsedSelectedSegment.segIdx
          );
          if (s?.text) {
            rawText = s.text;
            break;
          }
        }
      }

      // 4. Buscar en useV2VStore.getState().segments
      if (!rawText) {
        const globalSegs = (useV2VStore.getState() as any).segments || [];
        const s = globalSegs.find((seg: any) => seg.seg === parsedSelectedSegment.segIdx);
        if (s?.text) rawText = s.text;
      }

      // 5. Fallback asíncrono desde el endpoint de segmentos si aún no está en memoria
      if (!rawText && jobId) {
        v2vApi.getSegmentsEditor(jobId, activeVideoIndex).then((res) => {
          const row = res.segments?.find((r) => r.seg === parsedSelectedSegment.segIdx);
          if (row) {
            const t = row.tts_text || row.original_text || "";
            if (t) setText(t);
          }
        }).catch(() => { });
      }

      setText(rawText);

      // Obtener voz del segmento existente
      if (parsedSelectedSegment.speakerToken) {
        const matchingSpeaker = speakers.find(
          (s) =>
            s.value === parsedSelectedSegment.speakerToken ||
            s.label.toLowerCase() === parsedSelectedSegment.speakerToken.toLowerCase(),
        );
        if (matchingSpeaker) {
          setSelectedVoice(matchingSpeaker.value || matchingSpeaker.label);
        }
      }

      // Inicializar control de velocidad con la duración actual del clip
      setSpeedMode("x");
      setSpeedInput("1.000");
      setCachedAudio(null);
    }
  }, [
    parsedSelectedSegment?.segIdx,
    parsedSelectedSegment?.speakerToken,
    selectedClip?.id,
    selectedMediaItem?.id,
    activeFolder,
    activeVideoIndex,
    jobId,
    speakers,
    getFolderRef,
    getSegmentByMediaId,
    activeVideo,
    videos,
  ]);

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

  // El texto final es el editado directamente por el usuario (con emociones donde las ubicó)
  const computeFinalText = useCallback(() => {
    return text.trim();
  }, [text]);

  // Preescucha de audio
  const handlePreview = useCallback(async () => {
    if (isPlayingPreview) {
      if (previewAudioRef.current) {
        previewAudioRef.current.pause();
        previewAudioRef.current.currentTime = 0;
      }
      setIsPlayingPreview(false);
      return;
    }

    const finalText = computeFinalText();
    if (!finalText.trim()) {
      toast.error("Texto requerido", "Escribe una frase para preescuchar.");
      return;
    }

    try {
      setIsProcessing(true);
      let audioResult: GeneratedAudioResult;

      if (
        cachedAudio &&
        cachedAudio.finalText === finalText &&
        cachedAudio.voice === selectedVoice
      ) {
        audioResult = cachedAudio.result;
      } else {
        audioResult = await v2vApi.generateNewAudioSegment(
          jobId,
          activeVideoIndex,
          finalText,
          selectedVoice,
          {
            start: isEditingExistingSegment && selectedClip ? selectedClip.startTime : playheadPosition,
            temperature,
          },
        );
        setCachedAudio({
          result: audioResult,
          finalText,
          voice: selectedVoice,
        });
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
        toast.error("Error", "No se pudo reproducir la preescucha.");
      };

      await audio.play();
      setIsPlayingPreview(true);
    } catch (err: any) {
      toast.error("Error al preescuchar", err?.message || "Ocurrió un error");
    } finally {
      setIsProcessing(false);
    }
  }, [
    isPlayingPreview,
    computeFinalText,
    cachedAudio,
    selectedVoice,
    jobId,
    activeVideoIndex,
    isEditingExistingSegment,
    selectedClip,
    playheadPosition,
    temperature,
  ]);

  // Acción: Ajustar solo velocidad al clip existente sin regenerar TTS
  const handleApplySpeedOnly = useCallback(async () => {
    if (!isEditingExistingSegment || !parsedSelectedSegment || !selectedClip || !selectedMediaItem) {
      toast.error("Selección requerida", "Debes tener seleccionado un segmento del timeline.");
      return;
    }

    setIsApplyingSpeed(true);
    let effectiveSpeed = parseFloat(speedInput) || 1.0;
    let targetDuration: number | undefined;
    if (speedMode === "s" && effectiveSpeed > 0) {
      targetDuration = effectiveSpeed;
      effectiveSpeed = 1.0;
    }

    try {
      const regenBlob = await v2vApi.applyAudioSpeed(
        jobId,
        activeVideoIndex,
        parsedSelectedSegment.segIdx,
        speedMode === "x" ? effectiveSpeed : null,
        targetDuration,
      );

      const speedForStore = speedMode === "x" ? effectiveSpeed : 1.0;

      const result = await applyRegeneratedSegmentToTimeline({
        folder: activeFolder,
        jobId,
        videoIndex: activeVideoIndex,
        segIdx: parsedSelectedSegment.segIdx,
        regenBlob,
        text: text.trim(),
        speaker: selectedVoice,
        speakerLabel,
        previousSpeakerToken: parsedSelectedSegment.speakerToken,
        start: selectedClip.startTime,
        end: selectedClip.startTime + selectedClip.duration,
        effectiveSpeed: speedForStore,
        mediaId: selectedMediaItem.id,
        clipId: selectedClip.id,
        trackStart: selectedClip.startTime,
      });

      if (!result.success) {
        throw new Error(result.message || "No se pudo actualizar el timeline");
      }

      toast.success("Velocidad aplicada", "Se ajustó el segmento sin regenerar voz.");
    } catch (e: any) {
      toast.error("Error al aplicar velocidad", e?.message || String(e));
    } finally {
      setIsApplyingSpeed(false);
    }
  }, [
    isEditingExistingSegment,
    parsedSelectedSegment,
    selectedClip,
    selectedMediaItem,
    speedInput,
    speedMode,
    jobId,
    activeVideoIndex,
    activeFolder,
    text,
    selectedVoice,
    speakerLabel,
  ]);

  // Ejecutar Acción Principal (Regenerar segmento existente O Generar nuevo N+1)
  const handleMainAction = useCallback(async () => {
    const finalText = computeFinalText();
    if (!finalText.trim()) {
      toast.error("Texto requerido", "Por favor escribe un texto para sintetizar.");
      return;
    }

    setIsProcessing(true);
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      setIsPlayingPreview(false);
    }

    try {
      if (isEditingExistingSegment && parsedSelectedSegment && selectedClip && selectedMediaItem) {
        // --- MODO EDICIÓN INDIVIDUAL DE SEGMENTO EXISTENTE ---
        const start = selectedClip.startTime;
        const end = selectedClip.startTime + selectedClip.duration;

        let effectiveSpeed = 1.0;
        let targetDuration: number | undefined = undefined;

        if (speedMode === "x") {
          const parsed = parseFloat(speedInput);
          effectiveSpeed = !isNaN(parsed) && parsed > 0 ? parsed : 1.0;
          targetDuration = undefined;
        } else {
          const parsed = parseFloat(speedInput);
          targetDuration = !isNaN(parsed) && parsed > 0 ? parsed : selectedClip.duration;
          effectiveSpeed = 1.0;
        }

        const regenBlob = await v2vApi.regenerateSegment(
          jobId,
          activeVideoIndex,
          parsedSelectedSegment.segIdx,
          finalText,
          start,
          end,
          null,
          selectedVoice,
          effectiveSpeed,
          targetDuration,
          { temperature },
        );

        const result = await applyRegeneratedSegmentToTimeline({
          folder: activeFolder,
          jobId,
          videoIndex: activeVideoIndex,
          segIdx: parsedSelectedSegment.segIdx,
          regenBlob,
          text: finalText,
          speaker: selectedVoice,
          speakerLabel,
          previousSpeakerToken: parsedSelectedSegment.speakerToken,
          start,
          end,
          effectiveSpeed: speedMode === "x" ? effectiveSpeed : 1.0,
          mediaId: selectedMediaItem.id,
          clipId: selectedClip.id,
          trackStart: selectedClip.startTime,
        });

        if (result.success) {
          toast.success("Segmento regenerado", result.message);
          setCachedAudio(null);
        } else {
          throw new Error(result.message);
        }
      } else {
        // --- MODO NUEVO SEGMENTO TTS (N+1) AL PLAYHEAD ---
        let audioResult: GeneratedAudioResult;
        if (
          cachedAudio &&
          cachedAudio.finalText === finalText &&
          cachedAudio.voice === selectedVoice
        ) {
          audioResult = cachedAudio.result;
        } else {
          audioResult = await v2vApi.generateNewAudioSegment(
            jobId,
            activeVideoIndex,
            finalText,
            selectedVoice,
            {
              start: playheadPosition,
              temperature,
            },
          );
        }

        const { blob, segIdx, duration, filename } = audioResult;
        const file = new File([blob], filename, { type: "audio/wav" });

        // 1. Importar a la Media Library
        const importRes = await importMedia(file);
        if (!importRes.success || !importRes.actionId) {
          throw new Error(
            typeof importRes.error === "string"
              ? importRes.error
              : "No se pudo importar el archivo a la biblioteca de medios.",
          );
        }
        const mediaId = importRes.actionId;

        // 2. Asignar pista de audio
        const currentProject = useProjectStore.getState().project;
        const audioTracks = currentProject.timeline.tracks.filter((t) => t.type === "audio");
        const startTime = Math.max(0, playheadPosition);
        const endTime = startTime + duration;

        let targetTrack = audioTracks.find((t) =>
          (t as any).name?.toLowerCase().includes(speakerLabel.toLowerCase()),
        );

        if (!targetTrack || hasCollision(targetTrack, startTime, endTime)) {
          const freeTrack = audioTracks.find((t) => !hasCollision(t, startTime, endTime));
          if (freeTrack) {
            targetTrack = freeTrack;
          } else {
            const addTrackRes = await addTrack("audio", undefined, { name: speakerLabel });
            if (addTrackRes.success) {
              const updated = useProjectStore.getState().project.timeline.tracks;
              targetTrack = updated.filter((t) => t.type === "audio").pop();
            }
          }
        }

        if (!targetTrack) {
          throw new Error("No se pudo asignar una pista de audio en el Timeline.");
        }

        // 3. Añadir clip a la Timeline
        await addClip(targetTrack.id, mediaId, startTime);

        // 4. Sincronizar en background con servidor Colab
        if (jobId) {
          try {
            await v2vApi.uploadMediaForRender(jobId, activeVideoIndex, file);
            if (activeFolder) {
              await syncFolderAssets(jobId, activeVideoIndex, activeFolder);
            }
          } catch (syncErr) {
            console.warn("[V2V] Error sincronizando asset:", syncErr);
          }
        }

        // 5. Notificar éxito e invalidar caché
        if (typeof window !== "undefined") {
          window.dispatchEvent(
            new CustomEvent("openreel:preview-invalidate", { detail: { mediaId } }),
          );
        }

        toast.success(
          "Segmento insertado",
          `Segmento #${segIdx} añadido al timeline en ${startTime.toFixed(2)}s (${duration.toFixed(1)}s)`,
        );

        setText("");
        setCachedAudio(null);
      }
    } catch (err: any) {
      toast.error(
        isEditingExistingSegment ? "Error al regenerar" : "Error al insertar",
        err?.message || "Ocurrió un error en el proceso.",
      );
    } finally {
      setIsProcessing(false);
    }
  }, [
    computeFinalText,
    isEditingExistingSegment,
    parsedSelectedSegment,
    selectedClip,
    selectedMediaItem,
    jobId,
    activeVideoIndex,
    selectedVoice,
    temperature,
    speedMode,
    speedInput,
    cachedAudio,
    playheadPosition,
    importMedia,
    addTrack,
    addClip,
    syncFolderAssets,
  ]);

  return (
    <div className="bg-bg-2/70 border border-border/80 rounded-xl p-3.5 space-y-3 shadow-sm">
      {/* Cabecera integrada */}
      <div className="flex items-center justify-between border-b border-border/50 pb-2.5">
        <div className="flex items-center gap-2">
          <div
            className={`w-7 h-7 rounded-lg flex items-center justify-center ${isEditingExistingSegment
                ? "bg-amber-500/15 text-amber-500"
                : "bg-red-500/15 text-red-500"
              }`}
          >
            {isEditingExistingSegment ? <RefreshCw size={15} /> : <Mic size={15} />}
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <h4 className="text-xs font-bold text-fg">
                {isEditingExistingSegment
                  ? `Editar Segmento #${parsedSelectedSegment?.segIdx}`
                  : "Generador de Voz TTS"}
              </h4>
              <span
                className={`text-[9px] font-medium px-1.5 py-0.2 rounded border ${isEditingExistingSegment
                    ? "bg-amber-500/10 text-amber-500 border-amber-500/20"
                    : "bg-primary/10 text-primary border-primary/20"
                  }`}
              >
                {isEditingExistingSegment ? "Clip Seleccionado" : "IA N+1"}
              </span>
            </div>
            <p className="text-[10px] text-fg-3">
              {isEditingExistingSegment
                ? "Modifica el texto o voz del segmento seleccionado en Timeline"
                : "Crea una locución a partir de texto y colócala en el Timeline"}
            </p>
          </div>
        </div>

        {/* Botón de volver a modo Nuevo si está editando un clip */}
        {isEditingExistingSegment && (
          <button
            type="button"
            onClick={() => {
              clearSelection();
              setText("");
              setCachedAudio(null);
            }}
            className="text-[10px] flex items-center gap-1 text-fg-3 hover:text-fg px-1.5 py-1 rounded hover:bg-hover transition-colors"
            title="Deseleccionar clip y crear un nuevo segmento"
          >
            <X size={12} />
            <span>Nuevo</span>
          </button>
        )}
      </div>

      {/* Selectores en fila: Voz / Hablante y Emoción */}
      <div className="grid grid-cols-2 gap-2">
        {/* Selector de Voz */}
        <div className="space-y-1">
          <label className="text-[10px] font-semibold text-fg-2 block">
            Voz / Hablante
          </label>
          <select
            value={selectedVoice}
            onChange={(e) => setSelectedVoice(e.target.value)}
            className="w-full h-8 px-2 text-xs bg-bg-1 border border-border rounded-lg text-fg focus:outline-none focus:ring-1 focus:ring-primary truncate"
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

        {/* Selector de Emoción (inserta en el cursor) */}
        <div className="space-y-1">
          <label className="text-[10px] font-semibold text-fg-2 flex items-center justify-between">
            <span>Insertar Emoción</span>
            <span className="text-[9px] text-primary font-medium">S2.1</span>
          </label>
          <select
            value=""
            onChange={(e) => insertEmotionAtCursor(e.target.value)}
            className="w-full h-8 px-2 text-xs bg-bg-1 border border-border rounded-lg text-fg focus:outline-none focus:ring-1 focus:ring-primary truncate cursor-pointer"
            title="Selecciona una emoción para insertarla donde esté la barra de texto"
          >
            <option value="" disabled>✨ Insertar emoción...</option>
            {EMOTION_CATEGORIES.map((cat) => (
              <optgroup key={cat.name} label={`${cat.emoji} ${cat.label}`}>
                {getEmotionsByCategory(cat.name).map((em) => (
                  <option key={em.tag} value={em.tag}>
                    {formatEmotionLabel(em)}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
      </div>

      {/* Área de texto */}
      <div className="space-y-1">
        <label className="text-[10px] font-semibold text-fg-2 block">
          Texto del segmento
        </label>
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={
            isEditingExistingSegment
              ? "Edita el diálogo del segmento..."
              : "Escribe el diálogo o locución que deseas generar..."
          }
          rows={3}
          className="w-full text-xs p-2.5 rounded-lg bg-bg-1 border border-border text-fg placeholder:text-fg-4 focus:outline-none focus:ring-1 focus:ring-primary resize-none transition-colors"
        />
      </div>

      {/* Indicador de posición en Timeline */}
      <div className="flex items-center justify-between px-2.5 py-1.5 rounded-md bg-bg-3/50 text-[11px] text-fg-3 border border-border/40">
        <span className="flex items-center gap-1 text-[10px]">
          <Clock size={11} className="text-primary" />{" "}
          {isEditingExistingSegment ? "Inicio segmento:" : "Posición Playhead:"}
        </span>
        <span className="font-mono font-semibold text-fg text-[11px]">
          {isEditingExistingSegment && selectedClip
            ? `${selectedClip.startTime.toFixed(2)}s (dur: ${selectedClip.duration.toFixed(2)}s)`
            : `${playheadPosition.toFixed(2)}s`}
        </span>
      </div>

      {/* Fila: Ajustes avanzados + Botón Editor en Lote */}
      <div className="border-t border-border/50 pt-2 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-1.5 text-[11px] text-fg-3 hover:text-fg py-1 transition-colors cursor-pointer"
        >
          <SlidersHorizontal size={12} />
          <span className="font-medium">Ajustes avanzados</span>
          {showAdvanced ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>

        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="text-[10px] h-7 px-2.5 gap-1.5 text-fg-2 hover:text-fg bg-bg-3/80 hover:bg-bg-3 border border-border/60 cursor-pointer"
          onClick={() => {
            setBulkEditorOpen(true);
            setIsV2VOpen(false);
          }}
          title="Abrir la ventana de edición masiva de todos los segmentos del video"
        >
          <ListChecks size={13} className="text-primary" />
          <span>Editor en Lote</span>
        </Button>
      </div>

      {showAdvanced && (
        <div className="pb-1 space-y-2.5 animate-in fade-in duration-150">
          {/* Control de velocidad (solo al abrir ajustes avanzados con segmento existente) */}
          {isEditingExistingSegment && (
            <div className="p-2 rounded-lg bg-bg-1 border border-border/70 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-fg-3 font-medium">Velocidad:</span>
                <span className="text-[9px] text-fg-4 font-mono">
                  {selectedClip ? `actual: ${selectedClip.duration.toFixed(2)}s` : ""}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <select
                  value={speedMode}
                  onChange={(e) => {
                    const isS = e.target.value === "s";
                    setSpeedMode(isS ? "s" : "x");
                    if (selectedClip) {
                      setSpeedInput(isS ? selectedClip.duration.toFixed(3) : "1.000");
                    }
                  }}
                  className="h-7 w-12 text-[10px] px-1 bg-bg-2 border border-border rounded text-fg focus:outline-none focus:ring-1 focus:ring-primary font-mono cursor-pointer shrink-0"
                >
                  <option value="x">×</option>
                  <option value="s">s</option>
                </select>
                {speedMode === "x" ? (
                  <div className="flex items-center gap-1.5 flex-1 min-w-0">
                    <input
                      type="range"
                      min="0.5"
                      max="2.0"
                      step="0.05"
                      value={parseFloat(speedInput) || 1.0}
                      onChange={(e) => setSpeedInput(parseFloat(e.target.value).toFixed(2))}
                      className="w-20 accent-primary h-1 bg-border rounded cursor-pointer"
                      title="Deslizar para ajustar velocidad del segmento sintetizado (0.5x – 2.0x)"
                    />
                    <input
                      type="text"
                      className="w-14 h-7 text-[10px] px-1 text-center rounded border border-border bg-bg-2 font-mono text-fg focus:outline-none focus:ring-1 focus:ring-primary"
                      placeholder="1.00"
                      value={speedInput}
                      onChange={(e) => setSpeedInput(e.target.value)}
                      title="Multiplicador de velocidad"
                    />
                  </div>
                ) : (
                  <input
                    type="text"
                    className="w-20 h-7 text-[10px] px-2 rounded border border-border bg-bg-2 font-mono text-fg focus:outline-none focus:ring-1 focus:ring-primary"
                    placeholder={selectedClip?.duration.toFixed(2) || "1.0"}
                    value={speedInput}
                    onChange={(e) => setSpeedInput(e.target.value)}
                    title="Duración exacta en segundos"
                  />
                )}
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="text-[9px] h-7 px-2.5 ml-auto shrink-0 bg-bg-3 hover:bg-bg-2 text-fg border border-border"
                  disabled={isProcessing || isApplyingSpeed}
                  onClick={handleApplySpeedOnly}
                  title="Aplica la velocidad sin volver a generar audio con la IA"
                >
                  {isApplyingSpeed ? <Loader2 size={11} className="animate-spin mr-1" /> : null}
                  Ajustar
                </Button>
              </div>
            </div>
          )}

          <div className="space-y-1.5">
            <div className="flex justify-between text-[10px] text-fg-3">
              <span>Expresividad / Temperatura</span>
              <span className="font-mono text-fg font-semibold">{temperature.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min="0.1"
              max="1.0"
              step="0.05"
              value={temperature}
              onChange={(e) => setTemperature(parseFloat(e.target.value))}
              className="w-full accent-primary h-1 bg-border rounded-lg cursor-pointer"
            />
            <div className="flex justify-between text-[8px] text-fg-4">
              <span>Más consistente (0.1)</span>
              <span>Más variado / expresivo (1.0)</span>
            </div>
          </div>
        </div>
      )}

      {/* Botones de acción */}
      <div className="flex items-center gap-2 pt-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handlePreview}
          disabled={isProcessing || !text.trim()}
          className="flex-1 text-xs h-8 gap-1.5 border-border bg-bg-1 hover:bg-bg-3"
          title="Escuchar cómo suena antes de insertarlo en el timeline"
        >
          {isProcessing ? (
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
          onClick={handleMainAction}
          disabled={isProcessing || !text.trim()}
          className={`flex-1 text-xs h-8 gap-1.5 font-semibold shadow ${isEditingExistingSegment
              ? "bg-amber-500 hover:bg-amber-600 text-white"
              : "bg-primary hover:bg-primary/90 text-primary-foreground"
            }`}
        >
          {isProcessing ? (
            <Loader2 size={14} className="animate-spin" />
          ) : isEditingExistingSegment ? (
            <RefreshCw size={13} />
          ) : (
            <Plus size={14} />
          )}
          <span>
            {isEditingExistingSegment
              ? `Regenerar #${parsedSelectedSegment?.segIdx}`
              : "Insertar al Timeline"}
          </span>
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
    return !(end <= cStart || start >= cEnd);
  });
}
