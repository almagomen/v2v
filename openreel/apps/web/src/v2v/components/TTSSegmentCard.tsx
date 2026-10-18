import React from "react";
import {
  Clock,
  ChevronUp,
  ChevronDown,
  SlidersHorizontal,
  Loader2,
  Square,
  Play,
} from "lucide-react";
import { Button } from "@openreel/ui";
import { EmotionSelector } from "./EmotionSelector";

export interface TTSSegmentCardProps {
  text: string;
  setText: (text: string) => void;
  selectedVoice: string;
  setSelectedVoice: (voice: string) => void;
  speakers: Array<{ label: string; value: string }>;
  onInsertEmotion: (emotion: string) => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  isEditingExistingSegment: boolean;
  positionInput: string;
  onPositionChange: (val: string) => void;
  onPositionBlur: () => void;
  onStepPosition: (delta: number) => void;
  onSnapToPlayhead?: () => void;
  showAdvanced: boolean;
  setShowAdvanced: (val: boolean) => void;
  temperature: number;
  setTemperature: (val: number) => void;
  volume: number;
  setVolume: (val: number) => void;
  speedMode: "x" | "s";
  setSpeedMode: (val: "x" | "s") => void;
  speedInput: string;
  setSpeedInput: (val: string) => void;
  onApplySpeedOnly?: () => void;
  isApplyingSpeed?: boolean;
  clipDuration?: number;
  isProcessing: boolean;
  isPlayingPreview: boolean;
  onPreview: () => void;
  onMainAction: () => void;
  mainActionLabel: string;
  mainActionIcon: React.ReactNode;
}

