import React from "react";
import { RefreshCw, Mic, X, ListChecks } from "lucide-react";
import { Button } from "@openreel/ui";

export interface TTSBatchControlsProps {
  isEditingExistingSegment: boolean;
  segIdx?: number;
  clipDuration?: number;
  onResetToNew?: () => void;
  onOpenBulkEditor: () => void;
}

export const TTSBatchControls: React.FC<TTSBatchControlsProps> = ({
  isEditingExistingSegment,
  segIdx,
  clipDuration,
  onResetToNew,
  onOpenBulkEditor,
}) => {
  return (
    <div className="flex items-center justify-between border-b border-border/50 pb-2.5">
      <div className="flex items-center gap-2">
        <div
          className={`w-7 h-7 rounded-lg flex items-center justify-center ${
            isEditingExistingSegment ? "bg-amber-500/15 text-amber-500" : "bg-red-500/15 text-red-500"
          }`}
        >
          {isEditingExistingSegment ? <RefreshCw size={15} /> : <Mic size={15} />}
        </div>
        <div>
          <div className="flex items-center gap-1.5">
            <h4 className="text-xs font-bold text-fg">
              {isEditingExistingSegment ? `Editar Segmento #${segIdx}` : "Generador de Voz TTS"}
            </h4>
            <span
              className={`text-[9px] font-medium px-1.5 py-0.2 rounded border font-mono ${
                isEditingExistingSegment
                  ? "bg-amber-500/10 text-amber-500 border-amber-500/20"
                  : "bg-primary/10 text-primary border-primary/20"
              }`}
            >
              {isEditingExistingSegment && clipDuration !== undefined
                ? `dur: ${clipDuration.toFixed(2)}s`
                : isEditingExistingSegment
                  ? "Clip"
                  : "IA N+1"}
            </span>
          </div>
          <p className="text-[10px] text-fg-3">
            {isEditingExistingSegment
              ? "Modifica el texto o voz del segmento seleccionado en Timeline"
              : "Crea una locución a partir de texto y colócala en el Timeline"}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-1.5">
        {isEditingExistingSegment && onResetToNew && (
          <button
            type="button"
            onClick={onResetToNew}
            className="text-[10px] flex items-center gap-1 text-fg-3 hover:text-fg px-1.5 py-1 rounded hover:bg-hover transition-colors cursor-pointer"
            title="Deseleccionar clip y crear un nuevo segmento"
          >
            <X size={12} />
            <span>Nuevo</span>
          </button>
        )}

        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="text-[10px] h-7 px-2.5 gap-1.5 text-fg-2 hover:text-fg bg-bg-3/80 hover:bg-bg-3 border border-border/60 cursor-pointer"
          onClick={onOpenBulkEditor}
          title="Abrir la ventana de edición masiva de todos los segmentos del video"
        >
          <ListChecks size={13} className="text-primary" />
          <span>Editor en Lote</span>
        </Button>
      </div>
    </div>
  );
};
