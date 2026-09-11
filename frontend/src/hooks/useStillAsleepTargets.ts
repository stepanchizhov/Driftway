import { useMemo } from "react";
import type { Coord } from "../types";
import type { Place } from "./usePlaces";
import type { RecentDestination } from "./useRecentDestination";
import { isRecentEnough } from "../lib/stillAsleepConfig";

/** Somewhere Still Asleep can send you, with no typing. */
export interface StillAsleepTarget {
  id: string;
  label: string;
  detail?: string;
  coord: Coord;
  /**
   * "home" and "saved" are places the parent deliberately kept.
   * "recent" is a destination they merely searched for, and is offered only
   * while genuinely recent.
   */
  kind: "home" | "saved" | "recent";
}

/**
 * Build the target list for Still Asleep.
 *
 * The ordering rule matters more than it looks. Bible v0.4 §6: a recent
 * destination is an *additional* choice and must never replace or silently
 * override a saved one. So saved places come first and always appear; a
 * recent search is appended, and only while it is fresh.
 *
 * The failure this avoids: a parent searches for a friend's house once, and
 * for the next week the app quietly offers that instead of Home when they
 * tap the urgent button with a sleeping child in the back.
 */
export function buildStillAsleepTargets(
  places: Place[],
  recent: RecentDestination | null,
  now?: number,
): StillAsleepTarget[] {
  const targets: StillAsleepTarget[] = [];

  const home = places.find((p) => p.isDefault) ?? places.find((p) => p.label === "Home");
  if (home) {
    targets.push({
      id: `place-${home.id}`,
      label: home.label || "Home",
      coord: { lat: home.lat, lng: home.lng },
      kind: "home",
    });
  }

  for (const place of places) {
    if (home && place.id === home.id) continue;
    targets.push({
      id: `place-${place.id}`,
      label: place.label || "Saved place",
      coord: { lat: place.lat, lng: place.lng },
      kind: "saved",
    });
  }

  // Appended, never inserted above a saved place, and only while fresh.
  if (recent && isRecentEnough(recent.savedAt, { now })) {
    const duplicate = targets.some(
      (t) =>
        Math.abs(t.coord.lat - recent.lat) < 1e-5 &&
        Math.abs(t.coord.lng - recent.lng) < 1e-5,
    );
    if (!duplicate) {
      targets.push({
        id: "recent",
        label: recent.label,
        detail: recent.detail,
        coord: { lat: recent.lat, lng: recent.lng },
        kind: "recent",
      });
    }
  }

  return targets;
}

/** React wrapper. All the judgement lives in buildStillAsleepTargets. */
export function useStillAsleepTargets(
  places: Place[],
  recent: RecentDestination | null,
  now?: number,
): StillAsleepTarget[] {
  return useMemo(
    () => buildStillAsleepTargets(places, recent, now),
    [places, recent?.lat, recent?.lng, recent?.label, recent?.savedAt, now],
  );
}
