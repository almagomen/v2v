export interface ProcessRequest {
  urls: string[];
  translate_lang?: string;
  speaker: string;
}

export interface JobResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface SegmentInfo {
  index: number;
  start: number;
  end: number;
  text: string;
  speaker?: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  url: string;
  video_path?: string;
  has_video: boolean;
  segment_count: number;
  src_lang?: string;
  cached: boolean;
}

export interface OpenCutTimelineElement {
  id: string;
  mediaId?: string;
  name: string;
  type: 'video' | 'audio' | 'text';
  startTime: number;
  duration: number;
  trimStart?: number;
  trimEnd?: number;
  volume?: number;
  muted?: boolean;
  text?: string;
}

export interface OpenCutTrack {
  id: string;
  name: string;
  type: 'video' | 'audio' | 'text';
  muted?: boolean;
  locked?: boolean;
  visible?: boolean;
  elements: OpenCutTimelineElement[];
}

export interface OpenCutMediaAsset {
  id: string;
  name: string;
  type: 'video' | 'audio' | 'image';
  url: string;
  duration?: number;
}

export interface OpenCutProject {
  version: number;
  metadata: {
    id: string;
    name: string;
    duration: number;
    createdAt: string;
    updatedAt: string;
  };
  scenes: Array<{
    id: string;
    name: string;
    isMain: boolean;
    tracks: OpenCutTrack[];
  }>;
  mediaAssets: OpenCutMediaAsset[];
}
