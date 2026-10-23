import type { Project, Action, ActionResult } from "@openreel/core";
import { ActionExecutor, ActionHistory } from "@openreel/core";
import { v4 as uuidv4 } from "uuid";

/**
 * Acciones sobre proyectos desacoplados (inmutables / detached) para la extensión V2V.
 * Permite construir o manipular líneas de tiempo sin tocar el store reactivo de OpenReel.
 */

/**
 * Ejecuta una acción sobre una copia del proyecto sin tocar el store ni el historial del editor activo.
 */
export async function executeActionOnDetachedProject(
  project: Project,
  action: Action,
): Promise<ActionResult & { project?: Project }> {
  const projectCopy = structuredClone(project);
  const actionExecutor = new ActionExecutor(new ActionHistory());
  const result = await actionExecutor.execute(action, projectCopy);
  if (result.success) {
    return {
      ...result,
      project: {
        ...projectCopy,
        modifiedAt: Date.now(),
      },
    };
  }
  return result;
}

export async function addTrackToDetachedProject(
  project: Project,
  trackType: "video" | "audio" | "image" | "text" | "graphics",
  position?: number,
  trackId?: string,
): Promise<ActionResult & { project?: Project }> {
  const action: Action = {
    type: "track/add",
    id: uuidv4(),
    timestamp: Date.now(),
    params: { trackType, position, trackId: trackId || `track-${uuidv4()}` },
  };
  return executeActionOnDetachedProject(project, action);
}

/**
 * Igual que addTrackToDetachedProject pero devuelve también el trackId del nuevo track.
 * Lo obtiene comparando los tracks antes y después de la acción.
 */
export async function addTrackAndGetId(
  project: Project,
  trackType: "video" | "audio" | "image" | "text" | "graphics",
  position?: number,
): Promise<{ project: Project; trackId: string | null }> {
  const existingIds = new Set(project.timeline.tracks.map((t) => t.id));
  const result = await addTrackToDetachedProject(project, trackType, position);
  if (!result.success || !result.project) return { project, trackId: null };
  const newTrack = result.project.timeline.tracks.find((t) => !existingIds.has(t.id));
  return { project: result.project, trackId: newTrack?.id ?? null };
}

export async function addClipToDetachedProject(
  project: Project,
  trackId: string,
  mediaId: string,
  startTime: number,
): Promise<ActionResult & { project?: Project }> {
  const action: Action = {
    type: "clip/add",
    id: uuidv4(),
    timestamp: Date.now(),
    params: { trackId, mediaId, startTime },
  };
  return executeActionOnDetachedProject(project, action);
}

/**
 * Añade múltiples clips a un proyecto en un solo paso, ejecutando structuredClone una sola vez
 * en lugar de una vez por cada clip. Acelera la inserción de 80 clips de 10s a milisegundos.
 */
export async function addMultipleClipsToDetachedProject(
  project: Project,
  clipsToAdd: Array<{ trackId: string; mediaId: string; startTime: number; duration?: number }>,
): Promise<{ project: Project; addedCount: number }> {
  if (clipsToAdd.length === 0) return { project, addedCount: 0 };

  const projectCopy = structuredClone(project);
  const actionExecutor = new ActionExecutor(new ActionHistory());
  let addedCount = 0;

  for (const item of clipsToAdd) {
    const action: Action = {
      type: "clip/add",
      id: uuidv4(),
      timestamp: Date.now(),
      params: {
        trackId: item.trackId,
        mediaId: item.mediaId,
        startTime: item.startTime,
        ...(item.duration !== undefined && item.duration > 0 ? { duration: item.duration } : {}),
      },
    };
    const res = await actionExecutor.execute(action, projectCopy);
    if (res.success) addedCount++;
  }

  return {
    project: {
      ...projectCopy,
      modifiedAt: Date.now(),
    },
    addedCount,
  };
}

export function renameTrackInProject(
  project: Project,
  trackId: string,
  name: string,
): Project {
  return {
    ...project,
    modifiedAt: Date.now(),
    timeline: {
      ...project.timeline,
      tracks: project.timeline.tracks.map((t) =>
        t.id === trackId ? { ...t, name } : t,
      ),
    },
  };
}

export function muteTrackInProject(
  project: Project,
  trackId: string,
  muted: boolean,
): Project {
  return {
    ...project,
    modifiedAt: Date.now(),
    timeline: {
      ...project.timeline,
      tracks: project.timeline.tracks.map((t) =>
        t.id === trackId ? { ...t, muted } : t,
      ),
    },
  };
}

export function renameMediaInLibrary(
  project: Project,
  mediaId: string,
  newName: string,
): Project {
  return {
    ...project,
    modifiedAt: Date.now(),
    mediaLibrary: {
      ...project.mediaLibrary,
      items: project.mediaLibrary.items.map((m) =>
        m.id === mediaId ? { ...m, name: newName } : m,
      ),
    },
  };
}

export async function moveClipToTrack(
  project: Project,
  clipId: string,
  targetTrackName: string,
  startTime: number,
): Promise<{ project: Project; trackId: string; success: boolean }> {
  let sourceTrackId: string | null = null;
  let sourceClip = null;
  let mediaId: string | null = null;

  for (const track of project.timeline.tracks) {
    const clipIdx = track.clips.findIndex((c) => c.id === clipId);
    if (clipIdx !== -1) {
      sourceTrackId = track.id;
      sourceClip = track.clips[clipIdx];
      mediaId = sourceClip.mediaId;
      break;
    }
  }

  if (!sourceTrackId || !sourceClip || !mediaId) {
    return { project, trackId: "", success: false };
  }

  let targetTrack = project.timeline.tracks.find(
    (t) => t.name === targetTrackName,
  );
  let targetTrackId = targetTrack?.id;

  if (!targetTrack) {
    const existingIds = new Set(project.timeline.tracks.map((t) => t.id));
    const addResult = await addTrackToDetachedProject(project, "audio");
    if (!addResult.success || !addResult.project) {
      return { project, trackId: "", success: false };
    }
    project = addResult.project;
    const newTrack = project.timeline.tracks.find(
      (t) => !existingIds.has(t.id),
    );
    if (!newTrack) {
      return { project, trackId: "", success: false };
    }
    targetTrackId = newTrack.id;
    project = renameTrackInProject(project, targetTrackId, targetTrackName);
  }

  const removeAction: Action = {
    type: "clip/remove",
    id: uuidv4(),
    timestamp: Date.now(),
    params: { trackId: sourceTrackId, clipId },
  };
  const removeResult = await executeActionOnDetachedProject(project, removeAction);
  if (!removeResult.success || !removeResult.project) {
    return { project, trackId: "", success: false };
  }
  project = removeResult.project;

  const addAction: Action = {
    type: "clip/add",
    id: uuidv4(),
    timestamp: Date.now(),
    params: { trackId: targetTrackId!, mediaId, startTime },
  };
  const addResult = await executeActionOnDetachedProject(project, addAction);
  if (!addResult.success || !addResult.project) {
    return { project, trackId: "", success: false };
  }

  return { project: addResult.project, trackId: targetTrackId!, success: true };
}
