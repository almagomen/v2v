import React from "react";
import { Youtube, ListChecks, X } from "lucide-react";
import { useProjectStore } from "../../../stores/project-store";
import { useV2VStore } from "../../../stores/v2v-store";
import { folderNameFromTitle } from "../../../utils/v2v-utils";
import { V2VPanel } from "../V2VPanel";
import { V2VSegmentBulkEditor } from "./V2VSegmentBulkEditor";

export const V2VToolbarEntry: React.FC = () => {
  const { project } = useProjectStore();
  const {
    isV2VOpen,
    setIsV2VOpen,
    bulkEditorOpen,
    setBulkEditorOpen,
    selectedVideoIndex,
    jobId,
    videos,
    getFolderRef,
    translateLang,
  } = useV2VStore();

  const effectiveDropdownValue = React.useMemo(() => {
    for (let i = 0; i < videos.length; i++) {
      const v = videos[i] as any;
      const projectTitle = folderNameFromTitle(v.output_name || `video_${v.index}`);
      if (project.name === projectTitle) return i;
    }
    return -1;
  }, [videos, project.name]);

  const bulkEditorContext = React.useMemo(() => {
    const videoIdx =
      effectiveDropdownValue >= 0 ? effectiveDropdownValue : (selectedVideoIndex >= 0 ? selectedVideoIndex : 0);
    if (!jobId || videoIdx < 0 || !videos[videoIdx]) return null;
    const v = videos[videoIdx] as { index: number; output_name?: string; url?: string };
    const folder = folderNameFromTitle(v.output_name || `video_${v.index}`);
    if (!getFolderRef(folder)) return null;
    return {
      jobId,
      videoIndex: v.index,
      folder,
      targetLang: translateLang === "None" ? null : translateLang,
    };
  }, [jobId, selectedVideoIndex, effectiveDropdownValue, videos, getFolderRef, translateLang]);

  return (
    <>
      {/* Botón en el Toolbar */}
      <button
        type="button"
        onClick={() => setIsV2VOpen(!isV2VOpen)}
        className={`flex items-center gap-1.5 rounded-[8px] px-3 py-[9px] text-[13px] font-semibold transition-colors ${
          isV2VOpen
            ? "bg-red-500/15 text-red-500 hover:bg-red-500/20"
            : "bg-bg-2 text-fg-2 hover:text-fg hover:bg-bg-3"
        }`}
        title="Video2Video – Traducción y doblaje"
      >
        <Youtube size={15} className="text-red-500" />
        <span className="hidden sm:inline">Video2Video</span>
      </button>

      {/* Drawer lateral de Video2Video */}
      {isV2VOpen && (
        <>
          <div
            className="fixed inset-0 bg-black/20 z-40"
            onClick={() => setIsV2VOpen(false)}
          />
          <div className="fixed top-topbar right-0 bottom-0 w-full max-w-md bg-bg-1 border-l border-border z-50 shadow-2xl animate-in slide-in-from-right duration-200 flex flex-col">
            <div className="flex items-center justify-between p-3 border-b border-border shrink-0">
              <span className="text-sm font-bold text-fg">
                Video2Video
              </span>
              <button
                type="button"
                onClick={() => setIsV2VOpen(false)}
                className="p-1.5 rounded hover:bg-hover text-fg-3 hover:text-fg transition-colors"
                title="Cerrar panel Video2Video"
              >
                <X size={14} />
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
              <V2VPanel embedInDrawer />
            </div>
          </div>
        </>
      )}

      {/* Diálogo flotante no-bloqueante para edición en lote de segmentos */}
      {bulkEditorOpen && bulkEditorContext && (
        <div 
          className="fixed top-14 left-1/2 -translate-x-1/2 w-[calc(100vw-2rem)] max-w-4xl max-h-[58vh] bg-bg-1 border border-border shadow-2xl rounded-xl z-50 flex flex-col overflow-hidden pointer-events-auto"
        >
          {/* Header */}
          <div className="px-5 py-3 space-y-0.5 shrink-0 text-left border-b border-border relative select-none">
            <div className="flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-fg">
                <ListChecks size={16} className="text-accent" />
                Editar segmentos V2V
              </h3>
              <button
                type="button"
                onClick={() => setBulkEditorOpen(false)}
                className="p-1 rounded-lg hover:bg-bg-2 text-fg-muted hover:text-fg transition-colors"
                title="Cerrar editor de segmentos"
              >
                <X size={15} />
              </button>
            </div>
            <p className="text-[11px] text-fg-muted">
              Texto STT original frente al TTS, retraducción con Gemini y aplicar regeneración. El timeline permanece accesible debajo sin cerrarse.
            </p>
          </div>
          {/* Content */}
          <div className="px-5 py-3.5 overflow-y-auto min-h-0 flex-1">
            <V2VSegmentBulkEditor
              jobId={bulkEditorContext.jobId}
              videoIndex={bulkEditorContext.videoIndex}
              folder={bulkEditorContext.folder}
              targetLang={bulkEditorContext.targetLang}
              hideTitle
              inDialog
            />
          </div>
        </div>
      )}
    </>
  );
};
