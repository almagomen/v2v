import React from "react";
import { Loader2 } from "lucide-react";

export interface RenderProgressBarProps {
  isRunning: boolean;
  currentStep?: string;
  status: string;
  progress: number;
  currentVideoName?: string;
  statusMsg?: string;
  isBatch?: boolean;
  totalVideos?: number;
  currentIdx?: number;
}

export const RenderProgressBar: React.FC<RenderProgressBarProps> = ({
  isRunning,
  currentStep,
  status,
  progress,
  currentVideoName,
  statusMsg,
  isBatch = false,
  totalVideos = 0,
  currentIdx = 1,
}) => {
  if (!isRunning) return null;

  const displayProgress = progress || (status === "uploading" ? 15 : 50);

  return (
    <div className="space-y-2 p-3 bg-primary/10 border border-primary/30 rounded-xl shadow-sm">
      {/* Fila 1: Paso actual y Porcentaje */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Loader2 size={13} className="animate-spin text-primary shrink-0" />
          <span className="text-xs font-semibold text-text-primary truncate">
            {currentStep || (status === "uploading" ? "Preparando medios…" : "Renderizando…")}
          </span>
        </div>
        <span className="text-[11px] font-mono font-bold text-primary px-2 py-0.5 bg-primary/20 rounded-full border border-primary/30 shrink-0">
          {displayProgress}%
        </span>
      </div>

      {/* Barra de progreso animada */}
      <div className="w-full bg-background-secondary rounded-full h-2 overflow-hidden border border-border/60">
        <div
          className="bg-primary h-full transition-all duration-300 ease-out rounded-full"
          style={{
            width: `${Math.max(4, Math.min(100, displayProgress))}%`,
          }}
        />
      </div>

      {/* Fila 2: Nombre del video en proceso y contador */}
      <div className="flex items-center justify-between text-[10px] text-text-muted gap-2 pt-0.5">
        <span
          className="truncate max-w-[270px] font-medium text-text-secondary"
          title={currentVideoName || statusMsg}
        >
          {currentVideoName ? `▶ ${currentVideoName}` : statusMsg}
        </span>
        {isBatch && totalVideos > 0 && (
          <span className="shrink-0 font-semibold text-primary/90">
            {currentIdx || 1} de {totalVideos}
          </span>
        )}
      </div>
    </div>
  );
};
