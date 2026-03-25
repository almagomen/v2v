import React, { useCallback, useRef, useState } from "react";
import {
  Search,
  Maximize2,
  X,
  Image as ImageIcon,
  Film,
  Music,
  Folder,
  Plus,
  Pencil,
  Upload,
  Trash2,
  Square,
  Circle,
  Triangle,
  Star,
  ArrowRight,
  ArrowLeft,
  Hexagon,
  FileCode,
  AlertTriangle,
  RefreshCw,
  Palette,
  LayoutGrid,
  Grid2x2,
  List,
  Settings,
} from "lucide-react";
import {
  BACKGROUND_PRESETS,
  generateBackgroundBlob,
  type BackgroundPreset,
} from "../../services/background-generator";
import type { ShapeType } from "@openreel/core";
import { useProjectStore } from "../../stores/project-store";
import { useUIStore } from "../../stores/ui-store";
import { useV2VStore } from "../../stores/v2v-store";
import type { MediaItem } from "@openreel/core";
import { v2vApi, type AudioSegmentItem } from "../../lib/v2v-api";
import { autoSaveManager } from "../../services/auto-save";
import { importMultipleMediaIntoProject } from "../../utils/import-media-into-project";
import { toSafeToken } from "../../utils/v2v-utils";
import { AspectRatioMatchDialog } from "./dialogs/AspectRatioMatchDialog";
import { AIGenTab } from "./AIGenTab";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  IconButton,
  Input,
  ScrollArea,
} from "@openreel/ui";

