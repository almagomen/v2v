/**
 * v2v API client - connects to the FastAPI backend
 */
const STORAGE_KEY_BACKEND_URL = "v2v_backend_url";

export function getCustomBackendUrl(): string {
  if (typeof window !== "undefined") {
    return localStorage.getItem(STORAGE_KEY_BACKEND_URL) || "";
  }
  return "";
}

export function setCustomBackendUrl(customUrl: string): void {
  if (typeof window !== "undefined") {
    const trimmed = customUrl.trim().replace(/\/$/, "");
    if (trimmed) {
      localStorage.setItem(STORAGE_KEY_BACKEND_URL, trimmed);
    } else {
      localStorage.removeItem(STORAGE_KEY_BACKEND_URL);
    }
  }
}

export function getEffectiveBackendUrl(): string {
  const custom = getCustomBackendUrl();
  if (custom) return custom;
  return (import.meta.env.VITE_V2V_API_URL || "").replace(/\/$/, "");
}

function isLocalhostLikeHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "0.0.0.0";
}

function apiBaseTargetsLocalhost(base: string): boolean {
  // VITE_V2V_API_URL suele venir como http://localhost:8000 o http://127.0.0.1:8000
  return /\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?/i.test(base);
}

function url(path: string): string {
  const base = getEffectiveBackendUrl();
  if (base) {
    if (typeof window !== "undefined") {
      const currentHost = window.location.hostname;
      const isDesktop = window.location.protocol === "app:" || (window as any).openreel?.platform === "desktop";
      // En modo Web remoto (ej: trycloudflare), si apunta a localhost usamos ruta relativa con proxy
      // En Desktop (app://), SIEMPRE usamos la URL base absoluta
      if (!isDesktop && apiBaseTargetsLocalhost(base) && !isLocalhostLikeHost(currentHost)) {
        return path;
      }
    }
    return `${base}${path}`;
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

const METADATA_TIMEOUT_MS = 30_000;
// Transferencias grandes (video_only, merged, TAR): sin tope total. Un MP4 de
// 40 MB puede tardar minutos por un túnel lento; abortar por tiempo total era
// un falso fallo. Solo se vigila el primer byte y los periodos sin datos.
const STREAM_HEADER_TIMEOUT_MS = 30_000;
const STREAM_STALL_TIMEOUT_MS = 45_000;
// Generación bajo demanda (TTS, aplicar velocidad): el servidor puede tardar
// bastante antes del primer byte, pero no minutos. Un tope amplio evita que la
// UI espere para siempre si la petición se perdió.
const GENERATION_HEADER_TIMEOUT_MS = 180_000;

function timeoutError(message: string): Error {
  return new DOMException(message, "TimeoutError");
}

/**
 * Señal de aborto con límite de tiempo y encadenamiento al AbortSignal externo.
 * El llamador debe ejecutar `cleanup()` en un `finally`.
 */
function createTimeoutSignal(
  timeoutMs: number,
  externalSignal?: AbortSignal,
  message = `Tiempo de espera agotado (${timeoutMs / 1000}s)`
): { signal: AbortSignal; cleanup: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(timeoutError(message)), timeoutMs);
  const onExternalAbort = () => controller.abort(externalSignal?.reason);
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort(externalSignal.reason);
    else externalSignal.addEventListener("abort", onExternalAbort, { once: true });
  }
  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timer);
      if (externalSignal) externalSignal.removeEventListener("abort", onExternalAbort);
    },
  };
}

interface BufferedDownload {
  buffer: ArrayBuffer;
  contentType: string;
  bytes: number;
}

// Transferencias grandes: varias conexiones en paralelo para aprovechar el
// ancho de banda del túnel. Cloudflare limita el caudal por conexión, así que
// 4 rangos simultáneos suelen ir bastante más rápido que un único flujo.
// Solo se activa cuando el servidor confirma soporte de HTTP Range.
const PARALLEL_RANGE_MAX = 4;
const PARALLEL_RANGE_BYTES = 8 * 1024 * 1024;
const PARALLEL_RANGE_ATTEMPTS = 3;
// Presupuesto global de conexiones de rango. Varios activos se descargan a la
// vez (`Promise.all` en la importación), y cada uno abriría 4 conexiones: sin
// este tope se saturan los sockets del navegador y Cloudflare empieza a
// devolver 429/502. Los trozos esperan turno en vez de fallar.
const RANGE_MAX_CONCURRENCY = 6;
let activeRangeRequests = 0;
const rangeWaiters: Array<() => void> = [];

async function withRangeSlot<T>(task: () => Promise<T>): Promise<T> {
  if (activeRangeRequests >= RANGE_MAX_CONCURRENCY) {
    // Esperamos a que se libere un hueco; el hueco se transfiere directamente.
    await new Promise<void>((resolve) => rangeWaiters.push(resolve));
  } else {
    activeRangeRequests++;
  }

  try {
    return await task();
  } finally {
    const next = rangeWaiters.shift();
    if (next) next();
    else activeRangeRequests--;
  }
}

interface GuardedResponse {
  res: Response;
  controller: AbortController;
  /** Libera el temporizador de cabeceras y el listener de cancelación. */
  cleanup: () => void;
}

/**
 * Lanza la petición y vigila solo el tiempo hasta las cabeceras. El consumidor
 * del cuerpo aplica después la guarda de estancamiento.
 */
