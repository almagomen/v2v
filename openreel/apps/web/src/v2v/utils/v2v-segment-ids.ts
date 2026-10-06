/**
 * V2V Segment ID System
 * 
 * Proporciona IDs estables para segmentos V2V que persisten con el proyecto.
 * Los segmentos se identifican por: jobId + videoIndex + segIdx
 * Esto permite mantener textos editados, speakers y speeds independientemente
 * del nombre de archivo que pueda cambiar al regenerar.
 */

export interface V2VSegmentInfo {
  segmentId: string;
  mediaId: string;
  jobId: string;
  videoIndex: number;
  segIdx: number;
  folder: string;
  originalText: string;
  editedText: string | null;
  speaker: string | null;
  speed: number | null;
  createdAt: number;
  updatedAt: number;
}

export interface V2VFolderData {
  folderId: string;
  jobId: string;
  videoIndex: number;
  outputName: string | null;
  nativeFiles: string[];
  segments: Map<string, V2VSegmentInfo>;
  createdAt: number;
  updatedAt: number;
}

export type V2VProjectData = Record<string, V2VFolderData>;

export function generateSegmentId(jobId: string, videoIndex: number, segIdx: number): string {
  return `${jobId}_${videoIndex}_${segIdx}`;
}

export function parseSegmentId(segmentId: string): {
  jobId: string;
  videoIndex: number;
  segIdx: number;
} | null {
  const parts = segmentId.split("_");
  if (parts.length !== 3) return null;
  
  const videoIndex = parseInt(parts[1], 10);
  const segIdx = parseInt(parts[2], 10);
  
  if (Number.isNaN(videoIndex) || Number.isNaN(segIdx)) return null;
  
  return {
    jobId: parts[0],
    videoIndex,
    segIdx,
  };
}

export function generateFolderId(folder: string, jobId: string): string {
  return `${folder}::${jobId}`;
}

export function parseFolderId(folderId: string): {
  folder: string;
  jobId: string;
} | null {
  const parts = folderId.split("::");
  if (parts.length !== 2) return null;
  return {
    folder: parts[0],
    jobId: parts[1],
  };
}

export function createSegmentInfo(params: {
  mediaId: string;
  jobId: string;
  videoIndex: number;
  segIdx: number;
  folder: string;
  originalText: string;
  speaker?: string;
}): V2VSegmentInfo {
  const now = Date.now();
  return {
    segmentId: generateSegmentId(params.jobId, params.videoIndex, params.segIdx),
    mediaId: params.mediaId,
    jobId: params.jobId,
    videoIndex: params.videoIndex,
    segIdx: params.segIdx,
    folder: params.folder,
    originalText: params.originalText,
    editedText: null,
    speaker: params.speaker || null,
    speed: null,
    createdAt: now,
    updatedAt: now,
  };
}

export function updateSegmentText(
  segment: V2VSegmentInfo,
  newText: string
): V2VSegmentInfo {
  return {
    ...segment,
    editedText: newText,
    updatedAt: Date.now(),
  };
}

export function updateSegmentSpeaker(
  segment: V2VSegmentInfo,
  newSpeaker: string | null
): V2VSegmentInfo {
  return {
    ...segment,
    speaker: newSpeaker,
    updatedAt: Date.now(),
  };
}

export function updateSegmentSpeed(
  segment: V2VSegmentInfo,
  newSpeed: number | null
): V2VSegmentInfo {
  return {
    ...segment,
    speed: newSpeed,
    updatedAt: Date.now(),
  };
}

export function getSegmentByMediaId(
  folderData: V2VFolderData,
  mediaId: string
): V2VSegmentInfo | undefined {
  for (const segment of folderData.segments.values()) {
    if (segment.mediaId === mediaId) {
      return segment;
    }
  }
  return undefined;
}

export function getSegmentBySegIdx(
  folderData: V2VFolderData,
  segIdx: number
): V2VSegmentInfo | undefined {
  for (const segment of folderData.segments.values()) {
    if (segment.segIdx === segIdx) {
      return segment;
    }
  }
  return undefined;
}

export function getAllSegmentsForSpeaker(
  folderData: V2VFolderData,
  speaker: string
): V2VSegmentInfo[] {
  const segments: V2VSegmentInfo[] = [];
  for (const segment of folderData.segments.values()) {
    if (segment.speaker === speaker) {
      segments.push(segment);
    }
  }
  return segments.sort((a, b) => a.segIdx - b.segIdx);
}

export function createFolderData(params: {
  folder: string;
  jobId: string;
  videoIndex: number;
  outputName?: string;
}): V2VFolderData {
  const now = Date.now();
  return {
    folderId: generateFolderId(params.folder, params.jobId),
    jobId: params.jobId,
    videoIndex: params.videoIndex,
    outputName: params.outputName || null,
    nativeFiles: [],
    segments: new Map(),
    createdAt: now,
    updatedAt: now,
  };
}

export function addSegmentToFolder(
  folderData: V2VFolderData,
  segment: V2VSegmentInfo
): V2VFolderData {
  const newSegments = new Map(folderData.segments);
  newSegments.set(segment.segmentId, segment);
  return {
    ...folderData,
    segments: newSegments,
    updatedAt: Date.now(),
  };
}

export function updateMediaIdForSegment(
  folderData: V2VFolderData,
  oldMediaId: string,
  newMediaId: string
): V2VFolderData {
  const newSegments = new Map<string, V2VSegmentInfo>();
  for (const [key, segment] of folderData.segments) {
    if (segment.mediaId === oldMediaId) {
      newSegments.set(key, { ...segment, mediaId: newMediaId });
    } else {
      newSegments.set(key, segment);
    }
  }
  return {
    ...folderData,
    segments: newSegments,
    updatedAt: Date.now(),
  };
}

export function serializeFolderData(folderData: V2VFolderData): Record<string, unknown> {
  return {
    ...folderData,
    segments: Object.fromEntries(folderData.segments),
  };
}

export function deserializeFolderData(data: Record<string, unknown>): V2VFolderData {
  const segmentsMap = new Map<string, V2VSegmentInfo>();
  const segmentsData = data.segments as Record<string, V2VSegmentInfo>;
  if (segmentsData && typeof segmentsData === "object") {
    for (const [key, value] of Object.entries(segmentsData)) {
      segmentsMap.set(key, value);
    }
  }
  return {
    folderId: data.folderId as string,
    jobId: data.jobId as string,
    videoIndex: data.videoIndex as number,
    outputName: data.outputName as string | null,
    nativeFiles: (data.nativeFiles as string[]) || [],
    segments: segmentsMap,
    createdAt: data.createdAt as number,
    updatedAt: data.updatedAt as number,
  };
}

export function serializeProjectData(projectData: V2VProjectData): Record<string, unknown> {
  const serialized: Record<string, unknown> = {};
  for (const [key, folderData] of Object.entries(projectData)) {
    serialized[key] = serializeFolderData(folderData);
  }
  return serialized;
}

export function deserializeProjectData(data: Record<string, unknown>): V2VProjectData {
  const projectData: V2VProjectData = {};
  for (const [key, value] of Object.entries(data)) {
    projectData[key] = deserializeFolderData(value as Record<string, unknown>);
  }
  return projectData;
}
