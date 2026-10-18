import React from "react";
import { SlidersHorizontal, RotateCcw } from "lucide-react";

export interface SegmentAudioSlidersProps {
  temperature: number;
  onTemperatureChange: (temp: number) => void;
  volume?: number;
  onVolumeChange?: (vol: number) => void;
  onReset?: () => void;
}

export const SegmentAudioSliders: React.FC<SegmentAudioSlidersProps> = ({
  temperature,
  onTemperatureChange,
  volume = 6.0,
  onVolumeChange,
  onReset,
}) => {
  return (
    <div className="p-2.5 rounded-md border border-primary/20 bg-primary/5 space-y-2 text-[10px]">
      <div className="flex items-center justify-between pb-1 border-b border-primary/10">
        <span className="font-semibold text-primary flex items-center gap-1">
          <SlidersHorizontal size={12} />
          Parámetros Fish Audio
        </span>
        {onReset && (
          <button
            type="button"
            onClick={onReset}
            className="text-[9px] text-text-muted hover:text-text-primary flex items-center gap-1 cursor-pointer"
            title="Restablecer valores por defecto (Temp: 0.70, Vol: +6.0 dB)"
          >
            <RotateCcw size={10} />
            Restablecer (0.70 / +6dB)
          </button>
        )}
      </div>

      <div>
        <div className="flex justify-between text-[9px] text-text-muted mb-0.5">
          <span>Expresividad (Temperature)</span>
          <span className="font-mono text-text-primary font-semibold">{temperature.toFixed(2)}</span>
        </div>
        <input
          type="range"
          min="0.1"
          max="1.0"
          step="0.05"
          value={temperature}
          onChange={(e) => onTemperatureChange(parseFloat(e.target.value))}
          className="w-full accent-primary h-1 bg-background-tertiary rounded cursor-pointer"
        />
        <div className="flex justify-between text-[8px] text-text-muted">
          <span>Consistente / Estable (0.1)</span>
          <span>Variado / Expresivo (1.0)</span>
        </div>
      </div>

      {onVolumeChange && (
        <div className="pt-1 border-t border-primary/10">
          <div className="flex justify-between text-[9px] text-text-muted mb-0.5">
            <span>Volumen (Ganancia nativa)</span>
            <span className="font-mono text-text-primary font-semibold">
              {volume > 0 ? `+${volume.toFixed(1)}` : volume.toFixed(1)} dB
            </span>
          </div>
          <input
            type="range"
            min="-10"
            max="15"
            step="0.5"
            value={volume}
            onChange={(e) => onVolumeChange(parseFloat(e.target.value))}
            className="w-full accent-primary h-1 bg-background-tertiary rounded cursor-pointer"
          />
          <div className="flex justify-between text-[8px] text-text-muted">
            <span>Suave (-10 dB)</span>
            <span className="font-medium text-primary">Por defecto (+6 dB)</span>
            <span>Potente (+15 dB)</span>
          </div>
        </div>
      )}
    </div>
  );
};
