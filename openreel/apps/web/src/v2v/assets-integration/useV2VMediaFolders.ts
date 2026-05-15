import { useCallback, useEffect, useMemo, useState } from "react";
import type { MediaItem } from "@openreel/core";
import { useProjectStore } from "../../stores/project-store";
import { useV2VStore } from "../../stores/v2v-store";
import { v2vApi, type AudioSegmentItem } from "../../lib/v2v-api";
import { autoSaveManager } from "../../services/auto-save";
import { importMultipleMediaIntoProject } from "../../utils/import-media-into-project";
import { toSafeToken } from "../../utils/v2v-utils";
import {
  collectFolderMediaFiles,
  extractFolderTimelineSnapshot,
  getDisplayName,
  getFolderName,
  listFolderNames,
  loadFolderSnapshot,
  renameTimelineTrack,
  saveFolderSnapshot,
} from "./v2v-folder-utils";

export type UseV2VMediaFoldersParams = {
  projectId: string;
  mediaItems: MediaItem[];
  searchQuery: string;
  showOnlyMissing: boolean;
  setIsImporting: (v: boolean) => void;
  setImportProgress: (s: string) => void;
};

export function useV2VMediaFolders({
  projectId,
  mediaItems,
  searchQuery,
  showOnlyMissing,
  setIsImporting,
  setImportProgress,
}: UseV2VMediaFoldersParams) {
  const [activeFolder, setActiveFolder] = useState<string | null>(null);
  const [draggedOverFolder, setDraggedOverFolder] = useState<string | null>(null);
  const [showCopyProjectModal, setShowCopyProjectModal] = useState(false);
  const [copyTargets, setCopyTargets] = useState<
    Array<{ id: string; name: string; subtitle: string; isCurrent: boolean }>
  >([]);
  const [copyingTargetId, setCopyingTargetId] = useState<string | null>(null);
  const [showGenerateAudio, setShowGenerateAudio] = useState(false);

  const {
    importMedia,
    deleteMedia,
    renameMedia,
    addTrack,
    addClip,
    trimClip,
    forceSave,
  } = useProjectStore();

  useEffect(() => {
    setActiveFolder(null);
  }, [projectId]);

  const folderNames = useMemo(() => listFolderNames(mediaItems), [mediaItems]);

  const baseItems = useMemo(() => {
    if (activeFolder) {
      return mediaItems.filter((m) => getFolderName(m.name) === activeFolder);
    }
    return mediaItems.filter((m) => !getFolderName(m.name));
  }, [mediaItems, activeFolder]);

  const filteredItems = useMemo(
    () =>
      baseItems.filter((item) => {
        const matchesSearch = item.name
          .toLowerCase()
          .includes(searchQuery.toLowerCase());
        const matchesFilter = showOnlyMissing ? item.isPlaceholder : true;
        return matchesSearch && matchesFilter;
      }),
    [baseItems, searchQuery, showOnlyMissing],
  );

  const itemForThumbnail = useCallback(
    (item: MediaItem): MediaItem =>
      activeFolder ? { ...item, name: getDisplayName(item.name) } : item,
    [activeFolder],
  );

  const importDroppedFiles = useCallback(
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

          if (result.success && file.type.startsWith("video/")) {
            setImportProgress(`Extracting audio from ${file.name}...`);
          }
        }
      } catch (error) {
        console.error("Import failed:", error);
      } finally {
        setIsImporting(false);
        setImportProgress("");
      }
    },
    [importMedia, activeFolder, setIsImporting, setImportProgress],
  );

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
    useV2VStore.getState().renameFolderRef(activeFolder, newName);
    setActiveFolder(newName);
  }, [activeFolder, mediaItems, renameMedia]);

  const handleDeleteFolder = useCallback(async () => {
    if (!activeFolder) return;
    const ok = window.confirm(
      `¿Borrar la carpeta "${activeFolder}" y todos sus archivos?`,
    );
    if (!ok) return;
    const items = mediaItems.filter((m) => getFolderName(m.name) === activeFolder);
    for (const it of items) {
      await deleteMedia(it.id);
    }
    useV2VStore.getState().removeFolderRef(activeFolder);
    setActiveFolder(null);
  }, [activeFolder, mediaItems, deleteMedia]);

  const handleFolderDrop = useCallback(
    async (e: React.DragEvent, targetFolder: string) => {
      e.preventDefault();
      e.stopPropagation();
      setDraggedOverFolder(null);

      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        return importDroppedFiles(e.dataTransfer.files, targetFolder);
      }

      const dataStr = e.dataTransfer.getData("application/json");
      if (!dataStr) return;

      try {
        const { mediaId } = JSON.parse(dataStr) as { mediaId?: string };
        if (mediaId && mediaId.length > 0) {
          const mediaItem = useProjectStore
            .getState()
            .project.mediaLibrary.items.find((m) => m.id === mediaId);
          if (!mediaItem) return;

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
    [importDroppedFiles, renameMedia],
  );

  const handleRootDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDraggedOverFolder(null);

      const dataStr = e.dataTransfer.getData("application/json");
      if (!dataStr) return;

      try {
        const { mediaId } = JSON.parse(dataStr) as { mediaId?: string };
        if (mediaId && mediaId.length > 0) {
          const mediaItem = useProjectStore
            .getState()
            .project.mediaLibrary.items.find((m) => m.id === mediaId);
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
    [renameMedia],
  );

  const handleFolderDragOver = useCallback((e: React.DragEvent, folder: string) => {
    e.preventDefault();
    e.stopPropagation();
    setDraggedOverFolder(folder);
  }, []);

  const handleFolderDragLeave = useCallback(() => {
    setDraggedOverFolder(null);
  }, []);

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

      const missingFilesInfo: {
        type: "video" | "audio";
        name: string;
        seg?: number;
      }[] = [];
      if (!mediaNames.has(videoMediaName)) {
        missingFilesInfo.push({ type: "video", name: videoMediaName });
      }

      for (const seg of segments) {
        const wavName = `${folder}/tts_${toSafeToken(seg.speaker || "speaker")}_${String(seg.seg).padStart(3, "0")}.wav`;
        if (!mediaNames.has(wavName)) {
          missingFilesInfo.push({ type: "audio", name: wavName, seg: seg.seg });
        }
      }

      if (missingFilesInfo.length > 0) {
        const downloadTasks = missingFilesInfo.map((info) => {
          if (info.type === "video") {
            return v2vApi
              .fetchOutputVideoBlob(ref.jobId, ref.videoIndex)
              .then((blob) => new File([blob], info.name, { type: "video/mp4" }));
          }
          return v2vApi
            .fetchAudioSegmentBlob(ref.jobId, ref.videoIndex, info.seg!)
            .then((blob) => new File([blob], info.name, { type: "audio/wav" }));
        });

        const filesToImport = await Promise.all(downloadTasks);

        const batchRes = await importMultipleMediaIntoProject(
          refreshState().project,
          filesToImport,
          { quick: true },
        );
        if (!batchRes.success) {
          throw new Error("Error en la importación masiva de la carpeta");
        }
        useProjectStore.setState({ project: batchRes.project });
      }

      return segments;
    },
    [],
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
    [ensureV2VMediaInProject, setIsImporting, setImportProgress],
  );

  const handleAddV2VFolderAsNewTracks = useCallback(async () => {
    if (!activeFolder) return;
    const ref = useV2VStore.getState().getFolderRef(activeFolder);

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
          const beforeIds = new Set(
            useProjectStore.getState().project.timeline.tracks.map((t) => t.id),
          );
          const rT = await addTrack(trackSnap.type as "video" | "audio" | "image");
          if (!rT.success) continue;

          const proj = useProjectStore.getState().project;
          const newTrack = proj.timeline.tracks.find((t) => !beforeIds.has(t.id));
          if (!newTrack) continue;

          renameTimelineTrack(newTrack.id, trackSnap.name);

          for (const clipSnap of trackSnap.clips) {
            const mediaName = `${folder}/${clipSnap.mediaName}`;
            const wm = useProjectStore
              .getState()
              .project.mediaLibrary.items.find((m) => m.name === mediaName);
            if (!wm) continue;

            const addR = await addClip(newTrack.id, wm.id, clipSnap.startTime);
            if (!addR.success) continue;

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
      return;
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
        const key =
          raw || `TTS_${toSafeToken(seg.speaker || "speaker")}_seg${seg.seg}`;
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
          ).padStart(3, "0")}.wav`;
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
      window.alert(
        e instanceof Error ? e.message : "Error al montar en el timeline",
      );
    } finally {
      setIsImporting(false);
      setImportProgress("");
    }
  }, [
    activeFolder,
    addTrack,
    addClip,
    trimClip,
    ensureV2VMediaInProject,
    forceSave,
    setIsImporting,
    setImportProgress,
  ]);

  const handleCopyFolderTtsToAnotherProject = useCallback(async () => {
    if (!activeFolder) return;

    try {
      await autoSaveManager.initialize();
      const saves = await autoSaveManager.checkForRecovery();

      const unique = saves.reduce((acc, save) => {
        const existing = acc.find((x) => x.projectId === save.projectId);
        if (!existing || save.timestamp > existing.timestamp) {
          return [...acc.filter((x) => x.projectId !== save.projectId), save];
        }
        return acc;
      }, [] as typeof saves);

      const ordered = unique.sort((a, b) => b.timestamp - a.timestamp);
      const currentProjectId = useProjectStore.getState().project.id;
      const targets: Array<{
        id: string;
        name: string;
        subtitle: string;
        isCurrent: boolean;
      }> = [];

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

          const filesToImport = snapshotFiles.filter((file) => {
            return !useProjectStore
              .getState()
              .project.mediaLibrary.items.some((m) => m.name === file.name);
          });

          if (filesToImport.length > 0) {
            const batchRes = await importMultipleMediaIntoProject(
              useProjectStore.getState().project,
              filesToImport,
              { quick: true },
            );
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

  return {
    activeFolder,
    setActiveFolder,
    draggedOverFolder,
    setDraggedOverFolder,
    folderNames,
    filteredItems,
    itemForThumbnail,
    importDroppedFiles,
    handleFolderDrop,
    handleRootDrop,
    handleFolderDragOver,
    handleFolderDragLeave,
    handleRenameFolder,
    handleDeleteFolder,
    showCopyProjectModal,
    setShowCopyProjectModal,
    copyTargets,
    copyingTargetId,
    handleCopyFolderTtsToAnotherProject,
    handleConfirmCopyToTarget,
    handleAddV2VFolderAsNewTracks,
    showGenerateAudio,
    setShowGenerateAudio,
  };
}

export type V2VMediaFoldersHandle = ReturnType<typeof useV2VMediaFolders>;