async function fetchWithHeaderGuard(
  target: string,
  options: {
    label: string;
    method?: string;
    headers?: Record<string, string>;
    body?: BodyInit;
    signal?: AbortSignal;
    /** `null` desactiva la guarda: para peticiones que pueden tardar minutos. */
    headerTimeoutMs?: number | null;
  }
): Promise<GuardedResponse> {
  const {
    label,
    method,
    headers,
    body,
    signal,
    headerTimeoutMs = STREAM_HEADER_TIMEOUT_MS,
  } = options;

  const controller = new AbortController();
  const timer =
    headerTimeoutMs == null
      ? null
      : setTimeout(
          () =>
            controller.abort(
              timeoutError(`El servidor no envió '${label}' en ${headerTimeoutMs / 1000}s`)
            ),
          headerTimeoutMs
        );
  const onAbort = () => controller.abort(signal?.reason);
  if (signal) {
    if (signal.aborted) controller.abort(signal.reason);
    else signal.addEventListener("abort", onAbort, { once: true });
  }
  const cleanup = () => {
    if (timer) clearTimeout(timer);
    if (signal) signal.removeEventListener("abort", onAbort);
  };

  try {
    const res = await fetch(target, { method, body, signal: controller.signal, headers });
    if (timer) clearTimeout(timer);
    return { res, controller, cleanup };
  } catch (error) {
    cleanup();
    throw error;
  }
}

/**
 * Lee el tamaño total con un HEAD. `Content-Length` y `Content-Type` son
 * cabeceras safelisted, así que se pueden leer también en cross-origin
 * (modo Desktop) sin configurar `Access-Control-Expose-Headers`.
 * Devuelve null si el servidor no responde al HEAD o no informa del tamaño.
 */
async function headDownloadSize(
  target: string,
  options: {
    label: string;
    signal?: AbortSignal;
    headerTimeoutMs: number;
  }
): Promise<{ total: number; contentType: string } | null> {
  try {
    const { res, cleanup } = await fetchWithHeaderGuard(target, {
      label: options.label,
      method: "HEAD",
      signal: options.signal,
      headerTimeoutMs: options.headerTimeoutMs,
    });
    cleanup();
    if (!res.ok) return null;
    const length = Number(res.headers.get("content-length"));
    if (!Number.isFinite(length) || length <= 0) return null;
    return {
      total: length,
      contentType: res.headers.get("content-type") || "",
    };
  } catch {
    return null;
  }
}

async function responseError(res: Response, label: string): Promise<Error> {
  const type = (res.headers.get("content-type") || "").toLowerCase();
  let detail = "";

  if (type.includes("application/json") || type.startsWith("text/")) {
    const raw = await res.text().catch(() => "");
    try {
      const parsed = JSON.parse(raw);
      if (typeof parsed?.detail === "string") detail = parsed.detail;
      else if (typeof parsed?.message === "string") detail = parsed.message;
    } catch {
      // La respuesta de error no era JSON; mostramos el texto si lo hay.
      if (raw.trim()) detail = raw.trim().slice(0, 300);
    }
  } else {
    // No descargamos un cuerpo binario enorme solo para leer el error.
    await res.body?.cancel().catch(() => {});
  }

  const error = new Error(detail || `Error al descargar '${label}' (${res.status})`);
  (error as Error & { status?: number }).status = res.status;
  return error;
}

/**
 * Consume el cuerpo con la guarda de estancamiento. Si se pasa `write`, los
 * trozos se escriben directamente en el buffer destino (sin acumular copias),
 * que es lo que usa la descarga por rangos.
 */
async function consumeBodyWithStallGuard(
  res: Response,
  controller: AbortController,
  label: string,
  stallTimeoutMs: number,
  write?: (chunk: Uint8Array, offset: number) => void
): Promise<{ buffer: ArrayBuffer; bytes: number }> {
  const abortWith = (message: string) => controller.abort(timeoutError(message));

  if (!res.body) {
    const buffer = await res.arrayBuffer();
    if (write) write(new Uint8Array(buffer), 0);
    return { buffer: write ? new ArrayBuffer(0) : buffer, bytes: buffer.byteLength };
  }

  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;

  for (;;) {
    let stallTimer: ReturnType<typeof setTimeout> | undefined;
    const stall = new Promise<never>((_, reject) => {
      stallTimer = setTimeout(() => {
        const message = `Descarga de '${label}' detenida: sin datos durante ${stallTimeoutMs / 1000}s`;
        abortWith(message);
        reject(new Error(message));
      }, stallTimeoutMs);
    });

    try {
      const result = await Promise.race([reader.read(), stall]);
      if (result.done) break;
      if (result.value) {
        if (write) write(result.value, total);
        else chunks.push(result.value);
        total += result.value.length;
      }
    } finally {
      if (stallTimer) clearTimeout(stallTimer);
    }
  }

  if (write) return { buffer: new ArrayBuffer(0), bytes: total };

  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return { buffer: merged.buffer, bytes: total };
}

/**
 * Ejecuta una petición que devuelve un blob (regenerar TTS, aplicar velocidad,
 * render) y consume el cuerpo con guarda de estancamiento.
 *
 * No impone límite al tiempo hasta las cabeceras por defecto: el servidor puede
 * tardar en generar el audio o el vídeo. Lo que sí se vigila es que, una vez
 * empezada la respuesta, no deje de llegar datos. Así una generación lenta
 * termina, pero una conexión colgada falla con un mensaje claro en vez de
 * dejar la UI bloqueada indefinidamente.
 */
