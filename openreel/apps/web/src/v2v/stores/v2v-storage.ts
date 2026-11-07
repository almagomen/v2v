import type { PersistedJobState } from "./v2v-types";

export const PROJECT_JOB_STORAGE_PREFIX = "openreel.v2v.projectJob.";
export const V2V_PREFERENCES_STORAGE_KEY = "openreel.v2v.preferences";

export interface V2VUserPreferences {
  initialEmotionPerSentence: boolean;
  initialEmotionTag: string;
  importTTSSegments: boolean;
  importVideoOnly: boolean;
  importMergedVideo: boolean;
  importInstrumental: boolean;
  importOriginalAudio: boolean;
  importOriginalVocals: boolean;
  importOriginalSegments: boolean;
}

export const DEFAULT_V2V_PREFERENCES: V2VUserPreferences = {
  initialEmotionPerSentence: false,
  initialEmotionTag: "[excited]",
  importTTSSegments: true,
  importVideoOnly: true,
  importMergedVideo: false,
  importInstrumental: true,
  importOriginalAudio: false,
  importOriginalVocals: false,
  importOriginalSegments: false,
};

export function loadV2VPreferences(): V2VUserPreferences {
  if (typeof window === "undefined") return DEFAULT_V2V_PREFERENCES;
  try {
    const raw = localStorage.getItem(V2V_PREFERENCES_STORAGE_KEY);
    return raw ? { ...DEFAULT_V2V_PREFERENCES, ...JSON.parse(raw) } : DEFAULT_V2V_PREFERENCES;
  } catch {
    return DEFAULT_V2V_PREFERENCES;
  }
}

export function saveV2VPreferences(prefs: Partial<V2VUserPreferences>): void {
  if (typeof window === "undefined") return;
  try {
    const current = loadV2VPreferences();
    localStorage.setItem(V2V_PREFERENCES_STORAGE_KEY, JSON.stringify({ ...current, ...prefs }));
  } catch {}
}

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
