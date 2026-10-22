import React, { useState, useRef } from "react";
import {
  AlertTriangle,
  Clock,
  SlidersHorizontal,
  ChevronUp,
  ChevronDown,
  Sparkles,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@openreel/ui";
import { useProjectStore } from "@/stores/project-store";
import { toast } from "@/stores/notification-store";
import { v2vApi } from "../api/v2v-api";
import { EmotionSelector } from "./EmotionSelector";
import { SegmentAudioSliders } from "./SegmentAudioSliders";

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
  originalSpeaker?: string;
  previousSpeakerToken: string;
  selected: boolean;
  dirty: boolean;
  mediaId?: string;
  clipId?: string;
  filename?: string | null;
  missingAudio: boolean;
  temperature: number;
  topP: number;
  repetitionPenalty: number;
  volume: number;
  phonemes?: Record<string, string>;
};


export interface SegmentRowProps {
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
}

export const SegmentRow: React.FC<SegmentRowProps> = ({
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
}) => {
  const [showSettings, setShowSettings] = useState(false);
  const [playing, setPlaying] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const hasCustomFishAudio = Math.abs(row.temperature - 0.7) > 0.01;

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
    } catch {
      setPlaying(false);
      toast.error("Error", "No se pudo reproducir el audio.");
    }
  };

  return (
    <div
      className={`rounded-lg border p-2.5 space-y-2.5 transition-colors ${
        row.missingAudio ? "border-red-500/40 bg-red-500/5" : "border-border bg-background"
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
        {row.originalSpeaker && (
          <span
            className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500 border border-amber-500/25"
            title={`Hablante original detectado por diarización: ${row.originalSpeaker}`}
          >
            {row.originalSpeaker}
          </span>
        )}
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

        <span
          className="text-[10px] font-mono text-text-muted flex items-center gap-1 bg-background-tertiary px-2 py-0.5 rounded border border-border/40"
          title="Posición real en el timeline"
        >
          <Clock size={11} className="text-primary shrink-0" />
          <span>
            {timelineStart.toFixed(2)}s – dur: {timelineDuration.toFixed(2)}s
          </span>
        </span>

        <button
          type="button"
          onClick={() => setShowSettings(!showSettings)}
          className={`flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border transition-colors cursor-pointer ${
            showSettings || hasCustomFishAudio
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
        {/* Original STT Text */}
        <div className="bg-background-tertiary/30 rounded p-1.5 border border-border/40 space-y-1">
          <div className="flex items-center justify-between text-[9px] text-text-muted mb-0.5">
            <span className="font-medium">Original (STT)</span>
            <span
              className="font-mono bg-background-tertiary px-1.5 py-0.2 rounded border border-border/40 text-[9px]"
              title="Duración original del segmento"
            >
              duración orig: {row.slotDuration.toFixed(2)}s
            </span>
          </div>
          <p className="text-[10px] text-text-muted leading-snug break-words">{row.originalText || "—"}</p>
        </div>

        {/* Draft Text + Emotion + AI Rewrite */}
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center justify-between gap-1">
            <div className="flex items-center gap-1.5">
              <p className="text-[9px] font-medium text-text-muted">TTS / Texto traducido</p>
              <button
                type="button"
                disabled={isProposingTranslation}
                onClick={onProposeTranslation}
                className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded border border-primary/30 bg-primary/10 text-primary hover:bg-primary/20 transition-all cursor-pointer font-medium disabled:opacity-50"
                title={`Reescribir frase manteniendo la idea según el idioma seleccionado (${targetLang})`}
              >
                {isProposingTranslation ? (
                  <Loader2 size={10} className="animate-spin text-primary" />
                ) : (
                  <Sparkles size={10} className="text-primary" />
                )}
                <span>{isProposingTranslation ? "Reescribiendo..." : "Proponer"}</span>
              </button>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-[9px] text-text-muted font-medium">Emoción:</span>
              <EmotionSelector onChange={insertTag} />
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
      </div>

      {showSettings && (
        <SegmentAudioSliders
          temperature={row.temperature}
          onTemperatureChange={(t) => updateRow(row.seg, { temperature: t })}
          onReset={() => updateRow(row.seg, { temperature: 0.7 })}
        />
      )}

      {/* Speed Controls */}
      <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-border/40">
        <span className="text-[9px] text-text-muted font-medium">Ajuste de velocidad:</span>
        <Select
          value={row.speedMode}
          onValueChange={(v) => {
            const isS = v === "s";
            updateRow(row.seg, {
              speedMode: isS ? "s" : "x",
              speedInput: isS
                ? row.slotDuration.toFixed(3)
                : row.loadedSpeed !== 1.0
                  ? row.loadedSpeed.toFixed(3)
                  : "1.000",
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
              title="Deslizar para ajustar velocidad (0.5x – 2.0x)"
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
            title="Duración exacta en segundos"
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
            title="Regenerar segmento con Fish Audio y sincronizarlo al timeline"
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
    </div>
  );
};