async function fetchBlobWithStallGuard(
  target: string,
  init: {
    method: string;
    headers?: Record<string, string>;
    body?: BodyInit;
    signal?: AbortSignal;
  },
  options: {
    label: string;
    headerTimeoutMs?: number | null;
    stallTimeoutMs?: number;
  }
): Promise<{ blob: Blob; res: Response }> {
  const stallTimeoutMs = options.stallTimeoutMs ?? STREAM_STALL_TIMEOUT_MS;
  const guarded = await fetchWithHeaderGuard(target, {
    label: options.label,
    method: init.method,
    headers: init.headers,
    body: init.body,
    signal: init.signal,
    headerTimeoutMs: options.headerTimeoutMs ?? null,
  });

  try {
    if (!guarded.res.ok) {
      throw await responseError(guarded.res, options.label);
    }
    const { buffer } = await consumeBodyWithStallGuard(
      guarded.res,
      guarded.controller,
      options.label,
      stallTimeoutMs
    );
    const contentType = guarded.res.headers.get("content-type") || "application/octet-stream";
    return { blob: new Blob([buffer], { type: contentType }), res: guarded.res };
  } finally {
    guarded.cleanup();
  }
}

/** Combina señales de cancelación (externa + aborto compartido de rangos). */
function anySignal(...signals: Array<AbortSignal | undefined>): AbortSignal | undefined {
  const present = signals.filter((s): s is AbortSignal => !!s);
  if (present.length === 0) return undefined;
  if (present.length === 1) return present[0];

  const controller = new AbortController();
  const onAbort = () => {
    const reason = present.find((s) => s.aborted)?.reason;
    controller.abort(reason);
  };
  for (const s of present) {
    if (s.aborted) {
      controller.abort(s.reason);
      break;
    }
    s.addEventListener("abort", onAbort, { once: true });
  }
  return controller.signal;
}

async function fetchRangeInto(
  target: string,
  start: number,
  end: number,
  sink: Uint8Array,
  options: {
    label: string;
    signal?: AbortSignal;
    headerTimeoutMs: number;
    stallTimeoutMs: number;
  }
): Promise<void> {
  const expected = end - start + 1;
  let lastError: unknown = null;

  for (let attempt = 1; attempt <= PARALLEL_RANGE_ATTEMPTS; attempt++) {
    const rangeLabel =
      attempt === 1 ? options.label : `${options.label} (reintento ${attempt - 1})`;

    try {
      await withRangeSlot(async () => {
        const guarded = await fetchWithHeaderGuard(target, {
          label: rangeLabel,
          headers: { Range: `bytes=${start}-${end}` },
          signal: options.signal,
          headerTimeoutMs: options.headerTimeoutMs,
        });

        try {
          if (guarded.res.status !== 206) {
            throw await responseError(guarded.res, rangeLabel);
          }
          const { bytes } = await consumeBodyWithStallGuard(
            guarded.res,
            guarded.controller,
            rangeLabel,
            options.stallTimeoutMs,
            (chunk, offset) => sink.set(chunk, start + offset)
          );
          if (bytes !== expected) {
            throw new Error(`Rango incompleto en '${rangeLabel}': ${bytes}/${expected} bytes`);
          }
        } finally {
          guarded.cleanup();
        }
      });
      return;
    } catch (error) {
      lastError = error;
      // Si el conjunto se canceló, no tiene sentido reintentar.
      if (options.signal?.aborted) break;
    }
  }

  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

/**
 * Descarga un archivo troceado en rangos paralelos. `total` viene del HEAD y
 * cada trozo se escribe directo en su posición del buffer final.
 */
async function downloadByRanges(
  target: string,
  total: number,
  options: {
    label: string;
    signal?: AbortSignal;
    headerTimeoutMs: number;
    stallTimeoutMs: number;
    contentType: string;
  }
): Promise<BufferedDownload> {
  const chunkCount = Math.max(
    1,
    Math.min(PARALLEL_RANGE_MAX, Math.ceil(total / PARALLEL_RANGE_BYTES))
  );
  const chunkSize = Math.ceil(total / chunkCount);
  const merged = new Uint8Array(total);
  const shared = new AbortController();
  const signal = anySignal(options.signal, shared.signal);

  const ranges: Array<{ index: number; start: number; end: number }> = [];
  for (let i = 0; i < chunkCount; i++) {
    const start = i * chunkSize;
    const end = Math.min(total - 1, start + chunkSize - 1);
    if (start <= end) ranges.push({ index: i, start, end });
  }

  try {
    await Promise.all(
      ranges.map(({ index, start, end }) =>
        fetchRangeInto(target, start, end, merged, {
          label: `${options.label} (${index + 1}/${ranges.length})`,
          signal,
          headerTimeoutMs: options.headerTimeoutMs,
          stallTimeoutMs: options.stallTimeoutMs,
        })
      )
    );
  } catch (error) {
    // Si un trozo falla de forma definitiva, cancelamos los que sigan vivos.
    shared.abort(error);
    throw error;
  }

  return {
    buffer: merged.buffer,
    contentType: options.contentType,
    bytes: total,
  };
}

/**
 * Descarga binaria con dos guardas: tiempo máximo hasta las cabeceras y tiempo
 * máximo sin recibir datos. No impone un tope total, así que una transferencia
 * lenta pero viva puede terminar; una conexión colgada falla con un error claro.
 *
 * La usan tanto el TAR de segmentos como los activos de video grandes. El tope
 * total de 60 s que había antes abortaba `video_only` en cuanto el MP4 pasaba
 * de ~25 MB en un túnel lento.
 *
 * Con `parallelRanges`, primero consulta el tamaño con un HEAD y luego sondea
 * con `Range: bytes=0-0`:
 *  - 206 → descarga en trozos paralelos (si el archivo es grande).
 *  - 200 → el servidor ignoró Range; esa misma respuesta ya es el archivo
 *          completo y se consume sin repetir la descarga.
 *  - 416 → sin rangos válidos; se hace un GET normal.
 */
async function fetchBufferWithGuards(
  target: string,
  options: {
    externalSignal?: AbortSignal;
    label?: string;
    headerTimeoutMs?: number;
    stallTimeoutMs?: number;
    parallelRanges?: boolean;
    /** Intentos del flujo único (los rangos ya tienen su propio reintento). */
    attempts?: number;
  } = {}
): Promise<BufferedDownload> {
  const {
    externalSignal,
    label = "archivo",
    headerTimeoutMs = STREAM_HEADER_TIMEOUT_MS,
    stallTimeoutMs = STREAM_STALL_TIMEOUT_MS,
    parallelRanges = false,
    attempts = 2,
  } = options;

  const contentTypeOf = (res: Response) => res.headers.get("content-type") || "";

  if (parallelRanges) {
    const head = await headDownloadSize(target, {
      label,
      signal: externalSignal,
      headerTimeoutMs,
    });

    if (head && head.total >= PARALLEL_RANGE_BYTES) {
      let probe: GuardedResponse | null = null;
      try {
        probe = await fetchWithHeaderGuard(target, {
          label,
          headers: { Range: "bytes=0-0" },
          signal: externalSignal,
          headerTimeoutMs,
        });
      } catch (error) {
        // Si el sondeo falla, probamos la descarga normal de una conexión.
        if (externalSignal?.aborted) throw error;
      }

      if (probe) {
        try {
          if (probe.res.status === 206) {
            // Liberamos el byte de sondeo antes de abrir las conexiones paralelas.
            await probe.res.body?.cancel().catch(() => {});
            try {
              return await downloadByRanges(target, head.total, {
                label,
                signal: externalSignal,
                headerTimeoutMs,
                stallTimeoutMs,
                contentType: head.contentType,
              });
            } catch (error) {
              if (externalSignal?.aborted) throw error;
              // Si los rangos fallan (túnel que limita conexiones, etc.),
              // último intento con un único flujo antes de rendirnos.
              console.warn(
                `[V2V] Descarga por rangos falló para '${label}'; reintentando en un flujo único.`,
                error
              );
            }
          } else if (probe.res.status === 200) {
            // Range ignorado: la respuesta abierta es el archivo completo.
            const { buffer, bytes } = await consumeBodyWithStallGuard(
              probe.res,
              probe.controller,
              label,
              stallTimeoutMs
            );
            return { buffer, contentType: contentTypeOf(probe.res), bytes };
          } else if (probe.res.status !== 416) {
            throw await responseError(probe.res, label);
          }
        } finally {
          probe.cleanup();
        }
      }
    }
  }

  let lastError: unknown = null;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      const single = await fetchWithHeaderGuard(target, {
        label,
        signal: externalSignal,
        headerTimeoutMs,
      });
      try {
        if (!single.res.ok) {
          throw await responseError(single.res, label);
        }
        const { buffer, bytes } = await consumeBodyWithStallGuard(
          single.res,
          single.controller,
          label,
          stallTimeoutMs
        );
        return { buffer, contentType: contentTypeOf(single.res), bytes };
      } finally {
        single.cleanup();
      }
    } catch (error) {
      lastError = error;
      const status = (error as { status?: number }).status;
      // Reintentamos fallos de red o 5xx; un 4xx no mejora al repetirlo.
      const retryable = status === undefined || status >= 500;
      if (!retryable || externalSignal?.aborted || attempt >= attempts) break;
      console.warn(
        `[V2V] Descarga de '${label}' falló; reintentando (${attempt}/${attempts - 1}).`,
        error
      );
    }
  }

  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

