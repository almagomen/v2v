import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Clock,
  Loader2,
  ListChecks,
  RefreshCw,
  RotateCcw,
  SlidersHorizontal,
  Sparkles,
  Volume2,
} from "lucide-react";
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@openreel/ui";

import { v2vApi, type SegmentEditorRow } from "../api/v2v-api";
import { useV2VStore } from "../stores/v2v-store";
import { useProjectStore } from "@/stores/project-store";
import { toast } from "@/stores/notification-store";
import { generateSegmentId } from "../utils/v2v-segment-ids";
import {
  applyRegeneratedSegmentToTimeline,
  findClipIdForSegment,
  parsedSpeakerTokenFromMediaName,
  resolveMediaIdForSegment,
} from "../utils/v2v-segment-regen";
import { toSafeToken } from "../utils/v2v-utils";
import { autoSaveManager } from "@/services/auto-save";
import {
  V2V_EMOTIONS,
  DEFAULT_EMOTION_TAG,
  EMOTION_CATEGORIES,
  getEmotionsByCategory,
  formatEmotionLabel,
  applyEmotionToText,
  extractEmotionFromText,
} from "../utils/v2v-emotions";

export type BulkSegmentRow = {
  seg: number;
  start: number;
  end: number;
  slotDuration: number;
  originalText: string;
  draftText: string;
  loadedText: string;
  loadedSpeed: number;
  loadedSpeedInput: string;
  speed: number;
  speedMode: "x" | "s";
  speedInput: string;
  speaker: string;
  speakerLabel: string;
  previousSpeakerToken: string;
  selected: boolean;
  dirty: boolean;
  mediaId?: string;
  clipId?: string;
  filename?: string | null;
  /** true si el MediaItem es placeholder (TTS falló al generar) */
  missingAudio: boolean;
  /** Parámetros Fish Audio por slot */
  temperature: number;
  topP: number;
  repetitionPenalty: number;
  volume: number;
};

function speakerLabelFor(speakers: { value: string; label: string }[], token: string): string {
  return speakers.find((s) => s.value === token)?.label || token;
}

function rowIsDirty(row: BulkSegmentRow): boolean {
  if (row.draftText.trim() !== row.loadedText.trim()) return true;
  if (row.speedMode === "x" && Math.abs(row.speed - row.loadedSpeed) > 0.001) return true;
  if (row.speedInput.trim() !== row.loadedSpeedInput.trim()) return true;
  if (Math.abs((row.temperature ?? 0.7) - 0.7) > 0.01) return true;
  return false;
}

type Props = {
  jobId: string;
  videoIndex: number;
  folder: string;
  targetLang?: string | null;
  /** Oculta la fila con icono + título (p. ej. cuando el modal ya muestra DialogTitle). */
  hideTitle?: boolean;
  /** Más altura útil para lista dentro de un modal. */
  inDialog?: boolean;
};

