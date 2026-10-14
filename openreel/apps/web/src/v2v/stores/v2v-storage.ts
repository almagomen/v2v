import type { PersistedJobState } from "./v2v-types";

export const JOB_STATE_STORAGE_KEY = "openreel.v2v.jobState";

export function loadJobStateFromStorage(): Partial<PersistedJobState> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(JOB_STATE_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PersistedJobState) : {};
  } catch {
    return {};
  }
}

export function saveJobStateToStorage(state: Partial<PersistedJobState>): void {
  if (typeof window === "undefined") return;
  try {
    const existing = loadJobStateFromStorage();
    localStorage.setItem(
      JOB_STATE_STORAGE_KEY,
      JSON.stringify({ ...existing, ...state }),
    );
  } catch {
    // ignore quota
  }
}
