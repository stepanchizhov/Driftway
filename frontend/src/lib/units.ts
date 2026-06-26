import type { Units } from "../hooks/useSettings";

// Distances are stored and computed in kilometres everywhere (canonical metric).
// This is the only place they get converted, and only for display. Duration is
// always minutes and unaffected by the units setting.

const KM_PER_MILE = 1.609344;

export function formatDistance(km: number, units: Units): string {
  if (units === "mi") {
    const mi = km / KM_PER_MILE;
    return `${Math.round(mi)} mi`;
  }
  return `${Math.round(km)} km`;
}