export const V2VSegmentBulkEditor: React.FC<Props> = ({
  jobId,
  videoIndex,
  folder,
  targetLang,
  hideTitle = false,
  inDialog = false,
}) => {
  const { getFolderRef, speakers, fetchSpeakers, speaker: defaultSpeaker, translateLang } =
    useV2VStore();
  const { getMediaItem } = useProjectStore();

  const [rows, setRows] = useState<BulkSegmentRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [retranslateBusy, setRetranslateBusy] = useState(false);
  const [retranslatingSingleSeg, setRetranslatingSingleSeg] = useState<number | null>(null);
  const [applyBusy, setApplyBusy] = useState(false);
  const [applyProgress, setApplyProgress] = useState<{ current: number; total: number } | null>(
    null,
  );
  const [selectedTargetLang, setSelectedTargetLang] = useState<string>(() => {
    if (targetLang && targetLang !== "None") return targetLang;
    if (translateLang && translateLang !== "None") return translateLang;
    return "es";
  });
  const [regeneratingSeg, setRegeneratingSeg] = useState<number | null>(null);
  const [bulkEmotion, setBulkEmotion] = useState<string>(DEFAULT_EMOTION_TAG);

  const handleApplyBulkEmotion = useCallback(() => {
    const anySelected = rows.some((r) => r.selected);
    const targetRows = anySelected ? rows.filter((r) => r.selected) : rows;
    if (targetRows.length === 0) return;

    setRows((prev) =>
      prev.map((r) => {
        if (anySelected && !r.selected) return r;
        const updatedDraft = applyEmotionToText(r.draftText, bulkEmotion);
        return {
          ...r,
          draftText: updatedDraft,
          dirty: updatedDraft.trim() !== r.loadedText.trim(),
        };
      }),
    );
    toast.success(
      "Emoción aplicada",
      `Se aplicó ${bulkEmotion} a ${targetRows.length} segmento(s).`,
    );
  }, [rows, bulkEmotion]);

  useEffect(() => {
    if (speakers.length === 0) fetchSpeakers();
  }, [speakers.length, fetchSpeakers]);

  const normalizeTranslateLang = useMemo(() => {
    if (targetLang && targetLang !== "None") return targetLang;
    if (translateLang && translateLang !== "None") return translateLang;
    return null;
  }, [targetLang, translateLang]);

  const buildRow = useCallback(
    async (apiRow: SegmentEditorRow): Promise<BulkSegmentRow> => {
      const folderRef = getFolderRef(folder);
      const segmentId = generateSegmentId(jobId, videoIndex, apiRow.seg);
      const stored = folderRef?.segments?.[segmentId];

      const ttsText = stored?.editedText?.trim() || apiRow.tts_text || "";
      const speakerToken = stored?.speaker || apiRow.speaker || defaultSpeaker || "speaker";
      const speakerLabel = speakerLabelFor(speakers, speakerToken);

      // Velocidad directa como multiplicador del segmento sintetizado (por defecto 1.0)
      const loadedSpeed = stored?.speed ?? 1.0;
      const loadedSpeedInput = loadedSpeed !== 1.0 ? loadedSpeed.toFixed(3) : "1.000";

      const mediaId =
        stored?.mediaId ||
        resolveMediaIdForSegment(apiRow.seg, {
          speaker: speakerToken,
          filename: apiRow.filename,
        });

      let previousSpeakerToken = toSafeToken(speakerToken);
      if (mediaId) {
        const media = getMediaItem(mediaId);
        if (media?.name) {
          previousSpeakerToken = parsedSpeakerTokenFromMediaName(media.name);
        }
      }

      const mediaItem = mediaId != null ? getMediaItem(mediaId) : undefined;
      const missingAudio = !!mediaItem?.isPlaceholder;

      const clipId =
        mediaId != null ? findClipIdForSegment(mediaId, apiRow.start) ?? undefined : undefined;

      const base: BulkSegmentRow = {
        seg: apiRow.seg,
        start: apiRow.start,
        end: apiRow.end,
        slotDuration: apiRow.slot_duration,
        originalText: apiRow.original_text || "",
        draftText: ttsText,
        loadedText: ttsText,
        loadedSpeed,
        loadedSpeedInput,
        speed: loadedSpeed,
        speedMode: "x",
        speedInput: loadedSpeedInput,
        speaker: speakerToken,
        speakerLabel,
        previousSpeakerToken,
        selected: false,
        dirty: false,
        mediaId,
        clipId,
        filename: apiRow.filename,
        missingAudio,
        temperature: 0.7,
        topP: 0.7,
        repetitionPenalty: 1.2,
        volume: 0.0,
      };
      // Si el audio falta, forzamos dirty=true para que "Aplicar todos" lo incluya automáticamente
      const forceDirty = missingAudio && ttsText.trim().length > 0;
      return { ...base, dirty: forceDirty || rowIsDirty(base) };
    },
    [folder, getFolderRef, jobId, videoIndex, defaultSpeaker, speakers, getMediaItem],
  );

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setLoadError(null);
      try {
        const data = await v2vApi.getSegmentsEditor(jobId, videoIndex);
        if (cancelled) return;
        const built = await Promise.all(data.segments.map((r) => buildRow(r)));
        if (cancelled) return;
        // Auto-seleccionar filas con audio faltante para fácil regeneración
        const withAutoSelect = built.map(r => ({ ...r, selected: r.missingAudio }));
        if (!cancelled) setRows(withAutoSelect);
      } catch (e) {
        if (!cancelled) {
          setLoadError(e instanceof Error ? e.message : "Error al cargar segmentos");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [jobId, videoIndex, buildRow]);

  const visibleRows = rows;

  const selectedCount = useMemo(() => rows.filter((r) => r.selected).length, [rows]);
  const dirtyCount = useMemo(() => rows.filter((r) => r.dirty).length, [rows]);

  const updateRow = useCallback((seg: number, patch: Partial<BulkSegmentRow>) => {
    setRows((prev) =>
      prev.map((r) => {
        if (r.seg !== seg) return r;
        const next = { ...r, ...patch };
        return { ...next, dirty: rowIsDirty(next) };
      }),
    );
  }, []);

  const selectAll = () => setRows((prev) => prev.map((r) => ({ ...r, selected: true })));
  const selectNone = () => setRows((prev) => prev.map((r) => ({ ...r, selected: false })));

  const handleProposeTranslation = async (specificSegs?: number[]) => {
    const targets = specificSegs ? rows.filter(r => specificSegs.includes(r.seg)) : rows.filter((r) => r.selected);
    if (targets.length === 0) {
      toast.warning("Selecciona segmentos", "Marca al menos un segmento para proponer traducción.");
      return;
    }

    const isSingle = targets.length === 1;
    if (isSingle) {
      setRetranslatingSingleSeg(targets[0].seg);
    } else {
      setRetranslateBusy(true);
    }

    try {
      const effectiveTargetLang = selectedTargetLang || normalizeTranslateLang || "es";
      const customMap: Record<number, string> = {};
      for (const t of targets) {
        const textToUse = t.originalText?.trim() || t.draftText?.trim();
        if (textToUse) customMap[t.seg] = textToUse;
      }

      const { segments } = await v2vApi.retranslateSegments(
        jobId,
        videoIndex,
        targets.map((r) => r.seg),
        effectiveTargetLang,
        Object.keys(customMap).length > 0 ? customMap : undefined,
      );
      const bySeg = new Map(segments.map((s) => [s.seg, s.text]));
      setRows((prev) =>
        prev.map((r) => {
          const text = bySeg.get(r.seg);
          if (text == null) return r;
          const next = { ...r, draftText: text };
          return { ...next, dirty: rowIsDirty(next) };
        }),
      );
      if (isSingle) {
        toast.success("Frase reescrita", `Segmento #${targets[0].seg} adaptado con éxito a (${effectiveTargetLang}).`);
      } else {
        toast.success("Traducción propuesta", `${segments.length} segmento(s) reescritos a (${effectiveTargetLang}).`);
      }
    } catch (e) {
      toast.error("Error al reescribir frase", e instanceof Error ? e.message : String(e));
    } finally {
      setRetranslateBusy(false);
      setRetranslatingSingleSeg(null);
    }
  };

  const handleRegenerateSingle = async (row: BulkSegmentRow) => {
    setRegeneratingSeg(row.seg);
    try {
      let effectiveSpeed = 1.0;
      let targetDuration: number | undefined = undefined;

      if (row.speedMode === "x") {
        const parsed = parseFloat(row.speedInput);
        effectiveSpeed = !isNaN(parsed) && parsed > 0 ? parsed : 1.0;
        targetDuration = undefined;
      } else {
        const parsed = parseFloat(row.speedInput);
        targetDuration = !isNaN(parsed) && parsed > 0 ? parsed : row.slotDuration;
        effectiveSpeed = 1.0;
      }
      const speedForStore = row.speedMode === "x" ? effectiveSpeed : 1.0;

      const regenBlob = await v2vApi.regenerateSegment(
        jobId,
        videoIndex,
        row.seg,
        row.draftText,
        row.start,
        row.end,
        selectedTargetLang || normalizeTranslateLang || "es",
        row.speaker,
        effectiveSpeed,
        targetDuration,
        {
          temperature: row.temperature,
          top_p: row.topP,
          repetition_penalty: row.repetitionPenalty,
          volume: row.volume,
        },
      );

      const result = await applyRegeneratedSegmentToTimeline({
        folder,
        jobId,
        videoIndex,
        segIdx: row.seg,
        regenBlob,
        text: row.draftText,
        speaker: row.speaker,
        speakerLabel: row.speakerLabel,
        previousSpeakerToken: row.previousSpeakerToken,
        start: row.start,
        end: row.end,
        effectiveSpeed: speedForStore,
        mediaId: row.mediaId,
        clipId: row.clipId,
        trackStart: row.start,
        targetStartTime: row.start,
      });

      if (!result.success) {
        throw new Error(result.message || "No se pudo actualizar el timeline");
      }

      const newSpeedInput =
        row.speedMode === "s" ? row.speedInput : speedForStore.toFixed(3);
      setRows((prev) =>
        prev.map((r) =>
          r.seg === row.seg
            ? {
              ...r,
              loadedText: row.draftText,
              loadedSpeed: speedForStore,
              loadedSpeedInput: newSpeedInput,
              speed: speedForStore,
              speedInput: newSpeedInput,
              mediaId: result.mediaId ?? r.mediaId,
              clipId: result.clipId ?? r.clipId,
              dirty: false,
              missingAudio: false,
            }
            : r,
        ),
      );
      toast.success("Segmento regenerado", `#${row.seg} actualizado y sincronizado en el timeline.`);
    } catch (e) {
      toast.error("Error al regenerar", e instanceof Error ? e.message : String(e));
    } finally {
      setRegeneratingSeg(null);
    }
  };

  const handleApplySpeedOnly = async (row: BulkSegmentRow) => {
    setApplyBusy(true);
    let effectiveSpeed = 1.0;
    let targetDuration: number | undefined = undefined;

    if (row.speedMode === "x") {
      const parsed = parseFloat(row.speedInput);
      effectiveSpeed = !isNaN(parsed) && parsed > 0 ? parsed : 1.0;
      targetDuration = undefined;
    } else {
      const parsed = parseFloat(row.speedInput);
      targetDuration = !isNaN(parsed) && parsed > 0 ? parsed : row.slotDuration;
      effectiveSpeed = 1.0;
    }

    try {
      const regenBlob = await v2vApi.applyAudioSpeed(
        jobId,
        videoIndex,
        row.seg,
        row.speedMode === "x" ? effectiveSpeed : null,
        targetDuration
      );

      const speedForStore = row.speedMode === "x" ? effectiveSpeed : 1.0;

      const result = await applyRegeneratedSegmentToTimeline({
        folder,
        jobId,
        videoIndex,
        segIdx: row.seg,
        regenBlob,
        text: row.loadedText, // Mantenemos el texto original (no TTS nuevo)
        speaker: row.speaker,
        speakerLabel: row.speakerLabel,
        previousSpeakerToken: row.previousSpeakerToken,
        start: row.start,
        end: row.end,
        effectiveSpeed: speedForStore,
        mediaId: row.mediaId,
        clipId: row.clipId,
        trackStart: row.start,
        targetStartTime: row.start,
      });

      if (!result.success) {
        throw new Error("No se pudo actualizar el timeline");
      }

      setRows((prev) =>
        prev.map((r) =>
          r.seg === row.seg
            ? {
              ...r,
              loadedText: r.draftText, // El texto en el timeline podría no cambiar, pero si lo modificó no importa
              loadedSpeedInput: row.speedInput,
              loadedSpeed: row.speedMode === "x" ? effectiveSpeed : row.loadedSpeed,
              dirty: false,
            }
            : r
        )
      );
      toast.success("Velocidad aplicada", "Se ajustó el segmento sin regenerar voz.");
    } catch (e) {
      toast.error("Error al aplicar velocidad", e instanceof Error ? e.message : String(e));
    } finally {
      setApplyBusy(false);
    }
  };

  const applyRows = async (toApply: BulkSegmentRow[]) => {
    const dirtyRows = toApply.filter((r) => r.dirty);
    if (dirtyRows.length === 0) {
      toast.info("Sin cambios", "No hay segmentos modificados para aplicar.");
      return;
    }

    setApplyBusy(true);
    setApplyProgress({ current: 0, total: dirtyRows.length });
    let ok = 0;
    let fail = 0;
    const errors: string[] = [];

    for (let i = 0; i < dirtyRows.length; i++) {
      const row = dirtyRows[i];
      setApplyProgress({ current: i + 1, total: dirtyRows.length });

      let effectiveSpeed = 1.0;
      let targetDuration: number | undefined = undefined;

      if (row.speedMode === "x") {
        const parsed = parseFloat(row.speedInput);
        effectiveSpeed = !isNaN(parsed) && parsed > 0 ? parsed : 1.0;
        targetDuration = undefined;
      } else {
        const parsed = parseFloat(row.speedInput);
        targetDuration = !isNaN(parsed) && parsed > 0 ? parsed : row.slotDuration;
        effectiveSpeed = 1.0;
      }

      const speedForStore = row.speedMode === "x" ? effectiveSpeed : 1.0;

      try {
        const regenBlob = await v2vApi.regenerateSegment(
          jobId,
          videoIndex,
          row.seg,
          row.draftText,
          row.start,
          row.end,
          selectedTargetLang || normalizeTranslateLang || "es",
          row.speaker,
          effectiveSpeed,
          targetDuration,
          {
            temperature: row.temperature,
            top_p: row.topP,
            repetition_penalty: row.repetitionPenalty,
            volume: row.volume,
          },
        );

        const result = await applyRegeneratedSegmentToTimeline({
          folder,
          jobId,
          videoIndex,
          segIdx: row.seg,
          regenBlob,
          text: row.draftText,
          speaker: row.speaker,
          speakerLabel: row.speakerLabel,
          previousSpeakerToken: row.previousSpeakerToken,
          start: row.start,
          end: row.end,
          effectiveSpeed: speedForStore,
          mediaId: row.mediaId,
          clipId: row.clipId,
          trackStart: row.start,
          targetStartTime: row.start,
        });

        if (!result.success) {
          fail++;
          errors.push(`#${row.seg}: ${result.message}`);
        } else {
          ok++;
          const newSpeedInput =
            row.speedMode === "s" ? row.speedInput : speedForStore.toFixed(3);
          setRows((prev) =>
            prev.map((r) => {
              if (r.seg !== row.seg) return r;
              const next: BulkSegmentRow = {
                ...r,
                loadedText: row.draftText,
                loadedSpeed: speedForStore,
                loadedSpeedInput: newSpeedInput,
                speed: speedForStore,
                speedInput: newSpeedInput,
                mediaId: result.mediaId ?? r.mediaId,
                clipId: result.clipId ?? r.clipId,
              };
              return { ...next, dirty: false };
            }),
          );
        }
      } catch (e) {
        fail++;
        errors.push(`#${row.seg}: ${e instanceof Error ? e.message : String(e)}`);
      }
    }

    setApplyBusy(false);
    setApplyProgress(null);

    if (ok > 0) {
      toast.success("Aplicación completada", `${ok} segmento(s) regenerados.`);
    }
    if (fail > 0) {
      toast.error(`${fail} error(es)`, errors.slice(0, 3).join("\n"));
    }

    const projectStore = useProjectStore.getState();
    if (projectStore.project.name === folder) {
      try {
        await autoSaveManager.initialize();
        const saves = await autoSaveManager.checkForRecovery();
        const latest = saves
          .filter((s: { projectName: string }) => s.projectName === folder)
          .sort((a: { timestamp: number }, b: { timestamp: number }) => b.timestamp - a.timestamp)[0];
        if (latest) {
          await projectStore.recoverFromAutoSave(latest.id);
        }
      } catch {
        // ignore
      }
    }
  };

  const handleApplySelected = () => {
    const selected = rows.filter((r) => r.selected && r.dirty);
    if (selected.length === 0) {
      if (!rows.some((r) => r.selected)) {
        toast.warning("Selecciona segmentos", "Marca segmentos modificados para aplicar.");
        return;
      }
      toast.info("Sin cambios", "Los segmentos seleccionados no tienen cambios.");
      return;
    }
    void applyRows(selected);
  };

  if (loading) {
    return (
      <StatusRow>
        <Loader2 size={14} className="animate-spin text-primary" />
        <span className="text-[10px] text-text-muted">Cargando segmentos…</span>
      </StatusRow>
    );
  }

  if (loadError) {
    return (
      <StatusRow>
        <AlertCircle size={14} className="text-red-400 shrink-0" />
        <span className="text-[10px] text-red-400">{loadError}</span>
      </StatusRow>
    );
  }

  if (rows.length === 0) {
    return <p className="text-[10px] text-text-muted">No hay segmentos para este video.</p>;
  }

  const listScrollClass = inDialog
    ? "max-h-[min(60vh,520px)]"
    : "max-h-72";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {!hideTitle && (
          <div className="flex items-center gap-2">
            <ListChecks size={14} className="text-primary" />
            <p className="text-xs font-medium text-text-primary">Editar segmentos</p>
          </div>
        )}
        <p className="text-[10px] text-text-muted">
          {selectedCount} sel. · {dirtyCount} mod.
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Button type="button" size="sm" variant="secondary" className="text-[10px] h-7 px-2" onClick={selectAll}>
          Todo
        </Button>
        <Button type="button" size="sm" variant="secondary" className="text-[10px] h-7 px-2" onClick={selectNone}>
          Ninguno
        </Button>



        <div className="flex items-center gap-1 bg-background border border-border rounded-md px-1">
          <span className="text-[9px] text-text-muted font-medium px-1">Traducir a:</span>
          <Select value={selectedTargetLang} onValueChange={setSelectedTargetLang}>
            <SelectTrigger className="h-7 text-[10px] w-28 border-0 bg-transparent shadow-none px-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="es">Español (es)</SelectItem>
              <SelectItem value="en">English (en)</SelectItem>
              <SelectItem value="pt">Português (pt)</SelectItem>
              <SelectItem value="fr">Français (fr)</SelectItem>
              <SelectItem value="de">Deutsch (de)</SelectItem>
              <SelectItem value="it">Italiano (it)</SelectItem>
              <SelectItem value="ja">日本語 (ja)</SelectItem>
              <SelectItem value="zh">中文 (zh)</SelectItem>
            </SelectContent>
          </Select>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            className="text-[10px] h-7 px-2"
            disabled={retranslateBusy || applyBusy}
            onClick={() => void handleProposeTranslation()}
            title={`Retraducir seleccionados a ${selectedTargetLang}`}
          >
            {retranslateBusy ? <Loader2 size={12} className="animate-spin" /> : "Proponer traducción"}
          </Button>
        </div>

        <div className="flex items-center gap-1 bg-background border border-border rounded-md px-1.5 h-7">
          <span className="text-[9px] text-text-muted font-medium">Emoción:</span>
          <select
            value={bulkEmotion}
            onChange={(e) => setBulkEmotion(e.target.value)}
            className="h-6 text-[10px] bg-transparent border-0 focus:outline-none text-text-primary pr-1 max-w-[200px] truncate cursor-pointer font-medium"
          >
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
          <Button
            type="button"
            size="sm"
            variant="secondary"
            className="text-[9px] h-5 px-1.5"
            onClick={handleApplyBulkEmotion}
            title="Aplica la emoción seleccionada a los segmentos marcados (o a todos si no hay selección)"
          >
            Aplicar
          </Button>
        </div>

        <Button type="button" size="sm" className="text-[10px] h-7" disabled={applyBusy} onClick={handleApplySelected}>
          Aplicar seleccionados
        </Button>

        <Button
          type="button"
          size="sm"
          variant="outline"
          className="text-[10px] h-7"
          disabled={applyBusy || dirtyCount === 0}
          onClick={() => void applyRows(rows)}
        >
          Aplicar todos ({dirtyCount})
        </Button>
      </div>

      {applyProgress && (
        <ApplyProgressBlock applyProgress={applyProgress} />
      )}

      <div
        className={`${listScrollClass} overflow-y-auto space-y-2 pr-1 border border-border rounded-lg p-2 bg-background-tertiary/40`}
      >
        {visibleRows.length === 0 ? (
          <p className="text-[10px] text-text-muted text-center py-4">
            Ningún segmento coincide con el filtro.
          </p>
        ) : (
          visibleRows.map((row) => (
            <SegmentRow
              key={row.seg}
              row={row}
              updateRow={updateRow}
              jobId={jobId}
              videoIndex={videoIndex}
              onApplyRow={() => void handleApplySpeedOnly(row)}
              onRegenerateSingle={() => void handleRegenerateSingle(row)}
              isRegenerating={regeneratingSeg === row.seg}
              onProposeTranslation={() => void handleProposeTranslation([row.seg])}
              isProposingTranslation={retranslatingSingleSeg === row.seg}
              targetLang={selectedTargetLang || normalizeTranslateLang || "es"}
            />
          ))
        )}
      </div>

    </div>
  );
};

