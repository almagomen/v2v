import type { PersistedJobState } from "./v2v-types";

export const JOB_STATE_STORAGE_KEY = "openreel.v2v.jobState";
export const PROJECT_JOB_STORAGE_PREFIX = "openreel.v2v.projectJob.";

export function loadJobStateForProject(projectId: string | null): Partial<PersistedJobState> {
  if (typeof window === "undefined" || !projectId) return {};
  try {
    const raw = localStorage.getItem(`${PROJECT_JOB_STORAGE_PREFIX}${projectId}`);
    return raw ? (JSON.parse(raw) as PersistedJobState) : {};
  } catch {
    return {};
  }
}

export function saveJobStateForProject(projectId: string | null, state: Partial<PersistedJobState>): void {
  if (typeof window === "undefined" || !projectId) return;
  try {
    const existing = loadJobStateForProject(projectId);
    localStorage.setItem(
      `${PROJECT_JOB_STORAGE_PREFIX}${projectId}`,
      JSON.stringify({ ...existing, ...state }),
    );
  } catch {
    // ignore quota
  }
}

export function clearJobStateForProject(projectId: string | null): void {
  if (typeof window === "undefined" || !projectId) return;
  try {
    localStorage.removeItem(`${PROJECT_JOB_STORAGE_PREFIX}${projectId}`);
  } catch {}
}

export function loadJobStateFromStorage(): Partial<PersistedJobState> {
  if (typeof window === "undefined") return {};
  try {
    localStorage.removeItem(JOB_STATE_STORAGE_KEY);
    return {};
  } catch {
    return {};
  }
}

import { useProjectStore } from "@/stores/project-store";

export function saveJobStateToStorage(state: Partial<PersistedJobState>): void {
  if (typeof window === "undefined") return;
  try {
    const pid = useProjectStore.getState().project?.id;
    if (pid) {
      saveJobStateForProject(pid, state);
    }
  } catch {
    // ignore
  }
}
