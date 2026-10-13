import type { Units } from "../hooks/useSettings";

/**
 * Distances inside the server's sentences, in the parent's units (founder's
 * phone, 13 Oct 2026: "Surface not recorded for about 4500 m ... after 0 yd"
 * with miles chosen). The server writes metres; the units live on the device.
 */
export function metresInText(text: string, units: Units): string {
  return text.replace(/\b(\d[\d,]*(?:\.\d+)?) m\b/g, (_all, raw: string) => {
    const m = Number(raw.replace(/,/g, ""));
    if (!Number.isFinite(m)) return `${raw} m`;
    if (units === "mi") {
      return m >= 800 ? `${(m / 1609.344).toFixed(1)} mi` : `${Math.round((m * 1.0936) / 10) * 10} yd`;
    }
    return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${raw} m`;
  });
}

/** Where along the walk, or "at the start" for the first few metres. */
export function alongText(m: number | null, units: Units): string {
  if (m == null) return "";
  if (m < 10) return "at the start";
  if (units === "mi") return `after ${Math.round(m * 1.0936)} yd`;
  return `after ${Math.round(m / 10) * 10} m`;
}
