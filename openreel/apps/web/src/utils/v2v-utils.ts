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
export function segmentLogicalName(folder: string, seg: SegmentNameInput): string {
  const base =
    seg.filename?.trim() ||
    `tts_${toSafeToken(seg.speaker || "speaker")}_${String(seg.seg).padStart(3, "0")}.wav`;
  return base.includes("/") ? base : `${folder}/${base}`;
}

/** Busca un ítem de media por nombre lógico o por sufijo tts_*_{seg}.wav */
export function findSegmentMediaInLibrary<
  T extends { name: string },
>(items: T[], folder: string, seg: SegmentNameInput): T | undefined {
  const logical = segmentLogicalName(folder, seg);
  const exact = items.find((m) => m.name === logical);
  if (exact) return exact;

  const suffix = `_${String(seg.seg).padStart(3, "0")}.wav`;
  return items.find((m) => {
    const norm = m.name.replace(/\\/g, "/");
    return norm.startsWith(`${folder}/`) && /(?:tts_|gen_).*/.test(norm) && norm.endsWith(suffix);
  });
}

export function parseV2VSegmentFromName(name: string): V2VParsedSegment | null {
  const normalized = name.replace(/\\/g, "/");
  const match = normalized.match(/^(?:(.+?)\/)?(tts_|gen_)(.+)_(\d{3})\.wav$/);
  if (!match) return null;
  const folder = match[1];
  const speakerToken = match[3];
  const segIdx = parseInt(match[4], 10);
  if (folder && !Number.isNaN(segIdx)) {
    return { folder, speakerToken, segIdx };
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
