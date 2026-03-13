export type ProjectStatus = 'pending' | 'downloading' | 'processing' | 'ready' | 'error';

export interface Project {
  id: string;
  url: string;
  output_name: string;
  status: ProjectStatus;
  video_path?: string;
  vocals_path?: string;
  no_vocals_path?: string;
  source_language?: string;
  video_clips: VideoClip[];
  audio_segments: AudioSegment[];
  created_at: string;
  updated_at: string;
}

export interface VideoClip {
  id: string;
  project_id: string;
  start_original: number;
  end_original: number;
  start_timeline: number;
  end_timeline: number;
  track_index: number;
  order: number;
  created_at: string;
}

export interface AudioSegment {
  id: string;
  project_id: string;
  text: string;
  speaker_id: string;
  start_timeline: number;
  end_timeline: number;
  start_original: number;
  end_original: number;
  audio_path?: string;
  audio_url?: string;
  is_dirty: boolean;
  is_generated: boolean;
  track_index: number;
  order: number;
  created_at: string;
}

export interface ProjectCreate {
  url: string;
  translate_lang?: string;
  speaker_id: string;
}

export interface ProgressMessage {
  type: 'progress' | 'log' | 'error' | 'complete';
  progress?: number;
  message: string;
  stage?: string;
}
