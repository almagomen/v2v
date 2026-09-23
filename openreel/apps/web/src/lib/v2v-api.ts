/**
 * v2v API client - connects to the FastAPI backend
 */
const API_BASE = (import.meta.env.VITE_V2V_API_URL || "").replace(/\/$/, "");

function isLocalhostLikeHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "0.0.0.0";
}

function apiBaseTargetsLocalhost(base: string): boolean {
  // VITE_V2V_API_URL suele venir como http://localhost:8000 o http://127.0.0.1:8000
  return /\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?/i.test(base);
}

function url(path: string): string {
  // En Colab normalmente abrimos el backend vía ngrok y el frontend se sirve desde el mismo host.
  // Si el build se hizo con VITE_V2V_API_URL apuntando a localhost, en el navegador eso falla.
  if (API_BASE) {
    if (typeof window !== "undefined") {
      const currentHost = window.location.hostname;
      if (apiBaseTargetsLocalhost(API_BASE) && !isLocalhostLikeHost(currentHost)) {
        return path; // usa llamada relativa (/api/...) contra el mismo backend
      }
    }
    return `${API_BASE}${path}`;
  }

  return path;
}

async function readJsonOrThrow<T>(res: Response): Promise<T> {
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return (await res.json()) as T;
  }

  // Si devolvió HTML (p.ej. index.html), evitamos el SyntaxError de JSON.parse
  const text = await res.text().catch(() => "");
  const preview = text
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 200);
  throw new Error(`Respuesta no JSON (${res.status}). Primeros caracteres: ${preview}`);
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
  video_only_path?: string;
  instrumental_path?: string;
  original_audio_path?: string;
  vocals_path?: string;
  segments: Segment[];
  url: string;
}

export interface JobResultResponse {
  job_id: string;
  status: string;
  videos: VideoResult[];
  log?: string;
}

export interface PollResponse {
  job_id: string;
  status: JobStatusResponse;
  log: string;
  items: any[];
  result?: JobResultResponse;
}

export interface SpeakerOption {
  label: string;
  value: string;
}

export interface AudioSegmentItem {
  seg: number;
  start: number;
  end: number;
  speaker: string;
  filename: string;
}

export interface GenerateAudioSegmentOptions {
  start?: number;
  speed?: number;
  temperature?: number;
  top_p?: number;
  repetition_penalty?: number;
  volume?: number;
  video_path?: string;
}

export interface GeneratedAudioResult {
  blob: Blob;
  segIdx: number;
  duration: number;
  filename: string;
}

export interface SegmentEditorRow {
  seg: number;
  start: number;
  end: number;
  slot_duration: number;
  original_text: string;
  tts_text: string;
  speaker?: string | null;
  filename?: string | null;
}

export interface SegmentsEditorResponse {
  job_id: string;
  video_index: number;
  source_lang?: string | null;
  target_lang?: string | null;
  segments: SegmentEditorRow[];
}


export interface JobUrlItem {
  url: string;
  status: string;
  message?: string;
  output_name?: string;
  index?: number;
}

// --- Colab Render ---
export interface TimelineClipPayload {
  type: "video" | "audio";
  media_name: string;
  start: number;
  end: number;
  track_start: number;
  volume?: number;
}

export interface RenderTimelinePayload {
  job_id: string;
  video_index: number;
  clips: TimelineClipPayload[];
  output_name: string;
  upload_to_catbox?: boolean;
}

export interface BatchRenderItemPayload {
  job_id: string;
  video_index: number;
  clips: TimelineClipPayload[];
  output_name: string;
}

export interface RenderBatchPayload {
  renders: BatchRenderItemPayload[];
  zip_name?: string;
  upload_to_catbox?: boolean;
}

export interface CatboxUploadResult {
  status: "uploaded";
  url: string;
  filename: string;
  expires_in: string;
}

export interface BatchCatboxResult {
  status: "completed";
  videos: Array<{ filename: string; url: string; status: string }>;
  errors: string[];
  expires_in: string;
}