async function fetchTarBuffer(
  target: string,
  externalSignal?: AbortSignal
): Promise<ArrayBuffer> {
  const { buffer } = await fetchBufferWithGuards(target, {
    externalSignal,
    label: "paquete TAR",
  });
  return buffer;
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
  duration?: number;
  orig_start?: number;
  orig_end?: number;
  orig_duration?: number;
  src_start?: number;
  src_end?: number;
  text: string;
  speaker?: string;
  original_speaker?: string;
  original_text?: string;
  phonemes?: Record<string, string>;
  internal_pause_sec?: number;
  syllable_count?: number;
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
  duration?: number;
  orig_start?: number;
  orig_end?: number;
  orig_duration?: number;
  src_start?: number;
  src_end?: number;
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
  phonemes?: Record<string, string>;
  preview?: boolean;
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
  orig_start?: number;
  orig_end?: number;
  orig_duration?: number;
  original_text: string;
  tts_text: string;
  speaker?: string | null;
  original_speaker?: string | null;
  filename?: string | null;
  phonemes?: Record<string, string>;
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
  mode?: "auto" | "stream_copy" | "reencode";
  force_rerender?: boolean;
}

export interface BatchRenderItemPayload {
  job_id: string;
  video_index: number;
  clips: TimelineClipPayload[];
  output_name: string;
  mode?: "auto" | "stream_copy" | "reencode";
}

export interface RenderBatchPayload {
  renders: BatchRenderItemPayload[];
  zip_name?: string;
  upload_to_catbox?: boolean;
  batch_id?: string;
  mode?: "auto" | "stream_copy" | "reencode";
  force_rerender?: boolean;
}

export interface BatchProgressResponse {
  status: string;
  current: number;
  total: number;
  percentage: number;
  step: string;
  current_name: string;
  started?: number;
  active?: string[];
  logs?: string[];
  total_time?: number;
}

