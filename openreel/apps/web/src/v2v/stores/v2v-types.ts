import type { Segment, VideoResult, JobUrlItem } from "../api/v2v-api";
import type { V2VSegmentInfo, V2VFolderData } from "../utils/v2v-segment-ids";

export type V2VFolderRef = { 
  jobId: string; 
  videoIndex: number; 
  outputName?: string; 
  nativeFiles?: string[];
  segments?: Record<string, V2VSegmentInfo>;
  /** ID del workingProject que generó este folderRef, para evitar cargar un autosave stale */
  projectId?: string;
};

export type SerializedFolderData = Omit<V2VFolderData, "segments"> & {
  segments: Record<string, V2VSegmentInfo>;
  projectId?: string;
};

export interface PersistedJobState {
  urls: string;
  jobId: string | null;
  progress: number;
  videos: VideoResult[];
  selectedVideoIndex: number;
  segments: Segment[];
  urlItems: JobUrlItem[];
  urlLogs: Record<string, string>;
  jobPhase: string;
  importStatusByKey: Record<string, "in_progress" | "done" | "error">;
  log: string;
  shareUrl: string | null;
  lastUrlsSignature: string | null;
  translateLang: string;
  speaker: string;
}

export interface FoldersState {
  folderRefs: Record<string, SerializedFolderData>;
}

export interface FoldersActions {
  setFolderRef: (folder: string, ref: V2VFolderRef) => void;
  getFolderRef: (folder: string) => SerializedFolderData | undefined;
  removeFolderRef: (folder: string) => void;
  renameFolderRef: (oldFolder: string, newFolder: string) => void;
  setSegmentInfo: (folder: string, segment: V2VSegmentInfo) => void;
  getSegmentInfo: (folder: string, segmentId: string) => V2VSegmentInfo | undefined;
  getSegmentByMediaId: (folder: string, mediaId: string) => V2VSegmentInfo | undefined;
  updateSegmentText: (folder: string, segmentId: string, text: string) => void;
  updateSegmentSpeaker: (folder: string, segmentId: string, speaker: string | null) => void;
  updateSegmentSpeed: (folder: string, segmentId: string, speed: number | null) => void;
  syncFolderAssets: (jobId: string, videoIndex: number, folder: string) => Promise<void>;
}

export type FoldersSlice = FoldersState & FoldersActions;

export interface SegmentsState {
  segments: Segment[];
  selectedRowIndex: number | null;
  regenStatus: string;
  translateLang: string;
  speaker: string;
  speakers: { label: string; value: string }[];
  speakerMap: Record<string, string>;
  detectedSpeakers: string[];
}

export interface SegmentsActions {
  setSegments: (segments: Segment[] | ((prev: Segment[]) => Segment[])) => void;
  setSelectedRowIndex: (idx: number | null) => void;
  setRegenStatus: (status: string) => void;
  setTranslateLang: (lang: string) => void;
  setSpeaker: (speaker: string) => void;
  fetchSpeakers: () => Promise<void>;
  setSpeakerMap: (map: Record<string, string>) => void;
  updateSpeakerMapEntry: (speaker: string, voice: string) => void;
  fetchVideoSpeakers: (jobId: string, videoIndex: number) => Promise<void>;
  saveVideoSpeakerMap: (jobId: string, videoIndex: number, map: Record<string, string>) => Promise<void>;
}

export type SegmentsSlice = SegmentsState & SegmentsActions;

export interface JobState {
  urls: string;
  jobId: string | null;
  progress: number;
  error: string | null;
  videos: VideoResult[];
  selectedVideoIndex: number;
  isProcessing: boolean;
  shareUrl: string | null;
  log: string;
  importStatusByKey: Record<string, "in_progress" | "done" | "error">;
  urlItems: JobUrlItem[];
  selectedUrlForLogs: string | null;
  urlLogs: Record<string, string>;
  jobPhase: string;
  lastUrlsSignature: string | null;

  isV2VOpen: boolean;
  bulkEditorOpen: boolean;
  timelineHeight: number;
}

export interface JobActions {
  setIsV2VOpen: (open: boolean) => void;
  setBulkEditorOpen: (open: boolean) => void;
  setTimelineHeight: (height: number) => void;

  setUrls: (urls: string) => void;
  setJobId: (jobId: string | null) => void;
  setProgress: (progress: number) => void;
  setError: (error: string | null) => void;

  setVideos: (videos: VideoResult[]) => void;
  setSelectedVideoIndex: (idx: number) => void;

  setIsProcessing: (isProcessing: boolean) => void;
  setShareUrl: (url: string | null) => void;
  setLog: (log: string) => void;
  setImportStatus: (key: string, status: "in_progress" | "done" | "error") => void;
  setUrlItems: (items: JobUrlItem[]) => void;
  setSelectedUrlForLogs: (url: string | null) => void;
  appendUrlLog: (url: string, line: string) => void;
  setJobPhase: (phase: string) => void;

  clearJobRunState: (opts?: { keepImports?: boolean; keepItems?: boolean }) => void;
  setLastUrlsSignature: (sig: string | null) => void;

  startPolling: (jobId: string) => void;
  stopPolling: () => void;

  updateVideoOutputName: (videoIndex: number, newOutputName: string, targetJobId?: string) => Promise<void>;
  reset: () => void;
}

export type JobSlice = JobState & JobActions;

export type V2VState = FoldersSlice & SegmentsSlice & JobSlice;
