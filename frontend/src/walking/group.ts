import type { Coord } from "../types";
import type { Walk } from "./api";

/** Walks starting within this distance count as near you. */
export const NEAR_KM = 25;

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

/**
 * Split walks into: near you and fitting the time; near you but shorter or
 * longer; and further away, nearest first.
 *
 * Founder feedback, 9 Oct: one undivided list put 20-minute walks beside walks
 * fitted to an hour, and Berlin walks beside Windsor ones. Without a position
 * every walk counts as near, so nothing is hidden from someone who has not
 * shared one. Runs on the device; the position is not sent anywhere for it.
 */
export function groupWalks(walks: Walk[], here: Coord | null) {
  const near = here ? walks.filter((w) => kmBetween(here, w.start) <= NEAR_KM) : walks;
  const far = here
    ? walks
        .filter((w) => kmBetween(here, w.start) > NEAR_KM)
        .sort((a, b) => kmBetween(here, a.start) - kmBetween(here, b.start))
    : [];
  return {
    fitting: near.filter(fitsTime),
    other: near.filter((w) => !fitsTime(w)),
    far,
  };
}
