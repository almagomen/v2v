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

export function shortProjectToken(name: string): string {
  const s = (name || "video")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9._ -]+/g, " ")
    .trim();
  const firstWords = s.split(/\s+/).filter(Boolean).slice(0, 2).join(" ");
  const compact = firstWords.replace(/\s+/g, "_").slice(0, 16);
  return compact || "video";
}

export function importKeyFor(url: string, index: number): string {
  return `${encodeURIComponent(url)}|${index}`;
}
