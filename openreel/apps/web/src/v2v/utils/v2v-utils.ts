/**
 * V2V Utility functions for consistent naming and tokenization across the app.
 */

export function toSafeToken(s: string): string {
  const ascii = s
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .replace(/^[\_\.\-\\]+|[\_\.\-\\]+$/g, "")
    .slice(0, 40);
  return ascii || "speaker";
}

export function sanitizeFolderName(name: string): string {
  // El folder se infiere por `Carpeta/archivo`, así que evitamos `/`.
  const cleaned = (name || "Video").replaceAll("/", "_").replaceAll("\\", "_").trim();
  return cleaned || "Video";
}

/**
 * Deriva el nombre de carpeta / proyecto a partir del output_name generado por IA.
 * Elimina los hashtags (#palabra) ya que son para redes sociales, no para carpetas.
 * El output_name completo (con hashtags) se conserva como título del render final.
 *
 * Ejemplo:
 *   "¡Truco de Python! 🤫 #Programacion #Python" → "¡Truco de Python! 🤫"
 */
export function folderNameFromTitle(outputName: string): string {
  const withoutHashtags = (outputName || "Video")
    .replace(/#\S+/g, "")   // quitar #hashtags
    .replace(/\s{2,}/g, " ") // colapsar espacios dobles
    .trim();
  // Luego aplicar el saneado de caracteres inválidos en paths
  return sanitizeFolderName(withoutHashtags) || "Video";
}

export type V2VParsedSegment = {
  folder: string;
  speakerToken: string;
  segIdx: number;
};

/** Parsea nombres de medios importados desde V2V (tts_/gen_ en carpeta de job). */
export type SegmentNameInput = {
  seg: number;
  speaker?: string;
  filename?: string;
};

/** Ruta lógica en Media (`carpeta/tts_…_NNN.wav`) alineada con el WAV real en Colab. */
export function segmentLogicalName(seg: SegmentNameInput): string {
  const base =
    seg.filename?.trim() ||
    `tts_${toSafeToken(seg.speaker || "speaker")}_${String(seg.seg).padStart(3, "0")}.wav`;
  // Extraemos el basename por si acaso venía con un path
  return base.split("/").pop() || base;
}

/** Busca un ítem de media por nombre lógico o por sufijo tts_*_{seg}.wav */
export function findSegmentMediaInLibrary<
  T extends { name: string },
>(items: T[], seg: SegmentNameInput): T | undefined {
  const logical = segmentLogicalName(seg);
  const exact = items.find((m) => m.name === logical || m.name.endsWith(`/${logical}`));
  if (exact) return exact;

  const suffix = `_${String(seg.seg).padStart(3, "0")}.wav`;
  return items.find((m) => {
    const norm = m.name.replace(/\\/g, "/");
    return /(?:tts_|gen_).*/.test(norm) && norm.endsWith(suffix);
  });
}

export function parseV2VSegmentFromName(name: string): V2VParsedSegment | null {
  const normalized = name.replace(/\\/g, "/");
  const basename = normalized.split("/").pop() || normalized;
  const match = basename.match(/^(?:tts_|gen_)(.+)_(\d{3})\.wav$/);
  if (!match) return null;
  const speakerToken = match[1];
  const segIdx = parseInt(match[2], 10);
  if (!Number.isNaN(segIdx)) {
    return { folder: "Video", speakerToken, segIdx }; // El folder ya no existe en el nombre, usamos un dummy para retrocompatibilidad estructural si es necesario
  }
  return null;
}

export function shortProjectToken(name: string): string {
  const s = (name || "video")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9._ -]+/g, " ")
    .trim();
  const words = s.split(/\s+/).filter(Boolean).slice(0, 3);
  const firstWords = words.join(" ");
  const compact = firstWords.replace(/\s+/g, "_").slice(0, 24);
  return compact || "video";
}

export function importKeyFor(url: string, index: number): string {
  return `${encodeURIComponent(url)}|${index}`;
}

/**
 * Extrae la duración física real en segundos leyendo la cabecera RIFF/WAVE de un Blob WAV (sin decodificar todo el audio).
 * Devuelve la duración en segundos con precisión de milisegundos, o null si no es un WAV válido.
 */
export async function getWavBlobDuration(blob: Blob): Promise<number | null> {
  try {
    const slice = blob.slice(0, 100);
    const buffer = await slice.arrayBuffer();
    if (!buffer || buffer.byteLength < 44) return null;
    const view = new DataView(buffer);
    const riff = String.fromCharCode(view.getUint8(0), view.getUint8(1), view.getUint8(2), view.getUint8(3));
    const wave = String.fromCharCode(view.getUint8(8), view.getUint8(9), view.getUint8(10), view.getUint8(11));
    if (riff !== "RIFF" || wave !== "WAVE") return null;
    const byteRate = view.getUint32(28, true);
    if (byteRate > 0) {
      const dataSize = Math.max(0, blob.size - 44);
      const dur = dataSize / byteRate;
      if (dur > 0 && isFinite(dur)) {
        return Math.round(dur * 1000) / 1000;
      }
    }
    return null;
  } catch {
    return null;
  }
}
