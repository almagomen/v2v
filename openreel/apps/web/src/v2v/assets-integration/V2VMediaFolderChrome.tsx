import {
  ArrowLeft,
  Folder,
  Pencil,
  Plus,
  RefreshCw,
  Settings,
  Trash2,
} from "lucide-react";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@openreel/ui";
import type { MediaItem } from "@openreel/core";
import { GenerateAudioSegmentSection } from "../../components/editor/GenerateAudioSegmentSection";
import type { V2VMediaFoldersHandle } from "./useV2VMediaFolders";
import { getFolderName } from "./v2v-folder-utils";

export function V2VMediaFolderRails(
  props: V2VMediaFoldersHandle & { mediaItems: MediaItem[] },
) {
  const {
    activeFolder,
    setActiveFolder,
    draggedOverFolder,
    folderNames,
    mediaItems,
    handleRootDrop,
    handleFolderDrop,
    handleFolderDragOver,
    handleFolderDragLeave,
    handleRenameFolder,
    handleDeleteFolder,
    handleCopyFolderTtsToAnotherProject,
    setShowGenerateAudio,
    setDraggedOverFolder,
  } = props;

  return (
    <>
      {activeFolder ? (
        <div className="flex items-center gap-2 mb-3">
          <button
            type="button"
            onClick={() => setActiveFolder(null)}
            onDrop={handleRootDrop}
            onDragOver={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setDraggedOverFolder("__root__");
            }}
            onDragLeave={() => setDraggedOverFolder(null)}
            className={`p-1 rounded transition-colors border ${
              draggedOverFolder === "__root__"
                ? "bg-primary/10 border-primary text-primary"
                : "hover:bg-background-tertiary border-transparent text-text-muted"
            }`}
            title="Volver a la raíz (suelta archivos aquí para sacarlos)"
          >
            <ArrowLeft size={14} />
          </button>
          <div className="flex-1 text-[11px] text-text-primary truncate" title={activeFolder}>
            {activeFolder}
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => void handleRenameFolder()}
              className="p-1 rounded bg-background-tertiary border border-border hover:border-primary/50 text-text-muted hover:text-primary transition-all active:scale-90"
              title="Renombrar carpeta"
            >
              <Pencil size={14} />
            </button>
            <button
              type="button"
              onClick={() => setShowGenerateAudio(true)}
              className="p-1 rounded bg-primary/15 border border-primary/30 hover:border-primary/50 text-primary transition-all active:scale-90"
              title="Generar segmento de audio con IA"
            >
              <RefreshCw size={14} />
            </button>
            <button
              type="button"
              onClick={() => void handleDeleteFolder()}
              className="p-1 rounded bg-background-tertiary border border-border hover:border-red-500/50 text-red-400 transition-all active:scale-90"
              title="Borrar carpeta"
            >
              <Trash2 size={14} />
            </button>
            <button
              type="button"
              onClick={() => void handleCopyFolderTtsToAnotherProject()}
              className="p-1 rounded bg-primary/15 border border-primary/30 hover:border-primary/50 text-primary transition-all active:scale-90"
              title="Opciones de carpeta"
            >
              <Settings size={14} />
            </button>
          </div>
        </div>
      ) : folderNames.length > 0 ? (
        <div className="grid grid-cols-2 gap-3 mb-4">
          {folderNames.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setActiveFolder(f)}
              onDragOver={(e) => handleFolderDragOver(e, f)}
              onDragLeave={handleFolderDragLeave}
              onDrop={(e) => void handleFolderDrop(e, f)}
              className={`aspect-video bg-background-tertiary rounded-lg border-2 transition-all flex flex-col items-center justify-center gap-1.5 ${
                draggedOverFolder === f
                  ? "border-primary bg-primary/10 shadow-[0_0_15px_rgba(108,99,255,0.4)]"
                  : "border-border hover:border-primary/50"
              }`}
              title={f}
            >
              <Folder size={22} className={draggedOverFolder === f ? "text-primary" : "text-text-muted"} />
              <span
                className={`text-[10px] truncate max-w-[120px] ${
                  draggedOverFolder === f ? "text-primary" : "text-text-secondary"
                }`}
              >
                {f}
              </span>
              <span className="text-[9px] text-text-muted">
                {mediaItems.filter((m) => getFolderName(m.name) === f).length} items
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </>
  );
}

export function V2VMediaFolderModals(v: V2VMediaFoldersHandle) {
  const {
    activeFolder,
    showCopyProjectModal,
    setShowCopyProjectModal,
    copyTargets,
    copyingTargetId,
    handleConfirmCopyToTarget,
    handleAddV2VFolderAsNewTracks,
    showGenerateAudio,
    setShowGenerateAudio,
  } = v;

  return (
    <>
      <Dialog open={showCopyProjectModal} onOpenChange={setShowCopyProjectModal}>
        <DialogContent className="max-w-md p-0 gap-0 bg-background-secondary border-border overflow-hidden">
          <DialogHeader className="p-4 border-b border-border space-y-1">
            <DialogTitle className="text-base font-semibold text-text-primary">
              Opciones de carpeta
            </DialogTitle>
            <DialogDescription className="text-xs text-text-muted">
              Añadir al timeline o copiar a otro proyecto.
            </DialogDescription>
          </DialogHeader>

          <div className="p-3 space-y-2 max-h-[320px] overflow-y-auto">
            <button
              type="button"
              onClick={() => {
                setShowCopyProjectModal(false);
                void handleAddV2VFolderAsNewTracks();
              }}
              className="w-full text-left p-3 mb-2 rounded-lg border border-primary/40 bg-primary/10 hover:border-primary transition-colors flex items-center justify-between"
            >
              <div>
                <div className="text-sm font-medium text-primary">Añadir al timeline</div>
                <div className="text-[11px] text-text-muted mt-0.5">
                  En nuevas pistas sincronizadas con job V2V
                </div>
              </div>
              <Plus size={18} className="text-primary" />
            </button>

            {copyTargets.length > 0 && (
              <div className="text-[10px] font-bold text-text-muted uppercase mb-1 tracking-wider mt-4 px-1">
                Copiar a otro proyecto
              </div>
            )}
            {copyTargets.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => void handleConfirmCopyToTarget(t.id)}
                disabled={Boolean(copyingTargetId)}
                className="w-full text-left p-3 rounded-lg border border-border bg-background-tertiary hover:border-primary/50 transition-colors disabled:opacity-60"
              >
                <div className="text-sm font-medium text-text-primary">{t.name}</div>
                <div className="text-[11px] text-text-muted">{t.subtitle}</div>
              </button>
            ))}
          </div>

          <div className="p-3 border-t border-border flex justify-end">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setShowCopyProjectModal(false)}
              disabled={Boolean(copyingTargetId)}
            >
              Cerrar
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {activeFolder ? (
        <GenerateAudioSegmentSection
          key={activeFolder}
          folder={activeFolder}
          open={showGenerateAudio}
          onOpenChange={setShowGenerateAudio}
        />
      ) : null}
    </>
  );
}
