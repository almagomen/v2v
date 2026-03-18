/**
 * v2v API client - connects to the FastAPI backend
 */
const API_BASE = (import.meta.env.VITE_V2V_API_URL || "").replace(/\/$/, "");

function url(path: string): string {
  return API_BASE ? `${API_BASE}${path}` : path;
}

export interface ProcessUrlsResponse {
  job_id: string;
  message: string;
}

export interface JobStatusResponse {
  job_id: string;
  status: string;
  message?: string;
  progress: number;
}

export interface Segment {
  seg: number;
  start: number;
  end: number;
  text: string;
  speaker?: string;
}

export interface VideoResult {
  index: number;
  output_name: string;
  video_path: string;
  output_video_path: string;
  output_filename?: string;
  segments: Segment[];
  url: string;
}

export interface JobResultResponse {
  job_id: string;
  status: string;
  videos: VideoResult[];
  log?: string;
}

export interface SpeakerOption {
  label: string;
  value: string;
}

export const v2vApi = {
  async processUrls(
    urls: string[],
    translateLang: string | null,
    speaker: string
  ): Promise<ProcessUrlsResponse> {
    const res = await fetch(url("/api/process-urls"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        urls,
        translate_lang: translateLang,
        speaker,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText || "Error al procesar");
    }
    return res.json();
  },

  async getJobStatus(jobId: string): Promise<JobStatusResponse> {
    const res = await fetch(url(`/api/job/${jobId}/status`));
    if (!res.ok) throw new Error("Error al obtener estado");
    return res.json();
  },

  async getJobResult(jobId: string): Promise<JobResultResponse> {
    const res = await fetch(url(`/api/job/${jobId}/result`));
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al obtener resultado");
    }
    return res.json();
  },

  getFileUrl(jobId: string, videoIndex: number, filename: string): string {
    return url(`/api/job/${jobId}/files/${videoIndex}/${filename}`);
  },

  async fetchFileBlob(
    jobId: string,
    videoIndex: number,
    filename: string
  ): Promise<Blob> {
    const res = await fetch(url(`/api/job/${jobId}/files/${videoIndex}/${filename}`));
    if (!res.ok) throw new Error(`Error al descargar ${filename}`);
    return res.blob();
  },

  async getSpeakers(): Promise<SpeakerOption[]> {
    const res = await fetch(url("/api/speakers"));
    if (!res.ok) return [];
    return res.json();
  },

  async regenerateSegment(
    jobId: string,
    videoIndex: number,
    segIdx: number,
    text: string,
    start: number,
    end: number,
    translateLang: string | null,
    speaker: string
  ): Promise<Blob> {
    const res = await fetch(url("/api/regenerate-segment"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: jobId,
        video_index: videoIndex,
        seg_idx: segIdx,
        text,
        start,
        end,
        translate_lang: translateLang,
        speaker,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al regenerar segmento");
    }
    return res.blob();
  },

  async regenerateVideo(
    jobId: string,
    videoIndex: number,
    segments: Segment[],
    translateLang: string | null,
    speaker: string
  ): Promise<{ output_path: string; filename: string }> {
    const res = await fetch(url("/api/regenerate-video"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: jobId,
        video_index: videoIndex,
        segments,
        translate_lang: translateLang,
        speaker,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al regenerar video");
    }
    return res.json();
  },

  async shareToCatbox(jobId: string, videoIndex: number): Promise<string> {
    const res = await fetch(url(`/api/job/${jobId}/share/${videoIndex}`));
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al compartir");
    }
    const data = await res.json();
    return data.url;
  },

  getZipUrl(jobId: string): string {
    return url(`/api/job/${jobId}/zip`);
  },
};