const formatDuration = (seconds: number): string => {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins.toString().padStart(2, "0")}:${secs
    .toString()
    .padStart(2, "0")}`;
};


/** Copia blobs de Media de una carpeta `folder/…` a archivos para importar en otro proyecto. */
function collectFolderMediaFiles(items: MediaItem[], folder: string): File[] {
  const out: File[] = [];
  for (const m of items) {
    const idx = m.name.indexOf("/");
    if (idx <= 0) continue;
    if (m.name.slice(0, idx) !== folder) continue;
    if (!m.blob) continue;
    out.push(
      new File([m.blob], m.name, {
        type: m.blob.type || "application/octet-stream",
      }),
    );
  }
  return out;
}

function renameTimelineTrack(trackId: string, name: string) {
  useProjectStore.setState((state) => ({
    project: {
      ...state.project,
      timeline: {
        ...state.project.timeline,
        tracks: state.project.timeline.tracks.map((t) =>
          t.id === trackId ? { ...t, name } : t,
        ),
      },
    },
  }));
}

/** === Folder Timeline Snapshot Helpers === */

type FolderClipSnapshot = {
  mediaName: string; // nombre relativo (sin prefijo de carpeta) p.ej. "tts_voice_0001.wav"
  startTime: number;
  inPoint: number;
  outPoint: number;
  volume: number;
};

type FolderTrackSnapshot = {
  type: string;
  name: string;
  clips: FolderClipSnapshot[];
};

type FolderTimelineSnapshot = {
  folderName: string;
  tracks: FolderTrackSnapshot[];
  savedAt: number;
};

const SNAPSHOT_PREFIX = "or_folder_snapshot_";

function getFolderSnapshotKey(folder: string) {
  return `${SNAPSHOT_PREFIX}${folder.replace(/[^a-zA-Z0-9]/g, "_")}`;
}

function saveFolderSnapshot(snapshot: FolderTimelineSnapshot) {
  try {
    localStorage.setItem(
      getFolderSnapshotKey(snapshot.folderName),
      JSON.stringify(snapshot),
    );
  } catch (_) {}
}

function loadFolderSnapshot(folder: string): FolderTimelineSnapshot | null {
  try {
    const raw = localStorage.getItem(getFolderSnapshotKey(folder));
    return raw ? (JSON.parse(raw) as FolderTimelineSnapshot) : null;
  } catch (_) {
    return null;
  }
}

/**
 * Extrae los Tracks y Clips del proyecto actual que corresponden a archivos de la carpeta,
 * mapeando mediaId -> nombre relativo para que sobreviva al proyecto destino.
 */
function extractFolderTimelineSnapshot(
  folder: string,
): FolderTimelineSnapshot {
  const { project } = useProjectStore.getState();

  // Conjunto de mediaIds que pertenecen a esta carpeta
  const folderMediaMap = new Map<string, string>(); // id -> name relativo
  for (const m of project.mediaLibrary.items) {
    const idx = m.name.indexOf("/");
    if (idx <= 0) continue;
    if (m.name.slice(0, idx) !== folder) continue;
    folderMediaMap.set(m.id, m.name.slice(idx + 1)); // nombre sin el prefijo carpeta
  }

  const tracks: FolderTrackSnapshot[] = [];

  for (const track of project.timeline.tracks) {
    const filteredClips: FolderClipSnapshot[] = [];
    for (const clip of track.clips) {
      const relName = folderMediaMap.get(clip.mediaId);
      if (!relName) continue;
      filteredClips.push({
        mediaName: relName,
        startTime: clip.startTime,
        inPoint: clip.inPoint,
        outPoint: clip.outPoint,
        volume: clip.volume ?? 1,
      });
    }
    if (filteredClips.length > 0) {
      tracks.push({
        type: track.type,
        name: track.name,
        clips: filteredClips,
      });
    }
  }

  return { folderName: folder, tracks, savedAt: Date.now() };
}

/**
 * Media Item Thumbnail Component
 * Shows thumbnail with metadata below (not overlaid)
 */
type MediaViewMode = "large" | "small" | "list";

const MediaThumbnail: React.FC<{
  item: MediaItem;
  isSelected: boolean;
  viewMode: MediaViewMode;
  onSelect: () => void;
  onDelete: () => void;
  onReplace: () => void;
  onDragStart: (e: React.DragEvent) => void;
  onAddToTimeline: () => void;
}> = ({
  item,
  isSelected,
  viewMode,
  onSelect,
  onDelete,
  onReplace,
  onDragStart,
  onAddToTimeline,
}) => {
  const [isHovered, setIsHovered] = useState(false);

  const getIcon = () => {
    switch (item.type) {
      case "video":
        return Film;
      case "audio":
        return Music;
      case "image":
        return ImageIcon;
      default:
        return Film;
    }
  };

  const Icon = getIcon();

  const formatResolution = () => {
    if (item.metadata?.width && item.metadata?.height) {
      return `${item.metadata.width}×${item.metadata.height}`;
    }
    return null;
  };

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return null;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const iconColor = item.type === "audio"
    ? "text-primary/50"
    : item.type === "image"
      ? "text-primary/50"
      : "text-status-info/50";

  const borderClass = item.isPlaceholder
    ? "border-yellow-500 ring-1 ring-yellow-500/50 shadow-[0_0_10px_rgba(234,179,8,0.3)]"
    : isSelected
      ? "border-primary ring-1 ring-primary/50 shadow-[0_0_10px_rgba(34,197,94,0.2)]"
      : "border-border hover:border-text-secondary";

  const hoverOverlay = (
    <div className="absolute inset-0 bg-black/40 backdrop-blur-[1px] flex items-center justify-center gap-2 animate-in fade-in duration-200">
      {item.isPlaceholder ? (
        <button
          onClick={(e) => { e.stopPropagation(); onReplace(); }}
          title="Replace asset"
          className="p-2 bg-yellow-500/20 rounded-full hover:bg-yellow-500/40 backdrop-blur-sm transition-colors"
        >
          <RefreshCw size={14} className="text-yellow-500" />
        </button>
      ) : (
        <>
          <button
            onClick={(e) => { e.stopPropagation(); onAddToTimeline(); }}
            title="Add to timeline"
            className="p-2 bg-primary/20 rounded-full hover:bg-primary/40 backdrop-blur-sm transition-colors"
          >
            <Plus size={14} className="text-primary" />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            title="Delete"
            className="p-2 bg-red-500/20 rounded-full hover:bg-red-500/40 backdrop-blur-sm transition-colors"
          >
            <Trash2 size={14} className="text-red-400" />
          </button>
        </>
      )}
    </div>
  );

  // --- List view ---
  if (viewMode === "list") {
    return (
      <div
        draggable
        onDragStart={onDragStart}
        onClick={onSelect}
        onDoubleClick={(e) => { e.stopPropagation(); onAddToTimeline(); }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        className={`flex items-center gap-3 px-2 py-1.5 rounded-lg border-2 cursor-pointer transition-all group ${borderClass}`}
      >
        {/* Small thumbnail */}
        <div className="w-12 h-8 rounded bg-background-tertiary relative overflow-hidden flex-shrink-0">
          {item.thumbnailUrl ? (
            <img src={item.thumbnailUrl} alt={item.name} className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <Icon size={14} className={iconColor} />
            </div>
          )}
          {item.isPlaceholder && (
            <div className="absolute inset-0 flex items-center justify-center bg-yellow-500/10">
              <AlertTriangle size={12} className="text-yellow-500/70" />
            </div>
          )}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div
            className={`text-[11px] truncate font-medium ${isSelected ? "text-primary" : "text-text-primary"}`}
            title={item.name}
          >
            {item.name}
          </div>
          <div className="flex items-center gap-1.5 text-[9px] text-text-muted">
            {item.metadata?.duration && <span>{formatDuration(item.metadata.duration)}</span>}
            {item.metadata?.duration && formatResolution() && <span>•</span>}
            {formatResolution() && <span>{formatResolution()}</span>}
            {(item.metadata?.duration || formatResolution()) && formatFileSize(item.metadata?.fileSize) && <span>•</span>}
            {formatFileSize(item.metadata?.fileSize) && <span>{formatFileSize(item.metadata?.fileSize)}</span>}
          </div>
        </div>

        {/* Hover actions */}
        {isHovered && (
          <div className="flex items-center gap-1 flex-shrink-0">
            {item.isPlaceholder ? (
              <button
                onClick={(e) => { e.stopPropagation(); onReplace(); }}
                title="Replace asset"
                className="p-1 bg-yellow-500/20 rounded hover:bg-yellow-500/40 transition-colors"
              >
                <RefreshCw size={12} className="text-yellow-500" />
              </button>
            ) : (
              <>
                <button
                  onClick={(e) => { e.stopPropagation(); onAddToTimeline(); }}
                  title="Add to timeline"
                  className="p-1 bg-primary/20 rounded hover:bg-primary/40 transition-colors"
                >
                  <Plus size={12} className="text-primary" />
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); onDelete(); }}
                  title="Delete"
                  className="p-1 bg-red-500/20 rounded hover:bg-red-500/40 transition-colors"
                >
                  <Trash2 size={12} className="text-red-400" />
                </button>
              </>
            )}
          </div>
        )}

        {isSelected && (
          <div className="w-2 h-2 bg-primary rounded-full shadow-[0_0_8px_#22c55e] flex-shrink-0" />
        )}
      </div>
    );
  }

  // --- Grid view (large & small) ---
  const thumbnailIconSize = viewMode === "small" ? 16 : 24;

  return (
    <div className="flex flex-col">
      {/* Thumbnail container */}
      <div
        draggable
        onDragStart={onDragStart}
        onClick={onSelect}
        onDoubleClick={(e) => {
          e.stopPropagation();
          onAddToTimeline();
        }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        className={`aspect-video bg-background-tertiary rounded-lg border-2 relative group cursor-pointer transition-all overflow-hidden shadow-sm ${borderClass}`}
      >
        {/* Thumbnail or placeholder */}
        {item.thumbnailUrl ? (
          <img
            src={item.thumbnailUrl}
            alt={item.name}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center bg-background-tertiary">
            <Icon size={thumbnailIconSize} className={iconColor} />
          </div>
        )}

        {/* Audio waveform placeholder */}
        {item.type === "audio" && (
          <div className="absolute top-1/2 left-0 right-0 h-4 flex items-center gap-px px-2 -translate-y-1/2">
            {[...Array(10)].map((_, i) => (
              <div
                key={i}
                className="flex-1 bg-primary/30 rounded-full"
                style={{ height: `${Math.random() * 100}%` }}
              />
            ))}
          </div>
        )}

        {/* Missing Asset Badge */}
        {item.isPlaceholder && (
          <div className="absolute top-1 left-1 px-1.5 py-0.5 bg-yellow-500 rounded text-[8px] text-black font-bold flex items-center gap-1">
            <AlertTriangle size={10} />
            Missing
          </div>
        )}

        {/* Duration badge on thumbnail */}
        {item.metadata?.duration && (
          <div className="absolute bottom-1 right-1 px-1.5 py-0.5 bg-black/70 rounded text-[9px] text-white font-mono">
            {formatDuration(item.metadata.duration)}
          </div>
        )}

        {/* Warning icon overlay for placeholders */}
        {item.isPlaceholder && !isHovered && (
          <div className="absolute inset-0 flex items-center justify-center bg-yellow-500/10">
            <AlertTriangle size={viewMode === "small" ? 20 : 32} className="text-yellow-500/50" />
          </div>
        )}

        {/* Hover overlay with actions */}
        {isHovered && hoverOverlay}

        {/* Selection indicator */}
        {isSelected && (
          <div className="absolute top-1 right-1 w-2 h-2 bg-primary rounded-full shadow-[0_0_8px_#22c55e]" />
        )}
      </div>

      {/* Metadata below thumbnail */}
      <div className="mt-1.5 px-0.5">
        <div
          className={`text-[10px] truncate font-medium ${
            isSelected ? "text-primary" : "text-text-primary"
          }`}
          title={item.name}
        >
          {item.name}
        </div>
        {viewMode === "large" && (
          <div className="flex items-center gap-1.5 text-[9px] text-text-muted mt-0.5">
            {formatResolution() && <span>{formatResolution()}</span>}
            {formatResolution() && formatFileSize(item.metadata?.fileSize) && (
              <span>•</span>
            )}
            {formatFileSize(item.metadata?.fileSize) && (
              <span>{formatFileSize(item.metadata?.fileSize)}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const EmptyState: React.FC<{ onImport: () => void }> = ({ onImport }) => (
  <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
    <div className="w-16 h-16 rounded-2xl bg-background-tertiary border border-border flex items-center justify-center mb-4 shadow-inner">
      <Upload size={24} className="text-text-muted" />
    </div>
    <p className="text-sm text-text-secondary mb-2 font-medium">
      No media imported
    </p>
    <p className="text-xs text-text-muted mb-6">
      Drag files here or click to import
    </p>
    <button
      onClick={onImport}
      className="px-4 py-2 bg-background-elevated hover:bg-background-tertiary border border-border text-text-primary text-xs font-medium rounded-lg transition-all hover:border-primary/50"
    >
      Import Media
    </button>
  </div>
);

const LoadingIndicator: React.FC<{ message: string }> = ({ message }) => (
  <div className="absolute inset-0 bg-background-secondary/90 backdrop-blur-sm flex flex-col items-center justify-center z-50">
    <div className="w-10 h-10 border-2 border-primary border-t-transparent rounded-full animate-spin mb-3" />
    <p className="text-sm text-text-secondary">{message}</p>
  </div>
);

export const AssetsPanel: React.FC = () => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<
    "media" | "text" | "graphics" | "ai"
  >("media");
  const [activeFolder, setActiveFolder] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [draggedOverFolder, setDraggedOverFolder] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [importProgress, setImportProgress] = useState("");
  const [showOnlyMissing, setShowOnlyMissing] = useState(false);
  const [showAspectRatioDialog, setShowAspectRatioDialog] = useState(false);
  const [aspectRatioDialogData, setAspectRatioDialogData] = useState<{
    videoWidth: number;
    videoHeight: number;
    itemToAdd: MediaItem;
  } | null>(null);
  const [mediaViewMode, setMediaViewMode] = useState<MediaViewMode>("large");
  const [generatingBackground, setGeneratingBackground] = useState<
    string | null
  >(null);
  const [backgroundCategory, setBackgroundCategory] = useState<
    "all" | "solid" | "gradient" | "pattern" | "mesh"
  >("all");
  const [showCopyProjectModal, setShowCopyProjectModal] = useState(false);
  const [copyTargets, setCopyTargets] = useState<
    Array<{ id: string; name: string; subtitle: string; isCurrent: boolean }>
  >([]);
  const [copyingTargetId, setCopyingTargetId] = useState<string | null>(null);

  // Project store
  const {
    project,
    importMedia,
    deleteMedia,
    replaceMediaAsset,
    renameMedia,
    updateSettings,
    addTrack,
    addClip,
    trimClip,
    forceSave,
  } = useProjectStore();
  const mediaItems = project.mediaLibrary.items;

  // UI store
  const { select, isSelected, startDrag } = useUIStore();

  // Count missing assets
  const missingAssetsCount = mediaItems.filter(
    (item) => item.isPlaceholder,
  ).length;

  const getFolderName = (name: string): string | null => {
    const idx = name.indexOf("/");
    if (idx <= 0) return null;
    return name.slice(0, idx);
  };

  const getDisplayName = (name: string): string => {
    const idx = name.indexOf("/");
    return idx >= 0 ? name.slice(idx + 1) : name;
  };

  const folders = Array.from(
    new Set(
      mediaItems
        .map((m) => getFolderName(m.name))
        .filter((x): x is string => Boolean(x)),
    ),
  ).sort((a, b) => a.localeCompare(b));

  const folderItems = activeFolder
    ? mediaItems.filter((m) => getFolderName(m.name) === activeFolder)
    : [];

  const baseItems = activeFolder
    ? folderItems
    : mediaItems.filter((m) => !getFolderName(m.name));

  // Filter media items by search query and missing assets toggle
  const filteredItems = baseItems.filter((item) => {
    const matchesSearch = item.name
      .toLowerCase()
      .includes(searchQuery.toLowerCase());
    const matchesFilter = showOnlyMissing ? item.isPlaceholder : true;
    return matchesSearch && matchesFilter;
  });

  const handleRenameFolder = useCallback(async () => {
    if (!activeFolder) return;
    const next = window.prompt("Nuevo nombre de carpeta", activeFolder);
    if (!next || !next.trim() || next.trim() === activeFolder) return;
    const newName = next.trim();
    const items = mediaItems.filter((m) => getFolderName(m.name) === activeFolder);
    for (const it of items) {
      const rest = getDisplayName(it.name);
      await renameMedia(it.id, `${newName}/${rest}`);
    }
    // Re-map de referencia para el botón "Añadir a la timeline".
    useV2VStore.getState().renameFolderRef(activeFolder, newName);
    setActiveFolder(newName);
  }, [activeFolder, mediaItems, renameMedia]);

  const handleDeleteFolder = useCallback(async () => {
    if (!activeFolder) return;
    const ok = window.confirm(`¿Borrar la carpeta "${activeFolder}" y todos sus archivos?`);
    if (!ok) return;
    const items = mediaItems.filter((m) => getFolderName(m.name) === activeFolder);
    for (const it of items) {
      await deleteMedia(it.id);
    }
    useV2VStore.getState().removeFolderRef(activeFolder);
    setActiveFolder(null);
  }, [activeFolder, mediaItems, deleteMedia]);

  // Handle file import with loading state
  const handleFileImport = useCallback(
    async (files: FileList | null, targetFolderOverride?: string) => {
      if (!files || files.length === 0) return;

      setIsImporting(true);
      const fileArray = Array.from(files);

      try {
        for (let i = 0; i < fileArray.length; i++) {
          let file = fileArray[i];
          
          const folderPrefix = targetFolderOverride || activeFolder;
          if (folderPrefix) {
            file = new File([file], `${folderPrefix}/${file.name}`, { type: file.type });
          }
          
          setImportProgress(
            `Importing ${file.name} (${i + 1}/${fileArray.length})...`,
          );

          const result = await importMedia(file);

          // If it's a video with audio, extract audio to separate track
          if (result.success && file.type.startsWith("video/")) {
            setImportProgress(`Extracting audio from ${file.name}...`);
            // Audio extraction is handled by the importMedia function
            // The audio track is created automatically when adding to timeline
          }
        }
      } catch (error) {
        console.error("Import failed:", error);
      } finally {
        setIsImporting(false);
        setImportProgress("");
      }
    },
    [importMedia, activeFolder],
  );

  const handleFolderDrop = useCallback(
    async (e: React.DragEvent, targetFolder: string) => {
      e.preventDefault();
      e.stopPropagation();
      setDraggedOverFolder(null);

      // Check external files first
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        return handleFileImport(e.dataTransfer.files, targetFolder);
      }

      // Handle internal media item
      const dataStr = e.dataTransfer.getData("application/json");
      if (!dataStr) return;
      
      try {
        const { mediaId } = JSON.parse(dataStr);
        if (mediaId && mediaId.length > 0) {
          const mediaItem = project.mediaLibrary.items.find(m => m.id === mediaId);
          if (!mediaItem) return;
          
          // Recreate proper file path inside chosen folder
          const currentName = mediaItem.name;
          const nameWithoutPrefix = currentName.includes("/") 
            ? currentName.substring(currentName.lastIndexOf("/") + 1) 
            : currentName;
            
          const newName = `${targetFolder}/${nameWithoutPrefix}`;
          if (currentName !== newName) {
            await renameMedia(mediaId, newName);
          }
        }
      } catch (err) {
        console.error("Failed to parse dragged media", err);
      }
    },
    [handleFileImport, project.mediaLibrary.items, renameMedia]
  );

  const handleRootDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDraggedOverFolder(null);

      const dataStr = e.dataTransfer.getData("application/json");
      if (!dataStr) return;
      
      try {
        const { mediaId } = JSON.parse(dataStr);
        if (mediaId && mediaId.length > 0) {
          const mediaItem = project.mediaLibrary.items.find(m => m.id === mediaId);
          if (!mediaItem) return;
          
          const currentName = mediaItem.name;
          const nameWithoutPrefix = currentName.includes("/") 
            ? currentName.substring(currentName.lastIndexOf("/") + 1) 
            : currentName;
            
          const newName = nameWithoutPrefix;
          if (currentName !== newName) {
            await renameMedia(mediaId, newName);
          }
        }
      } catch (err) {
        console.error("Failed to parse dragged media", err);
      }
    },
    [project.mediaLibrary.items, renameMedia]
  );

  const handleFolderDragOver = useCallback((e: React.DragEvent, folder: string) => {
    e.preventDefault();
    e.stopPropagation();
    setDraggedOverFolder(folder);
  }, []);

  const handleFolderDragLeave = useCallback(() => {
    setDraggedOverFolder(null);
  }, []);

  // Handle drag and drop import
  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      handleFileImport(e.dataTransfer.files);
    },
    [handleFileImport],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);

    const container = e.currentTarget as HTMLElement;
    const viewport = container.querySelector('[data-radix-scroll-area-viewport]') as HTMLElement || container;
    
    const rect = container.getBoundingClientRect();
    const threshold = 60;
    const maxSpeed = 15;

    const distTop = e.clientY - rect.top;
    const distBottom = rect.bottom - e.clientY;

    if (distTop < threshold && distTop > 0) {
      const speed = maxSpeed * (1 - distTop / threshold);
      viewport.scrollTop -= speed;
    } else if (distBottom < threshold && distBottom > 0) {
      const speed = maxSpeed * (1 - distBottom / threshold);
      viewport.scrollTop += speed;
    }
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  // Handle media item selection
  const handleSelectItem = useCallback(
    (itemId: string) => {
      select({ type: "clip", id: itemId });
    },
    [select],
  );

  // Handle media item deletion
  const handleDeleteItem = useCallback(
    async (itemId: string) => {
      await deleteMedia(itemId);
    },
    [deleteMedia],
  );

  // Handle asset replacement
  const handleReplaceAsset = useCallback(
    async (itemId: string) => {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "video/*,audio/*,image/*";
      input.onchange = async (e) => {
        const file = (e.target as HTMLInputElement).files?.[0];
        if (file) {
          setIsImporting(true);
          setImportProgress(`Replacing asset...`);
          try {
            await replaceMediaAsset(itemId, file);
          } catch (error) {
            console.error("Asset replacement failed:", error);
          } finally {
            setIsImporting(false);
            setImportProgress("");
          }
        }
      };
      input.click();
    },
    [replaceMediaAsset],
  );

  // Handle drag start for timeline placement
  const handleItemDragStart = useCallback(
    (e: React.DragEvent, item: MediaItem) => {
      e.dataTransfer.setData(
        "application/json",
        JSON.stringify({ mediaId: item.id }),
      );
      e.dataTransfer.effectAllowed = "copy";
      startDrag("media", { mediaId: item.id, mediaType: item.type });
    },
    [startDrag],
  );

  const addMediaToTimeline = useCallback(async (item: MediaItem) => {
    const { addClipToNewTrack } = useProjectStore.getState();
    await addClipToNewTrack(item.id);
  }, []);

  const handleConfirmAspectRatioMatch = useCallback(async () => {
    if (!aspectRatioDialogData) return;

    await updateSettings({
      width: aspectRatioDialogData.videoWidth,
      height: aspectRatioDialogData.videoHeight,
    });

    const itemToAdd = aspectRatioDialogData.itemToAdd;
    setShowAspectRatioDialog(false);
    setAspectRatioDialogData(null);

    await addMediaToTimeline(itemToAdd);
  }, [aspectRatioDialogData, updateSettings, addMediaToTimeline]);

  const handleCancelAspectRatioMatch = useCallback(async () => {
    if (!aspectRatioDialogData) return;

    const itemToAdd = aspectRatioDialogData.itemToAdd;
    setShowAspectRatioDialog(false);
    setAspectRatioDialogData(null);

    await addMediaToTimeline(itemToAdd);
  }, [aspectRatioDialogData, addMediaToTimeline]);

  const handleAddToTimeline = useCallback(
    async (item: MediaItem) => {
      const { project: currentProject } = useProjectStore.getState();
      const tracks = currentProject.timeline.tracks;
      const hasClips = tracks.some((track) => track.clips.length > 0);

      if (
        !hasClips &&
        item.type === "video" &&
        item.metadata?.width &&
        item.metadata?.height
      ) {
        const videoWidth = item.metadata.width;
        const videoHeight = item.metadata.height;
        const projectWidth = currentProject.settings.width;
        const projectHeight = currentProject.settings.height;

        if (videoWidth !== projectWidth || videoHeight !== projectHeight) {
          setAspectRatioDialogData({ videoWidth, videoHeight, itemToAdd: item });
          setShowAspectRatioDialog(true);
          return;
        }
      }

      await addMediaToTimeline(item);
    },
    [addMediaToTimeline],
  );

  /** Descarga/importa a Media el video y WAV del job V2V. Devuelve los segmentos del backend. */
  const ensureV2VMediaInProject = useCallback(
    async (folder: string, ref: { jobId: string; videoIndex: number }) => {
      const segments: AudioSegmentItem[] = await v2vApi.getAudioSegments(
        ref.jobId,
        ref.videoIndex,
      );

      const videoMediaName = `${folder}/video.mp4`;
      const refreshState = () => useProjectStore.getState();
      const currentItems = refreshState().project.mediaLibrary.items;
      const mediaNames = new Set(currentItems.map((m) => m.name));

      // 1) Identificamos qué archivos faltan
      const missingFilesInfo: { type: 'video' | 'audio', name: string, seg?: number }[] = [];
      if (!mediaNames.has(videoMediaName)) {
        missingFilesInfo.push({ type: 'video', name: videoMediaName });
      }

      for (const seg of segments) {
        const wavName = `${folder}/tts_${toSafeToken(seg.speaker || "speaker")}_${String(seg.seg).padStart(4, "0")}.wav`;
        if (!mediaNames.has(wavName)) {
          missingFilesInfo.push({ type: 'audio', name: wavName, seg: seg.seg });
        }
      }

      if (missingFilesInfo.length > 0) {
        // 2) Descarga en paralelo
        const downloadTasks = missingFilesInfo.map(info => {
          if (info.type === 'video') {
            return v2vApi.fetchOutputVideoBlob(ref.jobId, ref.videoIndex)
              .then(blob => new File([blob], info.name, { type: "video/mp4" }));
          } else {
            return v2vApi.fetchAudioSegmentBlob(ref.jobId, ref.videoIndex, info.seg!)
              .then(blob => new File([blob], info.name, { type: "audio/wav" }));
          }
        });

        const filesToImport = await Promise.all(downloadTasks);
        
        // 3) Importación masiva
        const batchRes = await importMultipleMediaIntoProject(refreshState().project, filesToImport, { quick: true });
        if (!batchRes.success) {
           throw new Error("Error en la importación masiva de la carpeta");
        }
        // Actualizamos el proyecto en el store (ya que importMultiple lo crea desconectado)
        // NOTA: Como estamos en un callback de AssetsPanel, usamos importMedia o similar si queremos persistencia, 
        // pero aquí el patrón es que importMultiple devuelve el nuevo proyecto y nosotros lo inyectamos.
        // En AssetsPanel no tenemos un setProject directo, dependemos de importMedia. 
        // Sin embargo, podemos usar el patrón de 'ProjectStore.setState({ project: batchRes.project })' o similar si es accesible.
        // Revisando useProjectStore...
        useProjectStore.setState({ project: batchRes.project });
      }

      return segments;
    },
    [importMedia],
  );

  const importFolderTtsViaApi = useCallback(
    async (folder: string, ref: { jobId: string; videoIndex: number }) => {
      setIsImporting(true);
      setImportProgress("Copiando carpeta al proyecto seleccionado...");
      try {
        await ensureV2VMediaInProject(folder, ref);
      } catch (e) {
        window.alert(e instanceof Error ? e.message : "Error al importar media");
      } finally {
        setIsImporting(false);
        setImportProgress("");
      }
    },
    [ensureV2VMediaInProject],
  );

  /**
   * Añade nuevas pistas al timeline actual: video a t=0 y audios por speaker con start/end del backend.
   */
  const handleAddV2VFolderAsNewTracks = useCallback(async () => {
    if (!activeFolder) return;
    const ref = useV2VStore.getState().getFolderRef(activeFolder);

    // Comprobar si existe un snapshot guardado para esta carpeta
    const snapshot = loadFolderSnapshot(activeFolder);
    if (snapshot && snapshot.tracks.length > 0) {
      setIsImporting(true);
      setImportProgress("Restaurando pistas desde snapshot guardado…");
      try {
        if (ref) {
          await ensureV2VMediaInProject(activeFolder, ref);
        }
        const folder = activeFolder;

        for (const trackSnap of snapshot.tracks) {
          // Crear la pista
          const beforeIds = new Set(
            useProjectStore.getState().project.timeline.tracks.map((t) => t.id),
          );
          const rT = await addTrack(trackSnap.type as "video" | "audio" | "image");
          if (!rT.success) continue;

          const proj = useProjectStore.getState().project;
          const newTrack = proj.timeline.tracks.find(
            (t) => !beforeIds.has(t.id),
          );
          if (!newTrack) continue;

          renameTimelineTrack(newTrack.id, trackSnap.name);

          // Añadir clips
          for (const clipSnap of trackSnap.clips) {
            const mediaName = `${folder}/${clipSnap.mediaName}`;
            const wm = useProjectStore
              .getState()
              .project.mediaLibrary.items.find((m) => m.name === mediaName);
            if (!wm) continue;

            const addR = await addClip(newTrack.id, wm.id, clipSnap.startTime);
            if (!addR.success) continue;

            // Restaurar recorte
            const updatedClip = useProjectStore
              .getState()
              .project.timeline.tracks.find((t) => t.id === newTrack.id)
              ?.clips.find(
                (c) =>
                  c.mediaId === wm.id &&
                  Math.abs(c.startTime - clipSnap.startTime) < 0.05,
              );
            if (updatedClip) {
              await trimClip(updatedClip.id, clipSnap.inPoint, clipSnap.outPoint);
            }
          }
        }
        await forceSave();
      } catch (e) {
        window.alert(e instanceof Error ? e.message : "Error al restaurar snapshot");
      } finally {
        setIsImporting(false);
        setImportProgress("");
      }
      return; // salir después de restaurar desde snapshot
    }

    if (!ref) {
      window.alert(
        `No hay referencia V2V para "${activeFolder}". Procesa el video desde Video2Video (icono YouTube) o vuelve a ejecutar la inferencia.`,
      );
      return;
    }

    setIsImporting(true);
    setImportProgress("Sincronizando Media y añadiendo pistas al timeline…");
    try {
      const segments = await ensureV2VMediaInProject(activeFolder, ref);
      const folder = activeFolder;
      const videoName = `${folder}/video.mp4`;

      const videoMedia = useProjectStore
        .getState()
        .project.mediaLibrary.items.find((m) => m.name === videoName);
      if (!videoMedia) {
        window.alert(`No se encuentra "${videoName}" en Media.`);
        return;
      }

      let proj = useProjectStore.getState().project;
      const beforeVideo = new Set(proj.timeline.tracks.map((t) => t.id));
      const rVideo = await addTrack("video");
      if (!rVideo.success) {
        window.alert("No se pudo crear la pista de video.");
        return;
      }
      proj = useProjectStore.getState().project;
      const videoTrack = proj.timeline.tracks.find(
        (t) => t.type === "video" && !beforeVideo.has(t.id),
      );
      if (!videoTrack) {
        window.alert("No se encontró la pista de video nueva.");
        return;
      }

      const folderLabel = folder.length > 52 ? `${folder.slice(0, 49)}…` : folder;
      renameTimelineTrack(videoTrack.id, `V2V · ${folderLabel}`);

      const addV = await addClip(videoTrack.id, videoMedia.id, 0);
      if (!addV.success) {
        window.alert("No se pudo añadir el clip de video.");
        return;
      }

      const vDur =
        videoMedia.metadata?.duration && videoMedia.metadata.duration > 0
          ? videoMedia.metadata.duration
          : undefined;
      if (vDur) {
        proj = useProjectStore.getState().project;
        const vt = proj.timeline.tracks.find((t) => t.id === videoTrack.id);
        const vClip = vt?.clips.find((c) => c.mediaId === videoMedia.id);
        if (vClip) await trimClip(vClip.id, 0, vDur);
      }

      const bySpeaker: Record<string, AudioSegmentItem[]> = {};
      for (const seg of segments) {
        const raw = (seg.speaker || "").trim();
        const key = raw || `TTS_${toSafeToken(seg.speaker || "speaker")}_seg${seg.seg}`;
        (bySpeaker[key] ||= []).push(seg);
      }

      for (const speakerKey of Object.keys(bySpeaker)) {
        const segs = bySpeaker[speakerKey].slice().sort((a, b) => a.seg - b.seg);
        const beforeA = new Set(
          useProjectStore.getState().project.timeline.tracks.map((t) => t.id),
        );
        const rA = await addTrack("audio");
        if (!rA.success) continue;

        proj = useProjectStore.getState().project;
        const audioTrack = proj.timeline.tracks.find(
          (t) => t.type === "audio" && !beforeA.has(t.id),
        );
        if (!audioTrack) continue;

        const displaySpeaker = (segs[0]?.speaker || "").trim();
        const trackTitle =
          displaySpeaker.length > 0
            ? displaySpeaker.length > 80
              ? `${displaySpeaker.slice(0, 77)}…`
              : displaySpeaker
            : speakerKey;

        renameTimelineTrack(audioTrack.id, trackTitle);

        for (const seg of segs) {
          const wavName = `${folder}/tts_${toSafeToken(seg.speaker || "speaker")}_${String(
            seg.seg,
          ).padStart(4, "0")}.wav`;
          const wm = useProjectStore
            .getState()
            .project.mediaLibrary.items.find((m) => m.name === wavName);
          if (!wm) continue;

          const addW = await addClip(audioTrack.id, wm.id, seg.start);
          if (!addW.success) continue;

          proj = useProjectStore.getState().project;
          const tr = proj.timeline.tracks.find((t) => t.id === audioTrack.id);
          const clipOnTrack = tr?.clips.find(
            (c) => c.mediaId === wm.id && Math.abs(c.startTime - seg.start) < 0.05,
          );
          if (!clipOnTrack) continue;

          const mediaDur =
            wm.metadata?.duration && wm.metadata.duration > 0
              ? wm.metadata.duration
              : clipOnTrack.duration;
          if (mediaDur > 0) {
            await trimClip(clipOnTrack.id, 0, mediaDur);
          }
        }
      }

      await forceSave();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "Error al montar en el timeline");
    } finally {
      setIsImporting(false);
      setImportProgress("");
    }
  }, [activeFolder, addTrack, addClip, trimClip, ensureV2VMediaInProject, forceSave]);

  const handleCopyFolderTtsToAnotherProject = useCallback(async () => {
    if (!activeFolder) return;

    try {
      await autoSaveManager.initialize();
      const saves = await autoSaveManager.checkForRecovery();

      // Deduplicamos por projectId y nos quedamos con el más reciente.
      const unique = saves.reduce((acc, save) => {
        const existing = acc.find((x) => x.projectId === save.projectId);
        if (!existing || save.timestamp > existing.timestamp) {
          return [...acc.filter((x) => x.projectId !== save.projectId), save];
        }
        return acc;
      }, [] as typeof saves);

      const ordered = unique.sort((a, b) => b.timestamp - a.timestamp);
      const currentProjectId = useProjectStore.getState().project.id;
      const targets: Array<{ id: string; name: string; subtitle: string; isCurrent: boolean }> = [];

      for (const p of ordered) {
        if (p.projectId === currentProjectId) continue;
        targets.push({
          id: p.id,
          name: p.projectName,
          subtitle: "Proyecto reciente",
          isCurrent: false,
        });
      }

      if (targets.length === 0) {
        window.alert("No hay proyectos disponibles para copiar.");
        return;
      }

      setCopyTargets(targets);
      setShowCopyProjectModal(true);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "Error al copiar a proyecto");
    }
  }, [activeFolder]);

  const handleConfirmCopyToTarget = useCallback(
    async (targetId: string) => {
      if (!activeFolder) return;
      setCopyingTargetId(targetId);
      try {
        // Guardar el snapshot de Timeline de la carpeta ANTES de cambiar de proyecto
        const snapshot = extractFolderTimelineSnapshot(activeFolder);
        saveFolderSnapshot(snapshot);

        const snapshotFiles = collectFolderMediaFiles(
          useProjectStore.getState().project.mediaLibrary.items,
          activeFolder,
        );
        const ref = useV2VStore.getState().getFolderRef(activeFolder);

        if (targetId !== "__current__") {
          await useProjectStore.getState().recoverFromAutoSave(targetId);
        }

        if (ref) {
          await importFolderTtsViaApi(activeFolder, ref);
        } else {
          if (snapshotFiles.length === 0) {
            window.alert(
              "No hay archivos locales en esta carpeta (o faltan blobs). Ejecuta otra vez la inferencia desde Video2Video para registrar la referencia, o importa los archivos manualmente.",
            );
            return;
          }
          
          const filesToImport = snapshotFiles.filter(file => {
            return !useProjectStore.getState().project.mediaLibrary.items.some(m => m.name === file.name);
          });

          if (filesToImport.length > 0) {
            const batchRes = await importMultipleMediaIntoProject(useProjectStore.getState().project, filesToImport, { quick: true });
            if (batchRes.success) {
              useProjectStore.setState({ project: batchRes.project });
            }
          }
        }

        setShowCopyProjectModal(false);
      } catch (e) {
        window.alert(e instanceof Error ? e.message : "Error al copiar a proyecto");
      } finally {
        setCopyingTargetId(null);
      }
    },
    [activeFolder, importFolderTtsViaApi],
  );

  const triggerFileInput = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleImportBackground = useCallback(
    async (preset: BackgroundPreset) => {
      setGeneratingBackground(preset.id);
      try {
        const { width, height } = project.settings;
        const blob = await generateBackgroundBlob(preset, width, height);
        const file = new File([blob], `${preset.name}_${width}x${height}.png`, {
          type: "image/png",
        });
        const result = await importMedia(file);
        if (result.success && result.actionId) {
          const { addClipToNewTrack } = useProjectStore.getState();
          await addClipToNewTrack(result.actionId);
        }
      } catch (error) {
        console.error("Failed to generate background:", error);
      } finally {
        setGeneratingBackground(null);
      }
    },
    [importMedia, project.settings],
  );

  const filteredBackgrounds = BACKGROUND_PRESETS.filter(
    (preset) =>
      backgroundCategory === "all" || preset.category === backgroundCategory,
  );

  return (
    <div
      data-tour="assets"
      className="w-80 bg-background-secondary border-r border-border flex flex-col h-full relative"
    >
      {/* Loading overlay */}
      {isImporting && (
        <LoadingIndicator message={importProgress || "Importing media..."} />
      )}
      {/* Panel Header */}
      <div className="px-5 py-4 flex items-center justify-between">
        <span className="font-bold text-lg text-text-primary tracking-tight">
          Assets
        </span>
        <div className="flex gap-1">
          <IconButton
            icon={Plus}
            onClick={triggerFileInput}
            title="Import media"
          />
          <IconButton icon={Maximize2} title="Maximize panel" />
          <IconButton icon={X} title="Close panel" />
        </div>
      </div>

      {/* Tabs */}
      <div className="flex px-5 gap-6 border-b border-border text-xs font-medium text-text-muted mb-5">
        <button
          onClick={() => setActiveTab("media")}
          className={`pb-3 transition-all relative ${
            activeTab === "media"
              ? "text-text-primary"
              : "hover:text-text-secondary"
          }`}
        >
          Media
          {activeTab === "media" && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary rounded-t-full shadow-[0_-2px_8px_rgba(34,197,94,0.5)]" />
          )}
        </button>
        <button
          onClick={() => setActiveTab("text")}
          className={`pb-3 transition-all relative ${
            activeTab === "text"
              ? "text-text-primary"
              : "hover:text-text-secondary"
          }`}
        >
          Text
          {activeTab === "text" && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary rounded-t-full shadow-[0_-2px_8px_rgba(34,197,94,0.5)]" />
          )}
        </button>
        <button
          onClick={() => setActiveTab("graphics")}
          className={`pb-3 transition-all relative ${
            activeTab === "graphics"
              ? "text-text-primary"
              : "hover:text-text-secondary"
          }`}
        >
          Graphics
          {activeTab === "graphics" && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary rounded-t-full shadow-[0_-2px_8px_rgba(34,197,94,0.5)]" />
          )}
        </button>
        <button
          onClick={() => setActiveTab("ai")}
          className={`pb-3 transition-all relative ${
            activeTab === "ai"
              ? "text-primary"
              : "text-primary/70 hover:text-primary"
          }`}
        >
          AI Gen
          {activeTab === "ai" && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary rounded-t-full shadow-[0_-2px_8px_rgba(34,197,94,0.5)]" />
          )}
        </button>
      </div>

      {/* Search & view toggle - only show for media tab */}
      {activeTab === "media" && (
        <div className="px-5 mb-3 flex items-center gap-2">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted z-10" />
            <Input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={activeFolder ? `Buscar en ${activeFolder}` : "Search media"}
              className="pl-9 text-xs bg-background-tertiary border-border text-text-primary h-9"
            />
          </div>
          <div className="flex items-center bg-background-tertiary border border-border rounded-lg p-0.5">
            {([
              { mode: "large" as const, icon: LayoutGrid, title: "Large icons" },
              { mode: "small" as const, icon: Grid2x2, title: "Small icons" },
              { mode: "list" as const, icon: List, title: "List view" },
            ]).map(({ mode, icon: ViewIcon, title }) => (
              <button
                key={mode}
                onClick={() => setMediaViewMode(mode)}
                title={title}
                className={`p-1.5 rounded transition-colors ${
                  mediaViewMode === mode
                    ? "bg-background-elevated text-text-primary"
                    : "text-text-muted hover:text-text-secondary"
                }`}
              >
                <ViewIcon size={13} />
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Missing Assets Filter and Badge */}
      {activeTab === "media" && missingAssetsCount > 0 && (
        <div className="px-5 mb-5 space-y-2">
          <button
            onClick={() => setShowOnlyMissing(!showOnlyMissing)}
            className={`w-full px-3 py-2 rounded-lg border text-xs font-medium transition-all flex items-center justify-between ${
              showOnlyMissing
                ? "bg-yellow-500/10 border-yellow-500 text-yellow-500"
                : "bg-background-tertiary border-border text-text-secondary hover:border-yellow-500/50"
            }`}
          >
            <div className="flex items-center gap-2">
              <AlertTriangle size={14} />
              <span>Show Only Missing Assets</span>
            </div>
            <div className="px-2 py-0.5 rounded-full bg-yellow-500 text-black text-[10px] font-bold">
              {missingAssetsCount}
            </div>
          </button>
        </div>
      )}

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="video/*,audio/*,image/*"
        onChange={(e) => handleFileImport(e.target.files)}
        className="hidden"
      />

      {/* Content based on active tab */}
      {activeTab === "media" && (
        <ScrollArea
          className={`flex-1 ${isDragOver ? "bg-primary/5" : ""}`}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
        >
          <div className="px-5 pb-5">
            {/* Folder bar */}
            {activeFolder ? (
              <div className="flex items-center gap-2 mb-3">
                <button
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
                  title="Volver a la raíz (Suelta archivos aquí para sacarlos)"
                >
                  <ArrowLeft size={14} />
                </button>
                <div className="flex-1 text-[11px] text-text-primary truncate" title={activeFolder}>
                  {activeFolder}
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={handleRenameFolder}
                    className="p-1 rounded bg-background-tertiary border border-border hover:border-primary/50 text-text-muted"
                    title="Renombrar"
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    onClick={handleDeleteFolder}
                    className="p-1 rounded bg-background-tertiary border border-border hover:border-red-500/50 text-red-400"
                    title="Borrar"
                  >
                    <Trash2 size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleCopyFolderTtsToAnotherProject()}
                    className="p-1 rounded bg-primary/15 border border-primary/30 hover:border-primary/50 text-primary"
                    title="Opciones de carpeta"
                  >
                    <Settings size={14} />
                  </button>
                </div>
              </div>
            ) : folders.length > 0 ? (
              <div className="grid grid-cols-2 gap-3 mb-4">
                {folders.map((f) => (
                  <button
                    key={f}
                    onClick={() => setActiveFolder(f)}
                    onDragOver={(e) => handleFolderDragOver(e, f)}
                    onDragLeave={handleFolderDragLeave}
                    onDrop={(e) => handleFolderDrop(e, f)}
                    className={`aspect-video bg-background-tertiary rounded-lg border-2 transition-all flex flex-col items-center justify-center gap-1.5 ${
                      draggedOverFolder === f 
                        ? "border-primary bg-primary/10 shadow-[0_0_15px_rgba(108,99,255,0.4)]" 
                        : "border-border hover:border-primary/50"
                    }`}
                    title={f}
                  >
                    <Folder size={22} className={draggedOverFolder === f ? "text-primary" : "text-text-muted"} />
                    <span className={`text-[10px] truncate max-w-[120px] ${draggedOverFolder === f ? "text-primary" : "text-text-secondary"}`}>
                      {f}
                    </span>
                    <span className="text-[9px] text-text-muted">
                      {mediaItems.filter((m) => getFolderName(m.name) === f).length} items
                    </span>
                  </button>
                ))}
              </div>
            ) : null}

            {filteredItems.length === 0 ? (
              <EmptyState onImport={triggerFileInput} />
            ) : (
              <div className={
                mediaViewMode === "list"
                  ? "flex flex-col gap-1.5"
                  : mediaViewMode === "small"
                    ? "grid grid-cols-3 gap-2"
                    : "grid grid-cols-2 gap-3"
              }>
                {filteredItems.map((item) => (
                  <MediaThumbnail
                    key={item.id}
                    item={{ ...item, name: getDisplayName(item.name) }}
                    isSelected={isSelected(item.id)}
                    viewMode={mediaViewMode}
                    onSelect={() => handleSelectItem(item.id)}
                    onDelete={() => handleDeleteItem(item.id)}
                    onReplace={() => handleReplaceAsset(item.id)}
                    onDragStart={(e) => handleItemDragStart(e, item)}
                    onAddToTimeline={() => handleAddToTimeline(item)}
                  />
                ))}
                {/* Add more media tile */}
                {mediaViewMode === "list" ? (
                  <button
                    onClick={triggerFileInput}
                    className="flex items-center gap-3 px-2 py-1.5 rounded-lg border-2 border-dashed border-border hover:border-text-secondary cursor-pointer transition-all group"
                  >
                    <div className="w-12 h-8 rounded bg-background-tertiary flex items-center justify-center flex-shrink-0">
                      <Upload size={14} className="text-text-muted group-hover:text-text-secondary transition-colors" />
                    </div>
                    <span className="text-[11px] text-text-muted group-hover:text-text-secondary transition-colors font-medium">Add media</span>
                  </button>
                ) : (
                  <div className="flex flex-col">
                    <button
                      onClick={triggerFileInput}
                      className="aspect-video bg-background-tertiary rounded-lg border-2 border-dashed border-border hover:border-text-secondary relative flex items-center justify-center cursor-pointer transition-all overflow-hidden shadow-sm group"
                    >
                      <div className="flex flex-col items-center gap-1.5">
                        <Upload size={mediaViewMode === "small" ? 16 : 20} className="text-text-muted group-hover:text-text-secondary transition-colors" />
                        <span className="text-[10px] text-text-muted group-hover:text-text-secondary transition-colors">Add media</span>
                      </div>
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Drop zone indicator */}
            {isDragOver && (
              <div className="absolute inset-4 border-2 border-dashed border-primary rounded-xl flex items-center justify-center bg-primary/5 pointer-events-none z-50 backdrop-blur-sm">
                <div className="text-primary text-sm font-bold bg-background-secondary px-4 py-2 rounded-full shadow-lg">
                  Drop files to import
                </div>
              </div>
            )}
          </div>
        </ScrollArea>
      )}

      {/* Graphics Tab Content (Task 16) */}
      {activeTab === "graphics" && (
        <ScrollArea className="flex-1">
          <div className="px-5 pb-5">
          {/* Backgrounds Section */}
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-xs font-medium text-text-secondary flex items-center gap-1.5">
                <Palette size={12} />
                Backgrounds
              </h4>
            </div>
            <div className="flex gap-1.5 mb-3 flex-wrap">
              {(["all", "solid", "gradient", "mesh", "pattern"] as const).map(
                (cat) => (
                  <button
                    key={cat}
                    onClick={() => setBackgroundCategory(cat)}
                    className={`px-2.5 py-1 text-[10px] rounded-md transition-all ${
                      backgroundCategory === cat
                        ? "bg-primary text-white"
                        : "bg-background-tertiary text-text-muted hover:text-text-secondary"
                    }`}
                  >
                    {cat.charAt(0).toUpperCase() + cat.slice(1)}
                  </button>
                ),
              )}
            </div>
            <div className="grid grid-cols-4 gap-2">
              {filteredBackgrounds.map((preset) => (
                <button
                  key={preset.id}
                  onClick={() => handleImportBackground(preset)}
                  disabled={generatingBackground !== null}
                  className="aspect-square rounded-lg border border-border hover:border-primary/50 transition-all overflow-hidden relative group disabled:opacity-50"
                  title={preset.name}
                  style={{ background: preset.thumbnail }}
                >
                  {generatingBackground === preset.id && (
                    <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
                      <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    </div>
                  )}
                  <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-all flex items-center justify-center opacity-0 group-hover:opacity-100">
                    <Plus size={16} className="text-white" />
                  </div>
                  <span className="absolute bottom-0 left-0 right-0 text-[8px] text-white bg-black/60 py-0.5 px-1 truncate opacity-0 group-hover:opacity-100 transition-opacity">
                    {preset.name}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Shapes Section */}
          <div className="mb-6">
            <h4 className="text-xs font-medium text-text-secondary mb-3">
              Shapes
            </h4>
            <div className="grid grid-cols-4 gap-2">
              {[
                {
                  type: "rectangle" as ShapeType,
                  icon: Square,
                  label: "Rectangle",
                },
                { type: "circle" as ShapeType, icon: Circle, label: "Circle" },
                {
                  type: "triangle" as ShapeType,
                  icon: Triangle,
                  label: "Triangle",
                },
                { type: "star" as ShapeType, icon: Star, label: "Star" },
                {
                  type: "arrow" as ShapeType,
                  icon: ArrowRight,
                  label: "Arrow",
                },
                {
                  type: "polygon" as ShapeType,
                  icon: Hexagon,
                  label: "Polygon",
                },
              ].map((shape) => (
                <button
                  key={shape.type}
                  onClick={async () => {
                    const state = useProjectStore.getState();
                    const { createShapeClip, addTrack } = state;
                    const tracksBefore = state.project.timeline.tracks;
                    await addTrack("graphics", 0);
                    const tracksAfter =
                      useProjectStore.getState().project.timeline.tracks;
                    const newGraphicsTrack = tracksAfter.find(
                      (t) =>
                        t.type === "graphics" &&
                        !tracksBefore.some((bt) => bt.id === t.id),
                    );
                    if (newGraphicsTrack) {
                      createShapeClip(newGraphicsTrack.id, 0, shape.type);
                    }
                  }}
                  className="aspect-square bg-background-tertiary rounded-lg border border-border hover:border-primary/50 hover:bg-primary/5 transition-all flex flex-col items-center justify-center gap-1 group"
                  title={shape.label}
                >
                  <shape.icon
                    size={20}
                    className="text-text-secondary group-hover:text-primary transition-colors"
                  />
                  <span className="text-[9px] text-text-muted group-hover:text-text-secondary">
                    {shape.label}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* SVG Import Section */}
          <div className="mb-6">
            <h4 className="text-xs font-medium text-text-secondary mb-3">
              SVG Import
            </h4>
            <button
              onClick={() => {
                const input = document.createElement("input");
                input.type = "file";
                input.accept = ".svg";
                input.onchange = async (e) => {
                  const file = (e.target as HTMLInputElement).files?.[0];
                  if (file) {
                    const content = await file.text();
                    const state = useProjectStore.getState();
                    const { importSVG, addTrack } = state;
                    const tracksBefore = state.project.timeline.tracks;
                    await addTrack("graphics", 0);
                    const tracksAfter =
                      useProjectStore.getState().project.timeline.tracks;
                    const newGraphicsTrack = tracksAfter.find(
                      (t) =>
                        t.type === "graphics" &&
                        !tracksBefore.some((bt) => bt.id === t.id),
                    );
                    if (newGraphicsTrack) {
                      importSVG(content, newGraphicsTrack.id, 0);
                    }
                  }
                };
                input.click();
              }}
              className="w-full py-3 bg-background-tertiary rounded-lg border border-border hover:border-primary/50 hover:bg-primary/5 transition-all flex items-center justify-center gap-2 group"
            >
              <FileCode
                size={16}
                className="text-text-secondary group-hover:text-primary transition-colors"
              />
              <span className="text-xs text-text-secondary group-hover:text-text-primary">
                Import SVG File
              </span>
            </button>
          </div>

          {/* Stickers Section (placeholder) */}
          <div className="mb-6">
            <h4 className="text-xs font-medium text-text-secondary mb-3">
              Stickers & Emojis
            </h4>
            <div className="grid grid-cols-4 gap-2">
              {["😀", "🎉", "❤️", "⭐", "🔥", "👍", "🎬", "🎵"].map(
                (emoji, i) => (
                  <button
                    key={i}
                    onClick={async () => {
                      const state = useProjectStore.getState();
                      const { createStickerClip, addTrack } = state;
                      const { stickerLibrary } = await import("@openreel/core");

                      const tracksBefore = state.project.timeline.tracks;
                      await addTrack("graphics", 0);
                      const tracksAfter =
                        useProjectStore.getState().project.timeline.tracks;
                      const newGraphicsTrack = tracksAfter.find(
                        (t) =>
                          t.type === "graphics" &&
                          !tracksBefore.some((bt) => bt.id === t.id),
                      );

                      if (newGraphicsTrack) {
                        const emojiItem = {
                          id: `emoji-${i}`,
                          emoji,
                          name: emoji,
                          category: "emojis",
                        };
                        const clip = stickerLibrary.createEmojiClip(
                          emojiItem,
                          newGraphicsTrack.id,
                          0,
                          5,
                        );
                        createStickerClip(clip);
                      }
                    }}
                    className="aspect-square bg-background-tertiary rounded-lg border border-border hover:border-primary/50 hover:bg-primary/5 transition-all flex items-center justify-center text-xl cursor-pointer"
                  >
                    {emoji}
                  </button>
                ),
              )}
            </div>
          </div>
          </div>
        </ScrollArea>
      )}

      {/* Text Tab Content */}
      {activeTab === "text" && (
        <ScrollArea className="flex-1">
          <div className="px-5 pb-5 space-y-3">
            <button
              onClick={async () => {
                const state = useProjectStore.getState();
                const { createTextClip, addTrack } = state;
                const tracksBefore = state.project.timeline.tracks;
                await addTrack("text", 0);
                const tracksAfter =
                  useProjectStore.getState().project.timeline.tracks;
                const newTextTrack = tracksAfter.find(
                  (t) =>
                    t.type === "text" &&
                    !tracksBefore.some((bt) => bt.id === t.id),
                );
                if (newTextTrack) {
                  createTextClip(newTextTrack.id, 0, "New Title");
                }
              }}
              className="w-full py-4 bg-background-tertiary rounded-lg border border-border hover:border-primary/50 hover:bg-primary/5 transition-all text-center"
            >
              <span className="text-lg font-bold text-text-primary">
                Add Title
              </span>
              <p className="text-xs text-text-muted mt-1">
                Click to add text to timeline
              </p>
            </button>
            <div className="grid grid-cols-2 gap-2">
              {[
                {
                  name: "Heading",
                  text: "Heading",
                  style: {
                    fontSize: 72,
                    fontWeight: 700 as const,
                    textAlign: "center" as const,
                    verticalAlign: "middle" as const,
                  },
                },
                {
                  name: "Subtitle",
                  text: "Subtitle text",
                  style: {
                    fontSize: 36,
                    fontWeight: 400 as const,
                    textAlign: "center" as const,
                    verticalAlign: "middle" as const,
                  },
                },
                {
                  name: "Lower Third",
                  text: "Name Here",
                  style: {
                    fontSize: 32,
                    fontWeight: 600 as const,
                    textAlign: "left" as const,
                    verticalAlign: "bottom" as const,
                    backgroundColor: "rgba(0, 0, 0, 0.7)",
                  },
                },
                {
                  name: "Caption",
                  text: "Caption text here",
                  style: {
                    fontSize: 24,
                    fontWeight: 400 as const,
                    textAlign: "center" as const,
                    verticalAlign: "bottom" as const,
                    shadowColor: "rgba(0, 0, 0, 0.8)",
                    shadowBlur: 4,
                    shadowOffsetX: 1,
                    shadowOffsetY: 1,
                  },
                },
              ].map((preset) => (
                <button
                  key={preset.name}
                  onClick={async () => {
                    const state = useProjectStore.getState();
                    const { createTextClip, addTrack } = state;
                    const tracksBefore = state.project.timeline.tracks;
                    await addTrack("text", 0);
                    const tracksAfter =
                      useProjectStore.getState().project.timeline.tracks;
                    const newTextTrack = tracksAfter.find(
                      (t) =>
                        t.type === "text" &&
                        !tracksBefore.some((bt) => bt.id === t.id),
                    );
                    if (newTextTrack) {
                      createTextClip(
                        newTextTrack.id,
                        0,
                        preset.text,
                        5,
                        preset.style,
                      );
                    }
                  }}
                  className="py-3 bg-background-tertiary rounded-lg border border-border hover:border-primary/50 hover:bg-primary/5 transition-all text-xs text-text-secondary hover:text-text-primary"
                >
                  {preset.name}
                </button>
              ))}
            </div>
          </div>
        </ScrollArea>
      )}

      {/* AI Tab Content */}
      {activeTab === "ai" && <AIGenTab />}

      {aspectRatioDialogData && (
        <AspectRatioMatchDialog
          isOpen={showAspectRatioDialog}
          videoWidth={aspectRatioDialogData.videoWidth}
          videoHeight={aspectRatioDialogData.videoHeight}
          currentWidth={project.settings.width}
          currentHeight={project.settings.height}
          onConfirm={handleConfirmAspectRatioMatch}
          onCancel={handleCancelAspectRatioMatch}
        />
      )}

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
              onClick={() => {
                setShowCopyProjectModal(false);
                handleAddV2VFolderAsNewTracks();
              }}
              className="w-full text-left p-3 mb-2 rounded-lg border border-primary/40 bg-primary/10 hover:border-primary transition-colors flex items-center justify-between"
            >
              <div>
                <div className="text-sm font-medium text-primary">Añadir al timeline</div>
                <div className="text-[11px] text-text-muted mt-0.5">En nuevas pistas sincronizadas con job V2V</div>
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
                onClick={() => handleConfirmCopyToTarget(t.id)}
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
    </div>
  );
};

export default AssetsPanel;
