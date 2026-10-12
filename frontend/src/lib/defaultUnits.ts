import type { Units } from "../hooks/useSettings";

/**
 * Miles where the roads are signed in miles, km elsewhere (founder, 12 Oct
 * 2026: in the UK miles should be the default). Read from the device: a UK
 * time zone, or a region of GB, US, LR or MM in its language settings.
 * Ireland uses km. Only a default: choosing units in Settings overrides it.
 */
const MILES_REGIONS = new Set(["GB", "US", "LR", "MM"]);
const UK_ZONES = new Set(["Europe/London", "Europe/Isle_of_Man", "Europe/Jersey", "Europe/Guernsey"]);

export function unitsFor(timeZone: string | undefined, languages: readonly string[]): Units {
  if (timeZone && UK_ZONES.has(timeZone)) return "mi";
  for (const tag of languages) {
    const region = tag.split(/[-_]/)[1]?.toUpperCase();
    if (region && region.length === 2) return MILES_REGIONS.has(region) ? "mi" : "km";
  }
  return "km";
}

export function defaultUnits(): Units {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const langs = typeof navigator !== "undefined" ? navigator.languages ?? [navigator.language] : [];
    return unitsFor(tz, langs);
  } catch {
    return "km";
  }
}
