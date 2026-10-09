import type { Coord } from "../types";
import type { Walk } from "./api";

/** A walk starting this close counts as starting from your doorstep. */
export const DOORSTEP_KM = 1;

/**
 * Walks starting further than this are not shown at all.
 *
 * Founder decision, 9 Oct: nothing more than about an hour's drive away - Berlin
 * walks listed for someone in Windsor were noise. This is a straight-line
 * approximation of an hour's drive (60 km is roughly that across most of the
 * UK), not a measured drive time; measuring it would cost a routing request
 * per walk.
 */
export const MAX_KM = 60;

/** Rounding room: 15% means "about 15%", not a hard 0.150. */
const RETRACE_SLACK = 0.02;

export interface WalkPrefs {
  /** Most of a walk that may retrace ground already walked (0 to 1). */
  maxRetrace: number;
  /** Show walks that need driving or travelling to the start. */
  allowTravel: boolean;
}

export function kmBetween(a: Coord, b: { lat: number; lng: number }): number {
  const r = (d: number) => (d * Math.PI) / 180;
  const h =
    Math.sin(r(b.lat - a.lat) / 2) ** 2 +
    Math.cos(r(a.lat)) * Math.cos(r(b.lat)) * Math.sin(r(b.lng - a.lng) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

function fitsTime(w: Walk): boolean {
  return !w.fit || w.fit.kind === "turned" || w.fit.kind === "about_right";
}

export interface Grouped {
  /** Whether a position was known - without one, nothing is called doorstep. */
  located: boolean;
  doorstep: Walk[];
  /** Need travel to the start; nearest first, each with its distance. */
  travel: { walk: Walk; km: number }[];
  /** Shorter or longer than the time asked for. */
  other: Walk[];
  /** Counts only - hidden walks are said to exist, never silently dropped. */
  hidden: { outAndBack: number; travel: number };
}

/**
 * Sort walks into what you can start now, what needs a journey first, and what
 * does not fit the time - applying your preferences, and saying how many each
 * preference hid. Runs on the device; the position is not sent for it.
 */
export function groupWalks(walks: Walk[], here: Coord | null, prefs: WalkPrefs): Grouped {
  const g: Grouped = {
    located: here !== null,
    doorstep: [],
    travel: [],
    other: [],
    hidden: { outAndBack: 0, travel: 0 },
  };
  for (const w of walks) {
    const km = here ? kmBetween(here, w.start) : null;
    if (km !== null && km > MAX_KM) continue;
    if (w.retrace_share > prefs.maxRetrace + RETRACE_SLACK) {
      g.hidden.outAndBack += 1;
      continue;
    }
    const needsTravel = km !== null && km > DOORSTEP_KM;
    if (needsTravel && !prefs.allowTravel) {
      g.hidden.travel += 1;
      continue;
    }
    if (!fitsTime(w)) g.other.push(w);
    else if (needsTravel) g.travel.push({ walk: w, km: km as number });
    else g.doorstep.push(w);
  }
  g.travel.sort((a, b) => a.km - b.km);
  return g;
}