export const TTSSegmentCard: React.FC<TTSSegmentCardProps> = ({
  text,
  setText,
  selectedVoice,
  setSelectedVoice,
  speakers,
  onInsertEmotion,
  textareaRef,
  isEditingExistingSegment,
  positionInput,
  onPositionChange,
  onPositionBlur,
  onStepPosition,
  onSnapToPlayhead,
  showAdvanced,
  setShowAdvanced,
  temperature,
  setTemperature,
  volume,
  setVolume,
  speedMode,
  setSpeedMode,
  speedInput,
  setSpeedInput,
  onApplySpeedOnly,
  isApplyingSpeed = false,
  clipDuration,
  isProcessing,
  isPlayingPreview,
  onPreview,
  onMainAction,
  mainActionLabel,
  mainActionIcon,
}) => {
  return (
    <div className="space-y-3">
      {/* Selectores de Voz y Emoción */}
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <label className="text-[10px] font-semibold text-fg-2 block">Voz</label>
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

        <div className="space-y-1">
          <label className="text-[10px] font-semibold text-fg-2 flex items-center justify-between">
            <span>Insertar</span>
            <span className="text-[9px] text-primary font-medium">S2.1</span>
          </label>
          <EmotionSelector onChange={onInsertEmotion} className="w-full h-8 px-2 text-xs bg-bg-1 border border-border rounded-lg text-fg focus:outline-none focus:ring-1 focus:ring-primary truncate cursor-pointer" />
        </div>
      </div>

      {/* Área de texto */}
      <div className="space-y-1">
        <label className="text-[10px] font-semibold text-fg-2 block">Texto del segmento</label>
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

      {/* Indicador y edición de posición en Timeline */}
      <div className="flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-md bg-bg-3/50 text-[11px] text-fg-3 border border-border/40">
        <div className="flex items-center gap-1.5 min-w-0">
          <Clock size={12} className="text-primary shrink-0" />
          <span className="text-[10px] font-semibold text-fg-2 truncate">
            {isEditingExistingSegment ? "Inicio segmento:" : "Posición Playhead:"}
          </span>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {isEditingExistingSegment && onSnapToPlayhead && (
            <button
              type="button"
              onClick={onSnapToPlayhead}
              className="text-[9px] px-1.5 py-0.5 rounded bg-bg-1 hover:bg-hover border border-border/60 text-fg-3 hover:text-primary transition-colors cursor-pointer"
              title="Alinear inicio del clip a la posición actual del Playhead"
            >
              Al Playhead
            </button>
          )}

          <div className="flex items-center bg-bg-1 border border-border rounded px-1.5 py-0.5 focus-within:ring-1 focus-within:ring-primary focus-within:border-primary transition-all">
            <input
              type="number"
              step="0.05"
              min="0"
              value={positionInput}
              onChange={(e) => onPositionChange(e.target.value)}
              onBlur={onPositionBlur}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  onPositionBlur();
                  (e.target as HTMLInputElement).blur();
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  onStepPosition(0.05);
                } else if (e.key === "ArrowDown") {
                  e.preventDefault();
                  onStepPosition(-0.05);
                }
              }}
              className="w-12 text-right font-mono text-xs bg-transparent text-fg focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
              title="Edita los segundos o usa las flechas para mover el segmento"
            />
            <span className="text-[10px] text-fg-4 font-mono font-medium ml-1 mr-1 select-none">s</span>

            <div className="flex flex-col border-l border-border/60 pl-1 -my-0.5 justify-center">
              <button
                type="button"
                onClick={() => onStepPosition(0.05)}
                className="p-0.5 text-fg-3 hover:text-primary hover:bg-hover rounded transition-colors cursor-pointer"
                title="Avanzar +0.05s"
              >
                <ChevronUp size={10} />
              </button>
              <button
                type="button"
                onClick={() => onStepPosition(-0.05)}
                className="p-0.5 text-fg-3 hover:text-primary hover:bg-hover rounded transition-colors cursor-pointer"
                title="Retroceder -0.05s"
              >
                <ChevronDown size={10} />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Ajustes avanzados */}
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
      </div>

      {showAdvanced && (
        <div className="pb-1 space-y-2.5 animate-in fade-in duration-150">
          {isEditingExistingSegment && (
            <div className="p-2 rounded-lg bg-bg-1 border border-border/70 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-fg-3 font-medium">Velocidad:</span>
                <span className="text-[9px] text-fg-4 font-mono">
                  {clipDuration !== undefined ? `actual: ${clipDuration.toFixed(2)}s` : ""}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <select
                  value={speedMode}
                  onChange={(e) => {
                    const isS = e.target.value === "s";
                    setSpeedMode(isS ? "s" : "x");
                    if (clipDuration !== undefined) {
                      setSpeedInput(isS ? clipDuration.toFixed(3) : "1.000");
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
                      title="Ajustar velocidad (0.5x – 2.0x)"
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
                    placeholder={clipDuration?.toFixed(2) || "1.0"}
                    value={speedInput}
                    onChange={(e) => setSpeedInput(e.target.value)}
                    title="Duración exacta en segundos"
                  />
                )}
                {onApplySpeedOnly && (
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    className="text-[9px] h-7 px-2.5 ml-auto shrink-0 bg-bg-3 hover:bg-bg-2 text-fg border border-border"
                    disabled={isProcessing || isApplyingSpeed}
                    onClick={onApplySpeedOnly}
                    title="Aplica la velocidad sin volver a generar audio"
                  >
                    {isApplyingSpeed ? <Loader2 size={11} className="animate-spin mr-1" /> : null}
                    Ajustar
                  </Button>
                )}
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

          <div className="space-y-1.5 pt-1 border-t border-border/50">
            <div className="flex justify-between text-[10px] text-fg-3">
              <span>Volumen Fish Audio</span>
              <span className="font-mono text-fg font-semibold">
                {volume > 0 ? `+${volume.toFixed(1)}` : volume.toFixed(1)} dB
              </span>
            </div>
            <input
              type="range"
              min="-10"
              max="15"
              step="0.5"
              value={volume}
              onChange={(e) => setVolume(parseFloat(e.target.value))}
              className="w-full accent-primary h-1 bg-border rounded-lg cursor-pointer"
            />
            <div className="flex justify-between text-[8px] text-fg-4">
              <span>Suave (-10 dB)</span>
              <span className="font-medium text-primary">Por defecto (+6 dB)</span>
              <span>Potente (+15 dB)</span>
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
          onClick={onPreview}
          disabled={isProcessing || !text.trim()}
          className="flex-1 text-xs h-8 gap-1.5 border-border bg-bg-1 hover:bg-bg-3"
          title="Escuchar antes de insertarlo en el timeline"
        >
          {isProcessing ? (
            <Loader2 size={13} className="animate-spin text-primary" />
          ) : isPlayingPreview ? (
            <Square size={13} className="text-red-500 fill-red-500" />
          ) : (
            <Play size={13} className="text-fg-2" />
          )}
          <span>{isPlayingPreview ? "Detener" : "Reproducir"}</span>
        </Button>

        <Button
          type="button"
          size="sm"
          onClick={onMainAction}
          disabled={isProcessing || !text.trim()}
          className={`flex-1 text-xs h-8 gap-1.5 font-semibold shadow ${
            isEditingExistingSegment
              ? "bg-amber-500 hover:bg-amber-600 text-white"
              : "bg-primary hover:bg-primary/90 text-primary-foreground"
          }`}
        >
          {mainActionIcon}
          <span>{mainActionLabel}</span>
        </Button>
      </div>
    </div>
  );
};
