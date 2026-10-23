import { create } from "zustand";
import type { V2VState } from "./v2v-types";
import { createJobSlice } from "./v2v-job-slice";
import { createSegmentsSlice } from "./v2v-segments-slice";
import { createFoldersSlice } from "./v2v-folders-slice";

export const useV2VStore = create<V2VState>()((...a) => ({
  ...createJobSlice(...a),
  ...createSegmentsSlice(...a),
  ...createFoldersSlice(...a),
}));

// Re-export all types and slice creators for convenience & backward-compatibility
export type {
  V2VState,
  V2VFolderRef,
  SerializedFolderData,
  PersistedJobState,
  FoldersState,
  FoldersActions,
  FoldersSlice,
  SegmentsState,
  SegmentsActions,
  SegmentsSlice,
  JobState,
  JobActions,
  JobSlice,
} from "./v2v-types";

export { createJobSlice } from "./v2v-job-slice";
export { createSegmentsSlice } from "./v2v-segments-slice";
export {
  createFoldersSlice,
  FOLDER_REFS_STORAGE_KEY,
  loadFolderRefsFromStorage,
  saveFolderRefsToStorage,
} from "./v2v-folders-slice";
export {
  saveJobStateToStorage,
  loadJobStateForProject,
  saveJobStateForProject,
  clearJobStateForProject,
} from "./v2v-storage";
