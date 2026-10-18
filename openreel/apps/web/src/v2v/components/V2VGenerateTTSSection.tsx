import React, { useState, useCallback, useRef, useEffect, useMemo } from "react";
import {
  Plus,
  RefreshCw,
} from "lucide-react";
// Button imported via sub-components

import { v2vApi, type GeneratedAudioResult } from "../api/v2v-api";
import { useV2VStore } from "../stores/v2v-store";
import { useProjectStore } from "@/stores/project-store";
import { useTimelineStore } from "@/stores/timeline-store";
import { useUIStore } from "@/stores/ui-store";
import { toast } from "@/stores/notification-store";
import { folderNameFromTitle, parseV2VSegmentFromName } from "../utils/v2v-utils";
import { applyRegeneratedSegmentToTimeline } from "../utils/v2v-segment-regen";
import { TTSBatchControls } from "./TTSBatchControls";
import { TTSSegmentCard } from "./TTSSegmentCard";


export const V2VGenerateTTSSection: React.FC<{ inDrawer?: boolean }> = ({
  inDrawer: _inDrawer = false,
}) => {
  const { project, importMedia, addClip, addTrack, getClip, getMediaItem, moveClip } = useProjectStore();
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
  const seekTo = useTimelineStore((s) => s.seekTo);
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
  const [volume, setVolume] = useState(6.0);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Estados para ajuste de velocidad sin regenerar TTS
  const [speedMode, setSpeedMode] = useState<"x" | "s">("x");
  const [speedInput, setSpeedInput] = useState<string>("1.000");
  const [isApplyingSpeed, setIsApplyingSpeed] = useState<boolean>(false);

  // Estados para posición editable de Playhead / Inicio de segmento
  const [positionInput, setPositionInput] = useState<string>("");
  const [isManualPosition, setIsManualPosition] = useState<boolean>(false);

  // Estados de proceso y preescucha
  const [isProcessing, setIsProcessing] = useState(false);
  const [isPlayingPreview, setIsPlayingPreview] = useState(false);
  const [cachedAudio, setCachedAudio] = useState<{
    result: GeneratedAudioResult;
    finalText: string;
    voice: string;
    volume: number;
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

  // Referencia para evitar sobreescribir el texto mientras el usuario edita y hay polling en segundo plano
  const lastLoadedClipKeyRef = useRef<string | null>(null);

  // Sincronizar campos cuando cambia el clip seleccionado en la Timeline
  useEffect(() => {
    const currentClipKey = selectedClip ? `${selectedClip.id}_${parsedSelectedSegment?.segIdx ?? ""}` : null;

    if (!currentClipKey) {
      lastLoadedClipKeyRef.current = null;
      return;
    }

    // Si ya cargamos el texto de este mismo clip, NO sobreescribir con el polling de fondo
    if (lastLoadedClipKeyRef.current === currentClipKey) {
      return;
    }

    lastLoadedClipKeyRef.current = currentClipKey;

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
            if (t && lastLoadedClipKeyRef.current === currentClipKey) setText(t);
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
      setIsManualPosition(false);
      setPositionInput(selectedClip.startTime.toFixed(2));
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
  ]);

  // Sincronizar posición con el timeline cuando el usuario mueve el playhead o cambia el clip
  useEffect(() => {
    if (!isManualPosition) {
      if (isEditingExistingSegment && selectedClip) {
        setPositionInput(selectedClip.startTime.toFixed(2));
      } else if (!isEditingExistingSegment) {
        setPositionInput(playheadPosition.toFixed(2));
      }
    }
  }, [playheadPosition, isEditingExistingSegment, selectedClip?.id, selectedClip?.startTime, isManualPosition]);

  // Limpiar preview al desmontar
  useEffect(() => {
    return () => {
      if (previewAudioRef.current) {
        previewAudioRef.current.pause();
        previewAudioRef.current = null;
      }
    };
  }, []);

  const handlePositionChange = (val: string) => {
    setIsManualPosition(true);
    setPositionInput(val);
  };

  const handleStepPosition = useCallback(async (delta: number) => {
    const current = parseFloat(positionInput);
    const fallback = isEditingExistingSegment && selectedClip ? selectedClip.startTime : playheadPosition;
    const base = !isNaN(current) && current >= 0 ? current : fallback;
    const raw = Math.max(0, base + delta);
    const newVal = Math.round(raw * 100) / 100;
    const formatted = newVal.toFixed(2);
    setPositionInput(formatted);
    setIsManualPosition(true);

    if (isEditingExistingSegment && selectedClip) {
      if (Math.abs(selectedClip.startTime - newVal) > 0.001) {
        try {
          await moveClip(selectedClip.id, newVal);
        } catch (e) {
          console.error("[V2V] Error al mover clip:", e);
        }
      }
    } else {
      seekTo(newVal);
    }
  }, [positionInput, isEditingExistingSegment, selectedClip, playheadPosition, moveClip, seekTo]);

  const handlePositionBlur = useCallback(async () => {
    const val = parseFloat(positionInput);
    if (!isNaN(val) && val >= 0) {
      if (isEditingExistingSegment && selectedClip) {
        if (Math.abs(selectedClip.startTime - val) > 0.001) {
          try {
            await moveClip(selectedClip.id, val);
          } catch (e) {
            console.error("[V2V] Error al mover clip:", e);
          }
        }
      } else {
        seekTo(val);
      }
      setPositionInput(val.toFixed(2));
    } else {
      const fallback = isEditingExistingSegment && selectedClip ? selectedClip.startTime : playheadPosition;
      setPositionInput(fallback.toFixed(2));
      setIsManualPosition(false);
    }
  }, [positionInput, isEditingExistingSegment, selectedClip, moveClip, seekTo, playheadPosition]);

  const handleSnapToPlayhead = useCallback(async () => {
    const target = Math.max(0, playheadPosition);
    setPositionInput(target.toFixed(2));
    setIsManualPosition(true);
    if (isEditingExistingSegment && selectedClip) {
      try {
        await moveClip(selectedClip.id, target);
        toast.info("Segmento movido", `Inicio fijado al playhead (${target.toFixed(2)}s)`);
      } catch (e) {
        console.error("[V2V] Error al mover clip al playhead:", e);
      }
    }
  }, [playheadPosition, isEditingExistingSegment, selectedClip, moveClip]);

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

    if (!jobId) {
      toast.error("Error", "No hay un trabajo V2V activo.");
      return;
    }

    try {
      setIsProcessing(true);
      let audioResult: GeneratedAudioResult;

      if (
        cachedAudio &&
        cachedAudio.finalText === finalText &&
        cachedAudio.voice === selectedVoice &&
        cachedAudio.volume === volume
      ) {
        audioResult = cachedAudio.result;
      } else {
        const parsedPos = parseFloat(positionInput);
        const effectivePreviewStart = !isNaN(parsedPos) && parsedPos >= 0
          ? parsedPos
          : (isEditingExistingSegment && selectedClip ? selectedClip.startTime : playheadPosition);

        audioResult = await v2vApi.generateNewAudioSegment(
          jobId,
          activeVideoIndex,
          finalText,
          selectedVoice,
          {
            start: effectivePreviewStart,
            temperature,
            volume,
          },
        );
        setCachedAudio({
          result: audioResult,
          finalText,
          voice: selectedVoice,
          volume,
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
    if (!isEditingExistingSegment || !parsedSelectedSegment || !selectedClip || !selectedMediaItem || !jobId) {
      toast.error("Selección requerida", "Debes tener seleccionado un segmento del timeline y un trabajo V2V activo.");
      return;
    }

    setIsApplyingSpeed(true);
    let effectiveSpeed = parseFloat(speedInput) || 1.0;
    let targetDuration: number | undefined;
    if (speedMode === "s" && effectiveSpeed > 0) {
      targetDuration = effectiveSpeed;
      effectiveSpeed = 1.0;
    }

    const parsedPos = parseFloat(positionInput);
    const startToUse = !isNaN(parsedPos) && parsedPos >= 0 ? parsedPos : selectedClip.startTime;

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
        start: startToUse,
        end: startToUse + (targetDuration ?? selectedClip.duration),
        effectiveSpeed: speedForStore,
        mediaId: selectedMediaItem.id,
        clipId: selectedClip.id,
        trackStart: selectedClip.startTime,
        targetStartTime: startToUse,
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

    if (!jobId) {
      toast.error("Error", "No hay un trabajo V2V activo.");
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
        const parsedPos = parseFloat(positionInput);
        const start = !isNaN(parsedPos) && parsedPos >= 0 ? parsedPos : selectedClip.startTime;

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

        const end = start + (targetDuration ?? selectedClip.duration);

        // Si ya se presionó "Reproducir" previamente y coincide el texto, voz y volumen,
        // reutilizamos ese resultado exacto para no alterar el audio escuchado.
        // Si no se reprodujo primero, se genera una nueva versión con la IA.
        const hasCachedAudio = Boolean(
          cachedAudio &&
          cachedAudio.finalText === finalText &&
          cachedAudio.voice === selectedVoice &&
          cachedAudio.volume === volume &&
          cachedAudio.result?.blob
        );

        let regenBlob: Blob;

        if (hasCachedAudio) {
          regenBlob = cachedAudio!.result.blob;
        } else {
          regenBlob = await v2vApi.regenerateSegment(
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
            { temperature, volume },
          );
        }

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
          targetStartTime: start,
        });

        if (result.success) {
          toast.success("Segmento regenerado", result.message);
          setCachedAudio(null);
          setIsV2VOpen(false);
        } else {
          throw new Error(result.message);
        }
      } else {
        // --- MODO NUEVO SEGMENTO TTS (N+1) AL PLAYHEAD ---
        const parsedPos = parseFloat(positionInput);
        const targetStart = !isNaN(parsedPos) && parsedPos >= 0 ? parsedPos : playheadPosition;

        let audioResult: GeneratedAudioResult;
        if (
          cachedAudio &&
          cachedAudio.finalText === finalText &&
          cachedAudio.voice === selectedVoice &&
          cachedAudio.volume === volume
        ) {
          audioResult = cachedAudio.result;
        } else {
          audioResult = await v2vApi.generateNewAudioSegment(
            jobId,
            activeVideoIndex,
            finalText,
            selectedVoice,
            {
              start: targetStart,
              temperature,
              volume,
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
        const startTime = Math.max(0, targetStart);
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
        setIsV2VOpen(false);
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
    setIsV2VOpen,
  ]);

  return (
    <div className="bg-bg-2/70 border border-border/80 rounded-xl p-3.5 space-y-3 shadow-sm">
      <TTSBatchControls
        isEditingExistingSegment={isEditingExistingSegment}
        segIdx={parsedSelectedSegment?.segIdx}
        clipDuration={selectedClip?.duration}
        onResetToNew={() => {
          clearSelection();
          setText("");
          setCachedAudio(null);
          setIsManualPosition(false);
          setPositionInput(playheadPosition.toFixed(2));
        }}
        onOpenBulkEditor={() => {
          setBulkEditorOpen(true);
          setIsV2VOpen(false);
        }}
      />

      <TTSSegmentCard
        text={text}
        setText={setText}
        selectedVoice={selectedVoice}
        setSelectedVoice={setSelectedVoice}
        speakers={speakers}
        onInsertEmotion={insertEmotionAtCursor}
        textareaRef={textareaRef}
        isEditingExistingSegment={isEditingExistingSegment}
        positionInput={positionInput}
        onPositionChange={handlePositionChange}
        onPositionBlur={handlePositionBlur}
        onStepPosition={handleStepPosition}
        onSnapToPlayhead={handleSnapToPlayhead}
        showAdvanced={showAdvanced}
        setShowAdvanced={setShowAdvanced}
        temperature={temperature}
        setTemperature={setTemperature}
        volume={volume}
        setVolume={setVolume}
        speedMode={speedMode}
        setSpeedMode={setSpeedMode}
        speedInput={speedInput}
        setSpeedInput={setSpeedInput}
        onApplySpeedOnly={handleApplySpeedOnly}
        isApplyingSpeed={isApplyingSpeed}
        clipDuration={selectedClip?.duration}
        isProcessing={isProcessing}
        isPlayingPreview={isPlayingPreview}
        onPreview={handlePreview}
        onMainAction={handleMainAction}
        mainActionLabel={
          isEditingExistingSegment
            ? `Regenerar #${parsedSelectedSegment?.segIdx}`
            : "Insertar al Timeline"
        }
        mainActionIcon={
          isEditingExistingSegment ? <RefreshCw size={13} /> : <Plus size={14} />
        }
      />
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
