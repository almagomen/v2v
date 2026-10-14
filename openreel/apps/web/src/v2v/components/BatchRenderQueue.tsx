import React from "react";
import { Loader2, CheckSquare, Square, Sparkles } from "lucide-react";
import type { AutoSaveMetadata } from "@/services/auto-save";
import type { Project } from "@openreel/core";

export interface SavedProjectItem {
  meta: AutoSaveMetadata;
  project?: Project;
  selected: boolean;
}

export interface BatchRenderQueueProps {
  loadingSaved: boolean;
  savedProjects: SavedProjectItem[];
  isRunning: boolean;
  batchRegeneratingId: string | null;
  onToggleAll: () => void;
  onToggleProject: (id: string) => void;
  onBatchRegenerateTitle: (sp: SavedProjectItem) => void;
}

export const BatchRenderQueue: React.FC<BatchRenderQueueProps> = ({
  loadingSaved,
  savedProjects,
  isRunning,
  batchRegeneratingId,
  onToggleAll,
  onToggleProject,
  onBatchRegenerateTitle,
}) => {
  if (loadingSaved) {
    return (
      <div className="flex items-center gap-2 text-xs text-text-muted p-3">
        <Loader2 size={14} className="animate-spin" />
        Cargando proyectos guardados…
      </div>
    );
  }

  if (savedProjects.length === 0) {
    return <div className="text-xs text-text-muted p-3 text-center">No hay proyectos guardados.</div>;
  }

  const allSelected = savedProjects.every((p) => p.selected);
  const selectedCount = savedProjects.filter((p) => p.selected).length;

  return (
    <div className="space-y-2">
      <button
        onClick={onToggleAll}
        className="text-[10px] text-primary hover:underline px-1"
        disabled={isRunning}
      >
        {allSelected ? "Deseleccionar todo" : "Seleccionar todo"}
      </button>
      <div className="max-h-56 overflow-y-auto space-y-1.5 border border-border rounded-lg p-2">
        {savedProjects.map((sp) => (
          <div
            key={sp.meta.id}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded hover:bg-background-tertiary transition-colors"
          >
            <button
              onClick={() => onToggleProject(sp.meta.id)}
              disabled={isRunning}
              className="flex items-center gap-2 flex-1 min-w-0 text-left"
            >
              {sp.selected ? (
                <CheckSquare size={14} className="text-primary shrink-0" />
              ) : (
                <Square size={14} className="text-text-muted shrink-0" />
              )}
              <span className="text-xs text-text-primary truncate" title={sp.meta.projectName}>
                {sp.meta.projectName}
              </span>
            </button>

            <button
              onClick={(e) => {
                e.stopPropagation();
                onBatchRegenerateTitle(sp);
              }}
              disabled={isRunning || batchRegeneratingId === sp.meta.id}
              className="p-1 rounded hover:bg-primary/20 text-yellow-400 hover:text-yellow-300 transition-colors shrink-0"
              title="Regenerar título viral con IA para este proyecto"
            >
              {batchRegeneratingId === sp.meta.id ? (
                <Loader2 size={12} className="animate-spin text-primary" />
              ) : (
                <Sparkles size={12} />
              )}
            </button>

            <span className="text-[10px] text-text-muted shrink-0">
              {new Date(sp.meta.timestamp).toLocaleDateString()}
            </span>
          </div>
        ))}
      </div>
      <p className="text-[10px] text-text-muted px-1">
        {selectedCount} de {savedProjects.length} seleccionados
      </p>
    </div>
  );
};
