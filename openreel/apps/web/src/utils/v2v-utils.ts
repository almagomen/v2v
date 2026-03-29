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