function StatusRow({ children }: { children: React.ReactNode }) {
  return <div className="flex items-center gap-2 py-2">{children}</div>;
}

function ApplyProgressBlock({
  applyProgress,
}: {
  applyProgress: { current: number; total: number };
}) {
  const pct =
    applyProgress.total > 0
      ? Math.round((applyProgress.current / applyProgress.total) * 100)
      : 0;
  return (
    <div className="space-y-1">
      <div className="h-1.5 rounded-full bg-background-tertiary overflow-hidden">
        <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </div>
      <p className="text-[10px] text-text-muted">
        Segmento {applyProgress.current}/{applyProgress.total}…
      </p>
    </div>
  );
}


function SegmentRow({
  row,
  updateRow,
  jobId,
  videoIndex,
  onApplyRow,
  onRegenerateSingle,
  isRegenerating,
  onProposeTranslation,
  isProposingTranslation,
  targetLang,
}: {
  row: BulkSegmentRow;
  updateRow: (seg: number, patch: Partial<BulkSegmentRow>) => void;
  jobId: string;
  videoIndex: number;
  onApplyRow: () => void;
  onRegenerateSingle: () => void;
  isRegenerating: boolean;
  onProposeTranslation: () => void;
  isProposingTranslation: boolean;
  targetLang: string;
}) {
  const [showSettings, setShowSettings] = useState(false);
  const hasCustomFishAudio = Math.abs(row.temperature - 0.7) > 0.01;

  // Clip reactivo en el timeline para actualizar posición en tiempo real si el usuario lo mueve o recorta
  const currentClip = useProjectStore((state) => {
    for (const track of state.project.timeline.tracks) {
      if (row.clipId) {
        const found = track.clips.find((c) => c.id === row.clipId);
        if (found) return found;
      }
      if (row.mediaId) {
        const found = track.clips.find((c) => c.mediaId === row.mediaId);
        if (found) return found;
      }
    }
    return null;
  });

  const timelineStart = currentClip ? currentClip.startTime : row.start;
  const timelineDuration = currentClip ? currentClip.duration : row.slotDuration;

  return (
    <div
      className={`rounded-lg border p-2.5 space-y-2.5 transition-colors ${row.missingAudio
          ? "border-red-500/40 bg-red-500/5"
          : "border-border bg-background"
        }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="checkbox"
          checked={row.selected}
          onChange={(e) => updateRow(row.seg, { selected: e.target.checked })}
          className="rounded border-border cursor-pointer"
          title="Seleccionar segmento para acciones en lote"
        />
        <span
          className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/25 font-mono"
          title={`Segmento consecutivo #${row.seg}`}
        >
          Seg #{row.seg}
        </span>
        {row.missingAudio && (
          <span className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 font-medium">
            <AlertTriangle size={10} />
            Sin audio – regenerar
          </span>
        )}
        {row.dirty && (
          <button
            type="button"
            onClick={() =>
              updateRow(row.seg, {
                draftText: row.loadedText,
                speedInput: row.loadedSpeedInput,
                speedMode: "x",
                speed: row.loadedSpeed,
                temperature: 0.7,
                topP: 0.7,
                repetitionPenalty: 1.2,
                volume: 0.0,
              })
            }
            className="text-[9px] text-primary hover:underline cursor-pointer"
            title="Deshacer cambios"
          >
            modificado
          </button>
        )}

        <div className="flex-1" />

        {/* Posición real en el timeline posicionada del lado derecho (reactiva) */}
        <span
          className="text-[10px] font-mono text-text-muted flex items-center gap-1 bg-background-tertiary px-2 py-0.5 rounded border border-border/40"
          title="Posición real en el timeline: inicio en timeline - duración actual (se actualiza automáticamente al arrastrar el clip)"
        >
          <Clock size={11} className="text-primary shrink-0" />
          <span>{timelineStart.toFixed(2)}s – dur: {timelineDuration.toFixed(2)}s</span>
        </span>

        {/* Botón para desplegar ajustes de Fish Audio */}
        <button
          type="button"
          onClick={() => setShowSettings(!showSettings)}
          className={`flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border transition-colors cursor-pointer ${showSettings || hasCustomFishAudio
            ? "border-primary/40 bg-primary/10 text-primary font-medium"
            : "border-border/60 bg-background-tertiary text-text-muted hover:text-text-primary"
            }`}
          title="Ajustes de expresividad y voz Fish Audio"
        >
          <SlidersHorizontal size={11} />
          <span>Voz Fish</span>
          {hasCustomFishAudio && (
            <span className="w-1.5 h-1.5 rounded-full bg-primary" title="Parámetros personalizados" />
          )}
          {showSettings ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        <SegmentOriginalText row={row} />
        <SegmentDraftText
          row={row}
          updateRow={updateRow}
          onProposeTranslation={onProposeTranslation}
          isProposing={isProposingTranslation}
          targetLang={targetLang}
        />
      </div>

      {/* Panel colapsable de ajustes de Fish Audio */}
      {showSettings && (
        <SegmentFishAudioSettings row={row} updateRow={updateRow} />
      )}

      <SegmentSpeedControls
        row={row}
        updateRow={updateRow}
        jobId={jobId}
        videoIndex={videoIndex}
        onApplyRow={onApplyRow}
        onRegenerateSingle={onRegenerateSingle}
        isRegenerating={isRegenerating}
      />
    </div>
  );
}

function SegmentOriginalText({ row }: { row: BulkSegmentRow }) {
  return (
    <div className="bg-background-tertiary/30 rounded p-1.5 border border-border/40 space-y-1">
      <div className="flex items-center justify-between text-[9px] text-text-muted mb-0.5">
        <span className="font-medium">Original (STT)</span>
        <span
          className="font-mono bg-background-tertiary px-1.5 py-0.2 rounded border border-border/40 text-[9px]"
          title="Duración original del segmento detectada en el video"
        >
          duración orig: {row.slotDuration.toFixed(2)}s
        </span>
      </div>
      <p className="text-[10px] text-text-muted leading-snug break-words">{row.originalText || "—"}</p>
    </div>
  );
}

function SegmentDraftText({
  row,
  updateRow,
  onProposeTranslation,
  isProposing,
  targetLang,
}: {
  row: BulkSegmentRow;
  updateRow: (seg: number, patch: Partial<BulkSegmentRow>) => void;
  onProposeTranslation: () => void;
  isProposing: boolean;
  targetLang: string;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const insertTag = (tag: string) => {
    if (!tag || tag === "none") return;
    const formattedTag = tag.startsWith("[") ? tag : `[${tag}]`;
    const el = textareaRef.current;
    if (!el) {
      updateRow(row.seg, { draftText: `${row.draftText} ${formattedTag}`.trim() });
      return;
    }
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    const text = row.draftText;
    const inserted = text.substring(0, start) + `${formattedTag} ` + text.substring(end);
    updateRow(row.seg, { draftText: inserted });
    setTimeout(() => {
      el.focus();
      const pos = start + formattedTag.length + 1;
      el.setSelectionRange(pos, pos);
    }, 0);
  };

  const handleEmotionChange = (newTag: string) => {
    insertTag(newTag);
  };

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center justify-between gap-1">
        <div className="flex items-center gap-1.5">
          <p className="text-[9px] font-medium text-text-muted">TTS / Texto traducido</p>
          <button
            type="button"
            disabled={isProposing}
            onClick={onProposeTranslation}
            className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded border border-primary/30 bg-primary/10 text-primary hover:bg-primary/20 transition-all cursor-pointer font-medium disabled:opacity-50"
            title={`Reescribir frase manteniendo la idea según el idioma seleccionado (${targetLang})`}
          >
            {isProposing ? (
              <Loader2 size={10} className="animate-spin text-primary" />
            ) : (
              <Sparkles size={10} className="text-primary" />
            )}
            <span>{isProposing ? "Reescribiendo..." : "Proponer"}</span>
          </button>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-[9px] text-text-muted font-medium">Emoción:</span>
          <select
            value=""
            onChange={(e) => handleEmotionChange(e.target.value)}
            className="h-6 text-[10px] px-1.5 bg-background-tertiary border border-border rounded text-text-primary focus:outline-none focus:border-primary cursor-pointer max-w-[210px] truncate font-medium"
            title="Selecciona una emoción para insertarla en la posición del cursor"
          >
            <option value="" disabled>✨ Insertar...</option>
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

      <textarea
        ref={textareaRef}
        className="w-full min-h-[52px] text-[10px] px-2 py-1.5 rounded border border-border bg-background-tertiary resize-y focus:outline-none focus:border-primary leading-relaxed"
        value={row.draftText}
        placeholder="Texto a sintetizar. Puedes usar emociones como [excited], [happy], etc."
        onChange={(e) => updateRow(row.seg, { draftText: e.target.value })}
      />
    </div>
  );
}

function SegmentFishAudioSettings({
  row,
  updateRow,
}: {
  row: BulkSegmentRow;
  updateRow: (seg: number, patch: Partial<BulkSegmentRow>) => void;
}) {
  const resetDefaults = () => {
    updateRow(row.seg, {
      temperature: 0.7,
    });
  };

  return (
    <div className="p-2.5 rounded-md border border-primary/20 bg-primary/5 space-y-2 text-[10px]">
      <div className="flex items-center justify-between pb-1 border-b border-primary/10">
        <span className="font-semibold text-primary flex items-center gap-1">
          <SlidersHorizontal size={12} />
          Parámetro Fish Audio
        </span>
        <button
          type="button"
          onClick={resetDefaults}
          className="text-[9px] text-text-muted hover:text-text-primary flex items-center gap-1 cursor-pointer"
          title="Restablecer temperatura por defecto"
        >
          <RotateCcw size={10} />
          Restablecer (0.70)
        </button>
      </div>

      <div>
        <div className="flex justify-between text-[9px] text-text-muted mb-0.5">
          <span>Expresividad (Temperature)</span>
          <span className="font-mono text-text-primary font-semibold">{row.temperature.toFixed(2)}</span>
        </div>
        <input
          type="range"
          min="0.1"
          max="1.0"
          step="0.05"
          value={row.temperature}
          onChange={(e) => updateRow(row.seg, { temperature: parseFloat(e.target.value) })}
          className="w-full accent-primary h-1 bg-background-tertiary rounded cursor-pointer"
        />
        <div className="flex justify-between text-[8px] text-text-muted">
          <span>Consistente / Estable (0.1)</span>
          <span>Variado / Expresivo (1.0)</span>
        </div>
      </div>
    </div>
  );
}

function SegmentSpeedControls({
  row,
  updateRow,
  jobId,
  videoIndex,
  onApplyRow,
  onRegenerateSingle,
  isRegenerating,
}: {
  row: BulkSegmentRow;
  updateRow: (seg: number, patch: Partial<BulkSegmentRow>) => void;
  jobId: string;
  videoIndex: number;
  onApplyRow: () => void;
  onRegenerateSingle: () => void;
  isRegenerating: boolean;
}) {
  const [playing, setPlaying] = useState(false);

  const handlePlayAudio = async () => {
    if (playing) return;
    try {
      setPlaying(true);
      const blob = await v2vApi.fetchAudioSegmentBlob(jobId, videoIndex, row.seg);
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => {
        setPlaying(false);
        URL.revokeObjectURL(url);
      };
      audio.onerror = () => {
        setPlaying(false);
        URL.revokeObjectURL(url);
        toast.error("Error al reproducir", "No se pudo cargar el audio del segmento.");
      };
      await audio.play();
    } catch (e) {
      setPlaying(false);
      toast.error("Error", "No se pudo reproducir el audio.");
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-border/40">
      <span className="text-[9px] text-text-muted font-medium">Ajuste de velocidad:</span>
      <Select
        value={row.speedMode}
        onValueChange={(v) => {
          const isS = v === "s";
          updateRow(row.seg, {
            speedMode: isS ? "s" : "x",
            speedInput: isS ? row.slotDuration.toFixed(3) : (row.loadedSpeed !== 1.0 ? row.loadedSpeed.toFixed(3) : "1.000"),
          });
        }}
      >
        <SelectTrigger className="h-7 w-14 text-[10px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="x">×</SelectItem>
          <SelectItem value="s">s</SelectItem>
        </SelectContent>
      </Select>
      {row.speedMode === "x" ? (
        <div className="flex items-center gap-1.5">
          <input
            type="range"
            min="0.5"
            max="2.0"
            step="0.05"
            value={parseFloat(row.speedInput) || 1.0}
            onChange={(e) => updateRow(row.seg, { speedInput: parseFloat(e.target.value).toFixed(2) })}
            className="w-20 accent-primary h-1 bg-background-tertiary rounded cursor-pointer"
            title="Deslizar para ajustar velocidad del segmento sintetizado (0.5x – 2.0x)"
          />
          <input
            type="text"
            className="w-14 h-7 text-[10px] px-1 text-center rounded border border-border bg-background-tertiary font-mono"
            placeholder="1.00"
            value={row.speedInput}
            onChange={(e) => updateRow(row.seg, { speedInput: e.target.value })}
            title="Factor multiplicador de velocidad"
          />
        </div>
      ) : (
        <input
          type="text"
          className="w-18 h-7 text-[10px] px-2 rounded border border-border bg-background-tertiary font-mono"
          placeholder={row.slotDuration.toFixed(2)}
          value={row.speedInput}
          onChange={(e) => updateRow(row.seg, { speedInput: e.target.value })}
          title="Duración exacta en segundos para este segmento"
        />
      )}
      <Button
        type="button"
        size="sm"
        variant="secondary"
        className="text-[9px] h-7 px-2"
        disabled={!row.dirty || isRegenerating}
        onClick={onApplyRow}
        title="Aplica la velocidad sin volver a llamar a la API de voz"
      >
        Ajustar
      </Button>

      <div className="flex-1 min-w-[8px]" />

      {/* Botones de acción individual: Reproducir y Regenerar */}
      <div className="flex items-center gap-1.5 ml-auto">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="text-[9px] h-7 px-2.5"
          disabled={playing || isRegenerating}
          onClick={() => void handlePlayAudio()}
        >
          {playing ? "Reproduciendo..." : "Reproducir"}
        </Button>

        <Button
          type="button"
          size="sm"
          className="text-[9px] h-7 px-2.5 bg-primary text-primary-foreground hover:bg-primary/90 flex items-center gap-1 shadow-sm font-medium"
          disabled={isRegenerating}
          onClick={onRegenerateSingle}
          title="Regenerar segmento con Fish Audio y sincronizarlo inmediatamente al timeline"
        >
          {isRegenerating ? (
            <>
              <Loader2 size={11} className="animate-spin" />
              <span>Regenerando...</span>
            </>
          ) : (
            <>
              <RefreshCw size={11} />
              <span>Regenerar</span>
            </>
          )}
        </Button>
      </div>
    </div>
  );
}