export const v2vApi = {
  async processUrls(
    urls: string[],
    translateLang: string | null,
    speaker: string,
    emotion?: string | null
  ): Promise<ProcessUrlsResponse> {
    const res = await fetch(url("/api/process-urls"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        urls,
        translate_lang: translateLang,
        speaker,
        emotion: emotion || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText || "Error al procesar");
    }
    return readJsonOrThrow<ProcessUrlsResponse>(res);
  },

  async getJobStatus(jobId: string): Promise<JobStatusResponse> {
    const res = await fetch(url(`/api/job/${jobId}/status`));
    if (!res.ok) throw new Error("Error al obtener estado");
    return readJsonOrThrow<JobStatusResponse>(res);
  },

  async getJobResult(jobId: string): Promise<JobResultResponse> {
    const res = await fetch(url(`/api/job/${jobId}/result`));
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al obtener resultado");
    }
    return readJsonOrThrow<JobResultResponse>(res);
  },

  getFileUrl(jobId: string, videoIndex: number, filename: string): string {
    return url(`/api/job/${jobId}/files/${videoIndex}/${encodeURIComponent(filename)}`);
  },

  async fetchFileBlob(
    jobId: string,
    videoIndex: number,
    filename: string
  ): Promise<Blob> {
    const res = await fetch(url(`/api/job/${jobId}/files/${videoIndex}/${encodeURIComponent(filename)}`));
    if (!res.ok) throw new Error(`Error al descargar ${filename}`);
    return res.blob();
  },

  async fetchOutputVideoBlob(jobId: string, videoIndex: number): Promise<Blob> {
    // Endpoint nuevo: evita pasar `filename` (unicode/largo) en la URL.
    const res = await fetch(url(`/api/job/${jobId}/files/${videoIndex}`));
    if (!res.ok) throw new Error(`Error al descargar el video (${videoIndex})`);
    return res.blob();
  },

  async getSpeakers(): Promise<SpeakerOption[]> {
    const res = await fetch(url("/api/speakers"));
    if (!res.ok) return [];
    try {
      return await readJsonOrThrow<SpeakerOption[]>(res);
    } catch {
      // Si el backend no responde y devuelve HTML (p.ej. index.html), no rompas la UI.
      return [];
    }
  },

  async regenerateSegment(
    jobId: string,
    videoIndex: number,
    segIdx: number,
    text: string,
    start: number,
    end: number,
    translateLang: string | null,
    speaker: string,
    speed: number = 1.0,
    targetDuration?: number,
    options?: {
      temperature?: number;
      top_p?: number;
      repetition_penalty?: number;
      volume?: number;
    },
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
        speed,
        target_duration: targetDuration,
        temperature: options?.temperature ?? 0.7,
        top_p: options?.top_p ?? 0.7,
        repetition_penalty: options?.repetition_penalty ?? 1.2,
        volume: options?.volume ?? 0.0,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al regenerar segmento");
    }
    return res.blob();
  },

  async generateNewAudioSegment(
    jobId: string,
    videoIndex: number,
    text: string,
    speaker: string,
    options?: GenerateAudioSegmentOptions,
  ): Promise<GeneratedAudioResult> {
    const res = await fetch(url("/api/generate-audio-segment"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: jobId || undefined,
        video_index: videoIndex,
        video_path: options?.video_path,
        text,
        speaker,
        start: options?.start ?? 0,
        speed: options?.speed ?? 1.0,
        temperature: options?.temperature ?? 0.7,
        top_p: options?.top_p ?? 0.7,
        repetition_penalty: options?.repetition_penalty ?? 1.2,
        volume: options?.volume ?? 0.0,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al generar segmento de audio");
    }
    const blob = await res.blob();
    const segIdx = parseInt(res.headers.get("x-seg-idx") || "0", 10);
    const duration = parseFloat(res.headers.get("x-audio-duration") || "0");
    const filename =
      res.headers.get("x-audio-filename") ||
      `tts_${speaker}_${String(segIdx).padStart(3, "0")}.wav`;
    return { blob, segIdx, duration, filename };
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
    return readJsonOrThrow<{ output_path: string; filename: string }>(res);
  },

  async applyAudioSpeed(
    jobId: string,
    videoIndex: number,
    segIdx: number,
    speed: number | null,
    targetDuration?: number
  ): Promise<Blob> {
    const res = await fetch(url("/api/apply-speed"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: jobId,
        video_index: videoIndex,
        seg_idx: segIdx,
        speed,
        target_duration: targetDuration,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al aplicar velocidad al audio");
    }
    return res.blob();
  },

  async shareToCatbox(jobId: string, videoIndex: number): Promise<string> {
    const res = await fetch(url(`/api/job/${jobId}/share/${videoIndex}`));
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al compartir");
    }
    const data = await readJsonOrThrow<{ url: string }>(res);
    return data.url;
  },

  async getJobLog(jobId: string): Promise<string> {
    const res = await fetch(url(`/api/job/${jobId}/log`));
    if (!res.ok) return "";
    try {
      const data = await readJsonOrThrow<{ log?: string }>(res);
      return data.log || "";
    } catch {
      return "";
    }
  },

  async getJobItems(jobId: string): Promise<JobUrlItem[]> {
    const res = await fetch(url(`/api/job/${jobId}/items`));
    if (!res.ok) return [];
    try {
      const data = await readJsonOrThrow<{ items?: JobUrlItem[] }>(res);
      return data.items || [];
    } catch {
      return [];
    }
  },

  async getAudioSegments(jobId: string, videoIndex: number): Promise<AudioSegmentItem[]> {
    const res = await fetch(url(`/api/job/${jobId}/audio-segments/${videoIndex}`));
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al listar segmentos de audio");
    }
    return readJsonOrThrow<AudioSegmentItem[]>(res);
  },

  async fetchAudioSegmentBlob(jobId: string, videoIndex: number, seg: number): Promise<Blob> {
    const res = await fetch(url(`/api/job/${jobId}/audio-segments/${videoIndex}/${seg}`));
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Error al descargar segmento ${seg}`);
    }
    return res.blob();
  },

  async downloadZipBlob(jobId: string): Promise<Blob> {
    const res = await fetch(url(`/api/job/${jobId}/zip`));
    if (!res.ok) {
      // FastAPI suele devolver JSON con {detail}
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al descargar ZIP");
    }
    return res.blob();
  },

  getZipUrl(jobId: string): string {
    return url(`/api/job/${jobId}/zip`);
  },

  async getManifest(jobId: string, videoIndex: number): Promise<Record<string, unknown>> {
    const res = await fetch(url(`/api/render/manifest/${jobId}/${videoIndex}`));
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al obtener manifiesto");
    }
    return readJsonOrThrow<Record<string, unknown>>(res);
  },

  async getSegmentSpeed(jobId: string, videoIndex: number, segIdx: number): Promise<{ speed: number }> {
    const res = await fetch(url(`/api/segment-speed?job_id=${jobId}&video_index=${videoIndex}&seg_idx=${segIdx}`));
    if (!res.ok) return { speed: 1.0 };
    return readJsonOrThrow<{ speed: number }>(res);
  },

  async getSegmentsEditor(jobId: string, videoIndex: number): Promise<SegmentsEditorResponse> {
    const res = await fetch(url(`/api/job/${jobId}/segments-editor/${videoIndex}`));
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al cargar segmentos para edición");
    }
    return readJsonOrThrow<SegmentsEditorResponse>(res);
  },

  async retranslateSegments(
    jobId: string,
    videoIndex: number,
    segIndices: number[],
    targetLang?: string | null,
  ): Promise<{ segments: Array<{ seg: number; text: string }> }> {
    const res = await fetch(url("/api/retranslate-segments"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: jobId,
        video_index: videoIndex,
        seg_indices: segIndices,
        target_lang: targetLang ?? null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al retraducir segmentos");
    }
    return readJsonOrThrow<{ segments: Array<{ seg: number; text: string }> }>(res);
  },

  /**
   * Upload a local file to the Colab server before rendering.
   * Returns the media_name to use in the render payload.
   */
  async uploadMediaForRender(
    jobId: string,
    videoIndex: number,
    file: File,
    subfolder?: string,
  ): Promise<{ media_name: string }> {
    const form = new FormData();
    form.append("file", file, file.name);
    if (subfolder) form.append("subfolder", subfolder);
    const res = await fetch(
      url(`/api/render/upload-media/${jobId}/${videoIndex}`),
      { method: "POST", body: form },
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al subir media");
    }
    return readJsonOrThrow<{ media_name: string }>(res);
  },

  /**
   * Render a single project timeline on Colab via FFmpeg.
   * Returns a Blob (MP4) for direct download, or CatboxUploadResult if upload_to_catbox is true.
   */
  async renderTimeline(payload: RenderTimelinePayload): Promise<Blob | CatboxUploadResult> {
    const res = await fetch(url("/api/render/timeline"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al renderizar en Colab");
    }
    
    // Si se solicitó upload a Catbox, la respuesta es JSON
    if (payload.upload_to_catbox) {
      return readJsonOrThrow<CatboxUploadResult>(res);
    }
    
    return res.blob();
  },

  /**
   * Render multiple projects on Colab via FFmpeg.
   * Returns a Blob (ZIP) for direct download, or BatchCatboxResult if upload_to_catbox is true.
   */
  async renderBatch(payload: RenderBatchPayload): Promise<Blob | BatchCatboxResult> {
    const res = await fetch(url("/api/render/batch"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al renderizar batch en Colab");
    }
    
    // Si se solicitó upload a Catbox, la respuesta es JSON
    if (payload.upload_to_catbox) {
      return readJsonOrThrow<BatchCatboxResult>(res);
    }
    
    return res.blob();
  },

  async poll(jobId: string): Promise<PollResponse> {
    const res = await fetch(url(`/api/job/${jobId}/poll`));
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al sincronizar estado del job");
    }
    return readJsonOrThrow<PollResponse>(res);
  },

  async reconcileJobs(): Promise<{ jobs: Array<{ job_id: string; status: string; message: string; video_count: number; videos: any[] }> }> {
    const res = await fetch(url("/api/jobs/reconcile"));
    if (!res.ok) {
      return { jobs: [] };
    }
    return readJsonOrThrow(res);
  },

  async deleteVideo(folderName: string): Promise<{ status: string; message: string }> {
    const res = await fetch(url(`/api/video/${encodeURIComponent(folderName)}`), {
      method: "DELETE",
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al borrar carpeta de vídeo");
    }
    return await readJsonOrThrow<{ status: string; message: string }>(res);
  },

  async getTokens(): Promise<{ fish_api_key?: string; google_api_key?: string }> {
    const res = await fetch(url("/api/settings/tokens"));
    if (!res.ok) throw new Error("Error al obtener la configuración de tokens");
    return readJsonOrThrow<{ fish_api_key?: string; google_api_key?: string }>(res);
  },

  async saveTokens(
    fishApiKey?: string,
    googleApiKey?: string
  ): Promise<{ fish_api_key?: string; google_api_key?: string; message: string }> {
    const res = await fetch(url("/api/settings/tokens"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fish_api_key: fishApiKey || null,
        google_api_key: googleApiKey || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al actualizar la configuración de tokens");
    }
    return readJsonOrThrow(res);
  },
};