export interface CatboxUploadResult {
  status: "uploaded";
  url: string;
  filename: string;
  expires_in: string;
  timings?: {
    ffmpeg?: number;
    catbox?: number;
    total?: number;
  };
  log?: string;
  logs?: string[];
}

export interface BatchCatboxResult {
  status: "completed";
  videos: Array<{ filename: string; url: string; status: string }>;
  errors: string[];
  expires_in: string;
}

export interface GeminiModelsResponse {
  default_model: string;
  models: string[];
}

export interface TokenSettingsResponse {
  fish_api_key?: string;
  fish_enhance_token?: string;
  google_api_key?: string;
  title_model?: string;
  translation_model?: string;
  stt_engine?: "stable" | "crisper";
  fish_auto_emotions?: boolean;
  fish_enhance_version?: "s2.1-pro" | "drama-3";
  available_models?: string[];
  message?: string;
}

export interface FishEnhanceTestResponse {
  ok: boolean;
  status: number;
  message: string;
  preview?: string | null;
}

export interface RegenerateTitlePayload {
  job_id?: string;
  video_index?: number;
  folder_name?: string;
  model_name?: string;
  custom_title?: string;
  target_lang?: string;
}

export interface RegenerateTitleResponse {
  status: string;
  output_name: string;
  model_used?: string;
  message?: string;
}

/**
 * Desempaqueta un stream TAR estándar de forma nativa en JS (sin dependencias).
 * Retorna un mapa filename -> Blob (audio/wav).
 */
export function parseTarArchive(buffer: ArrayBuffer): Map<string, Blob> {
  const result = new Map<string, Blob>();
  const bytes = new Uint8Array(buffer);
  let offset = 0;

  while (offset + 512 <= bytes.length) {
    if (bytes[offset] === 0) break;

    // Nombre de archivo en los primeros 100 bytes
    let filename = "";
    for (let i = 0; i < 100; i++) {
      if (bytes[offset + i] === 0) break;
      filename += String.fromCharCode(bytes[offset + i]);
    }
    filename = filename.trim().split("/").pop() || filename.trim();

    // Tamaño del archivo en octal en bytes 124..136
    let sizeStr = "";
    for (let i = 124; i < 136; i++) {
      if (bytes[offset + i] === 0 || bytes[offset + i] === 32) break;
      sizeStr += String.fromCharCode(bytes[offset + i]);
    }
    const fileSize = parseInt(sizeStr.trim(), 8) || 0;

    offset += 512;

    if (fileSize > 0 && offset + fileSize <= bytes.length) {
      const isWav = filename.endsWith(".wav") || filename.includes(".wav");
      const isM4a = filename.endsWith(".m4a") || filename.includes(".m4a");
      const isMp3 = filename.endsWith(".mp3") || filename.includes(".mp3");
      if (isWav || isM4a || isMp3) {
        const fileContent = bytes.slice(offset, offset + fileSize);
        const mimeType = isM4a ? "audio/mp4" : isMp3 ? "audio/mpeg" : "audio/wav";
        result.set(filename, new Blob([fileContent], { type: mimeType }));
      }
      offset += Math.ceil(fileSize / 512) * 512;
    }
  }

  return result;
}

