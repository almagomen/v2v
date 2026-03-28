import type { Project, Action, ActionResult } from "@openreel/core";
import { ActionExecutor, ActionHistory } from "@openreel/core";
import { v4 as uuidv4 } from "uuid";

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
): Promise<ActionResult & { project?: Project }> {
  const action: Action = {
    type: "track/add",
    id: uuidv4(),
    timestamp: Date.now(),
    params: { trackType, position },
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