export const v2vApi = {
  async processUrls(
    urls: string[],
    translateLang: string | null,
    speaker: string,
    emotion?: string | null,
    options?: {
      forceReprocess?: boolean;
      speakerMap?: Record<string, string>;
      initialEmotionPerSentence?: boolean;
      initialEmotionTag?: string;
    },
    signal?: AbortSignal,
  ): Promise<ProcessUrlsResponse> {
    const res = await fetch(url("/api/process-urls"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify({
        urls,
        translate_lang: translateLang,
        speaker,
        emotion: emotion || null,
        force_reprocess: options?.forceReprocess ?? false,
        speaker_map: options?.speakerMap,
        initial_emotion_per_sentence: options?.initialEmotionPerSentence ?? false,
        initial_emotion_tag: options?.initialEmotionTag ?? "auto",
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText || "Error al procesar");
    }
    return readJsonOrThrow<ProcessUrlsResponse>(res);
  },

  getJobWebSocketUrl(jobId: string): string {
    const httpUrl = url(`/ws/job/${jobId}`);
    if (httpUrl.startsWith("http://")) {
      return httpUrl.replace("http://", "ws://");
    } else if (httpUrl.startsWith("https://")) {
      return httpUrl.replace("https://", "wss://");
    }
    if (typeof window !== "undefined") {
      const isDesktop = window.location.protocol === "app:" || (window as any).openreel?.platform === "desktop";
      if (isDesktop) {
        const base = getEffectiveBackendUrl();
        if (base.startsWith("https://")) return `${base.replace("https://", "wss://")}/ws/job/${jobId}`;
        if (base.startsWith("http://")) return `${base.replace("http://", "ws://")}/ws/job/${jobId}`;
      }
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      return `${proto}//${window.location.host}${httpUrl}`;
    }
    return `ws://localhost:8000/ws/job/${jobId}`;
  },

  async getVideoSpeakers(
    jobId: string,
    videoIndex: number,
  ): Promise<{ job_id: string; video_index: number; detected_speakers: string[]; speaker_map: Record<string, string> }> {
    const res = await fetch(url(`/api/job/${jobId}/speakers/${videoIndex}`));
    if (!res.ok) throw new Error("Error al obtener speakers del video");
    return readJsonOrThrow(res);
  },

  async updateSpeakerMap(
    jobId: string,
    videoIndex: number,
    speakerMap: Record<string, string>,
  ): Promise<{ job_id: string; video_index: number; detected_speakers: string[]; speaker_map: Record<string, string> }> {
    const res = await fetch(url(`/api/job/${jobId}/speakers/${videoIndex}/map`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ speaker_map: speakerMap }),
    });
    if (!res.ok) throw new Error("Error al actualizar speaker map");
    return readJsonOrThrow(res);
  },

  async getJobStatus(jobId: string): Promise<JobStatusResponse> {
    const { signal, cleanup } = createTimeoutSignal(METADATA_TIMEOUT_MS);
    try {
      const res = await fetch(url(`/api/job/${jobId}/status`), { signal });
      if (!res.ok) throw new Error("Error al obtener estado");
      return await readJsonOrThrow<JobStatusResponse>(res);
    } finally {
      cleanup();
    }
  },

  async getJobResult(jobId: string): Promise<JobResultResponse> {
    const { signal, cleanup } = createTimeoutSignal(METADATA_TIMEOUT_MS);
    try {
      const res = await fetch(url(`/api/job/${jobId}/result`), { signal });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Error al obtener resultado");
      }
      return await readJsonOrThrow<JobResultResponse>(res);
    } finally {
      cleanup();
    }
  },

  getFileUrl(jobId: string, videoIndex: number, filename: string): string {
    return url(`/api/job/${jobId}/files/${videoIndex}/${encodeURIComponent(filename)}`);
  },

  async fetchAssetBlob(
    jobId: string,
    videoIndex: number,
    assetKey: string
  ): Promise<Blob> {
    const { buffer, contentType } = await fetchBufferWithGuards(
      url(`/api/job/${jobId}/asset/${videoIndex}/${assetKey}`),
      { label: `activo '${assetKey}'`, parallelRanges: true }
    );
    return new Blob([buffer], { type: contentType || "application/octet-stream" });
  },

  async fetchFileBlob(
    jobId: string,
    videoIndex: number,
    filename: string
  ): Promise<Blob> {
    const { buffer, contentType } = await fetchBufferWithGuards(
      url(`/api/job/${jobId}/files/${videoIndex}/${encodeURIComponent(filename)}`),
      { label: filename, parallelRanges: true }
    );
    return new Blob([buffer], { type: contentType || "application/octet-stream" });
  },

  async fetchOutputVideoBlob(jobId: string, videoIndex: number): Promise<Blob> {
    // Endpoint nuevo: evita pasar `filename` (unicode/largo) en la URL.
    const { buffer, contentType } = await fetchBufferWithGuards(
      url(`/api/job/${jobId}/files/${videoIndex}`),
      { label: `video ${videoIndex + 1}`, parallelRanges: true }
    );
    return new Blob([buffer], { type: contentType || "video/mp4" });
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
      phonemes?: Record<string, string>;
      prevent_overlap?: boolean;
      signal?: AbortSignal;
    },
    signal?: AbortSignal,
  ): Promise<Blob> {
    const abortSignal = signal || options?.signal;
    const { blob } = await fetchBlobWithStallGuard(
      url("/api/regenerate-segment"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: abortSignal,
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
          phonemes: options?.phonemes,
          prevent_overlap: options?.prevent_overlap,
        }),
      },
      {
        label: `regenerar segmento ${segIdx}`,
        headerTimeoutMs: GENERATION_HEADER_TIMEOUT_MS,
      }
    );
    return blob;
  },

  async generateNewAudioSegment(
    jobId: string,
    videoIndex: number,
    text: string,
    speaker: string,
    options?: GenerateAudioSegmentOptions,
  ): Promise<GeneratedAudioResult> {
    const { blob, res } = await fetchBlobWithStallGuard(
      url("/api/generate-audio-segment"),
      {
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
          phonemes: options?.phonemes,
          preview: options?.preview ?? false,
        }),
      },
      {
        label: "generar segmento de audio",
        headerTimeoutMs: GENERATION_HEADER_TIMEOUT_MS,
      }
    );
    const segIdx = parseInt(res.headers.get("x-seg-idx") || "0", 10);
    const duration = parseFloat(res.headers.get("x-audio-duration") || "0");
    const filename =
      res.headers.get("x-audio-filename") ||
      `tts_${speaker}_${String(segIdx).padStart(3, "0")}.wav`;
    return { blob, segIdx, duration, filename };
  },

  async applyAudioSpeed(
    jobId: string,
    videoIndex: number,
    segIdx: number,
    speed: number | null,
    targetDuration?: number
  ): Promise<Blob> {
    const { blob } = await fetchBlobWithStallGuard(
      url("/api/apply-speed"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: jobId,
          video_index: videoIndex,
          seg_idx: segIdx,
          speed,
          target_duration: targetDuration,
        }),
      },
      {
        label: `aplicar velocidad al segmento ${segIdx}`,
        headerTimeoutMs: GENERATION_HEADER_TIMEOUT_MS,
      }
    );
    return blob;
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

  async getAudioSegments(jobId: string, videoIndex: number): Promise<AudioSegmentItem[]> {
    const { signal, cleanup } = createTimeoutSignal(METADATA_TIMEOUT_MS);
    try {
      const res = await fetch(url(`/api/job/${jobId}/audio-segments/${videoIndex}`), { signal });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Error al listar segmentos de audio");
      }
      return await readJsonOrThrow<AudioSegmentItem[]>(res);
    } finally {
      cleanup();
    }
  },

  audioSegmentUrl(jobId: string, videoIndex: number, seg: number): string {
    return url(`/api/job/${encodeURIComponent(jobId)}/audio-segments/${videoIndex}/${seg}`);
  },

  async fetchAudioSegmentBlob(jobId: string, videoIndex: number, seg: number): Promise<Blob> {
    const { buffer, contentType } = await fetchBufferWithGuards(
      url(`/api/job/${jobId}/audio-segments/${videoIndex}/${seg}`),
      { label: `segmento de audio ${seg}` }
    );
    return new Blob([buffer], { type: contentType || "audio/mp4" });
  },

  /**
   * Descarga todos los segmentos WAV de un video en una sola petición empaquetada (TAR).
   * Reduce radicalmente el tiempo de descarga a través de túneles (de 30s a 1s).
   */
  async fetchAudioSegmentsTar(
    jobId: string,
    videoIndex: number,
    externalSignal?: AbortSignal
  ): Promise<Map<string, Blob>> {
    let buffer = await fetchTarBuffer(
      url(`/api/job/${jobId}/audio-segments-tar/${videoIndex}`),
      externalSignal
    );

    // Si el buffer aún tiene magic bytes de gzip (0x1f, 0x8b), lo descomprimimos nativamente
    const head = new Uint8Array(buffer, 0, Math.min(2, buffer.byteLength));
    if (head.length >= 2 && head[0] === 0x1f && head[1] === 0x8b) {
      if (typeof DecompressionStream !== "undefined") {
        try {
          const ds = new DecompressionStream("gzip");
          const decompressedRes = new Response(new Blob([buffer]).stream().pipeThrough(ds));
          buffer = await decompressedRes.arrayBuffer();
        } catch (e) {
          console.warn("[V2V] Error descomprimiendo gzip de TAR:", e);
        }
      }
    }

    return parseTarArchive(buffer);
  },

  async getSrcAudioSegments(jobId: string, videoIndex: number): Promise<AudioSegmentItem[]> {
    const { signal, cleanup } = createTimeoutSignal(METADATA_TIMEOUT_MS);
    try {
      const res = await fetch(url(`/api/job/${jobId}/src-audio-segments/${videoIndex}`), { signal });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Error al listar segmentos de audio originales");
      }
      return await readJsonOrThrow<AudioSegmentItem[]>(res);
    } finally {
      cleanup();
    }
  },

  async fetchSrcAudioSegmentBlob(jobId: string, videoIndex: number, seg: number): Promise<Blob> {
    const { buffer, contentType } = await fetchBufferWithGuards(
      url(`/api/job/${jobId}/src-audio-segments/${videoIndex}/${seg}`),
      { label: `segmento original ${seg}` }
    );
    return new Blob([buffer], { type: contentType || "audio/mp4" });
  },

  /**
   * Descarga todos los segmentos WAV originales de un video en un paquete TAR empaquetado.
   */
  async fetchSrcAudioSegmentsTar(
    jobId: string,
    videoIndex: number,
    externalSignal?: AbortSignal
  ): Promise<Map<string, Blob>> {
    let buffer = await fetchTarBuffer(
      url(`/api/job/${jobId}/src-audio-segments-tar/${videoIndex}`),
      externalSignal
    );

    const head = new Uint8Array(buffer, 0, Math.min(2, buffer.byteLength));
    if (head.length >= 2 && head[0] === 0x1f && head[1] === 0x8b) {
      if (typeof DecompressionStream !== "undefined") {
        try {
          const ds = new DecompressionStream("gzip");
          const decompressedRes = new Response(new Blob([buffer]).stream().pipeThrough(ds));
          buffer = await decompressedRes.arrayBuffer();
        } catch (e) {
          console.warn("[V2V] Error descomprimiendo gzip de TAR original:", e);
        }
      }
    }

    return parseTarArchive(buffer);
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
    customTexts?: Record<number, string>,
  ): Promise<{ segments: Array<{ seg: number; text: string; phonemes?: Record<string, string> }> }> {
    const res = await fetch(url("/api/retranslate-segments"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: jobId,
        video_index: videoIndex,
        seg_indices: segIndices,
        target_lang: targetLang ?? null,
        custom_texts: customTexts ?? null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al retraducir segmentos");
    }
    return readJsonOrThrow<{ segments: Array<{ seg: number; text: string; phonemes?: Record<string, string> }> }>(res);
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
  async renderTimeline(payload: RenderTimelinePayload, signal?: AbortSignal): Promise<Blob | CatboxUploadResult> {
    const target = url("/api/render/timeline");
    const init = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify(payload),
    };

    // Si se solicitó upload a Catbox, la respuesta es un JSON pequeño.
    if (payload.upload_to_catbox) {
      const res = await fetch(target, init);
      if (!res.ok) throw await responseError(res, "render de timeline");
      return readJsonOrThrow<CatboxUploadResult>(res);
    }

    // El render puede tardar minutos: sin tope de cabeceras, pero con guarda
    // de estancamiento mientras llega el MP4.
    const { blob, res } = await fetchBlobWithStallGuard(target, init, {
      label: "render de timeline",
    });
    const ffTime = res.headers.get("X-Render-Time-Ffmpeg");
    const totTime = res.headers.get("X-Render-Time-Total");
    const isCached = res.headers.get("X-Render-Cached") === "1";
    const mode = res.headers.get("X-Render-Mode") || undefined;
    if (ffTime || totTime || mode) {
      (blob as any).timings = {
        ffmpeg: ffTime ? parseFloat(ffTime) : undefined,
        total: totTime ? parseFloat(totTime) : undefined,
        cached: isCached,
        mode: mode,
      };
    }
    return blob;
  },

  /**
   * Render multiple projects on Colab via FFmpeg.
   * Returns a Blob (ZIP) for direct download, or BatchCatboxResult if upload_to_catbox is true.
   */
  async renderBatch(payload: RenderBatchPayload, signal?: AbortSignal): Promise<Blob | BatchCatboxResult> {
    const target = url("/api/render/batch");
    const init = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify(payload),
    };

    // Si se solicitó upload a Catbox, la respuesta es un JSON pequeño.
    if (payload.upload_to_catbox) {
      const res = await fetch(target, init);
      if (!res.ok) throw await responseError(res, "render batch");
      return readJsonOrThrow<BatchCatboxResult>(res);
    }

    // El ZIP se genera después de renderizar todos los proyectos: sin tope de
    // cabeceras, pero con guarda de estancamiento durante la descarga.
    const { blob } = await fetchBlobWithStallGuard(target, init, { label: "render batch" });
    return blob;
  },

  async getBatchProgress(batchId: string): Promise<BatchProgressResponse> {
    const res = await fetch(url(`/api/render/batch/progress/${encodeURIComponent(batchId)}`));
    if (!res.ok) {
      return { status: "idle", current: 0, total: 0, percentage: 0, step: "", current_name: "" };
    }
    return readJsonOrThrow<BatchProgressResponse>(res);
  },

  async poll(jobId: string): Promise<PollResponse> {
    const { signal, cleanup } = createTimeoutSignal(METADATA_TIMEOUT_MS);
    try {
      const res = await fetch(url(`/api/job/${jobId}/poll`), { signal });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Error al sincronizar estado del job");
      }
      return await readJsonOrThrow<PollResponse>(res);
    } finally {
      cleanup();
    }
  },

  async reconcileJobs(): Promise<{ jobs: Array<{ job_id: string; status: string; message: string; video_count: number; videos: any[] }> }> {
    const res = await fetch(url("/api/jobs/reconcile"));
    if (!res.ok) {
      return { jobs: [] };
    }
    return readJsonOrThrow(res);
  },

  async deleteVideo(folderName?: string, urlToRemove?: string): Promise<{ status: string; message: string }> {
    const params = new URLSearchParams();
    if (folderName) params.append("folder_name", folderName);
    if (urlToRemove) params.append("url", urlToRemove);
    const endpoint = params.toString() ? `/api/video?${params.toString()}` : `/api/video/${encodeURIComponent(folderName || "")}`;
    const res = await fetch(url(endpoint), {
      method: "DELETE",
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al borrar carpeta de vídeo");
    }
    return await readJsonOrThrow<{ status: string; message: string }>(res);
  },

  async getTokens(): Promise<TokenSettingsResponse> {
    const res = await fetch(url("/api/settings/tokens"));
    if (!res.ok) throw new Error("Error al obtener la configuración de tokens y modelos");
    return readJsonOrThrow<TokenSettingsResponse>(res);
  },

  async saveTokens(
    fishApiKey?: string,
    googleApiKey?: string,
    titleModel?: string,
    translationModel?: string,
    sttEngine?: "stable" | "crisper",
    fishAutoEmotions?: boolean,
    fishEnhanceVersion?: "s2.1-pro" | "drama-3",
    fishEnhanceToken?: string
  ): Promise<TokenSettingsResponse> {
    const res = await fetch(url("/api/settings/tokens"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fish_api_key: fishApiKey || null,
        fish_enhance_token: fishEnhanceToken ?? null,
        google_api_key: googleApiKey || null,
        title_model: titleModel || null,
        translation_model: translationModel || null,
        stt_engine: sttEngine || null,
        fish_auto_emotions: fishAutoEmotions ?? null,
        fish_enhance_version: fishEnhanceVersion || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al actualizar la configuración de tokens y modelos");
    }
    return readJsonOrThrow(res);
  },

  async testFishEnhance(
    token?: string,
    version?: "s2.1-pro" | "drama-3"
  ): Promise<FishEnhanceTestResponse> {
    const res = await fetch(url("/api/settings/fish-enhance/test"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: token || null,
        version: version || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al probar el token de Fish");
    }
    return readJsonOrThrow<FishEnhanceTestResponse>(res);
  },

  async getGeminiModels(): Promise<GeminiModelsResponse> {
    const res = await fetch(url("/api/render/gemini-models"));
    if (!res.ok) {
      return {
        default_model: "gemini-flash-lite-latest",
        models: [
          "gemini-flash-lite-latest",
          "gemma-4-26b-a4b-it",
        ],
      };
    }
    return readJsonOrThrow<GeminiModelsResponse>(res);
  },

  async setGeminiDefaultModel(modelName: string): Promise<{ status: string; default_model: string }> {
    const res = await fetch(url("/api/render/gemini-models/default"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name: modelName }),
    });
    if (!res.ok) throw new Error("Error al cambiar modelo de Gemini");
    return readJsonOrThrow(res);
  },

  async regenerateTitle(payload: RegenerateTitlePayload): Promise<RegenerateTitleResponse> {
    const res = await fetch(url("/api/render/regenerate-title"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al generar título viral");
    }
    return readJsonOrThrow<RegenerateTitleResponse>(res);
  },

  async checkHealth(): Promise<{ ok: boolean; status?: number; error?: string }> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 4000);
      const res = await fetch(url("/health"), { signal: controller.signal });
      clearTimeout(timeoutId);
      return { ok: res.ok, status: res.status };
    } catch (e: any) {
      return { ok: false, error: e?.message || "Sin conexión con el backend" };
    }
  },

  getBackendUrl(): string {
    return getEffectiveBackendUrl();
  },

  setBackendUrl(newUrl: string): void {
    setCustomBackendUrl(newUrl);
  },
};

