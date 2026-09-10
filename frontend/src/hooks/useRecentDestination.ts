import { useCallback, useEffect, useState } from "react";
import type { Coord } from "../types";

/**
 * The last destination the parent looked at, held on the device.
 *
 * This is what makes delayed arrival a one-tap action. The baby falls asleep
 * during a brief stop; the parent has seconds and one hand. Re-entering a
 * destination through a search field is not viable then, so the app has to
 * already know where they were heading.
 *
 * Deliberately local-only, like saved places: it is travel data, and the
 * privacy position in the Bible is that nothing about where a family drives
 * leaves the device unless a convenience feature needs it.
 */
export interface RecentDestination {
  label: string;
  detail?: string;
  lat: number;
  lng: number;
  /** Epoch ms, so a stale destination can stop being offered. */
  savedAt: number;
}

const KEY = "driftway.recentDestination.v1";

/**
 * How long a remembered destination stays on offer.
 *
 * HYPOTHESIS. Long enough to cover a routine ("swimming on Tuesdays"), short
 * enough that the app is not still suggesting a holiday cottage in March.
 * Tune from real use.
 */
export const RECENT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

export function isFresh(dest: RecentDestination | null, now = Date.now()): boolean {
  if (!dest) return false;
  return now - dest.savedAt <= RECENT_MAX_AGE_MS;
}

function load(): RecentDestination | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as RecentDestination;
    if (typeof parsed?.lat !== "number" || typeof parsed?.lng !== "number") {
      return null;
    }
    return parsed;
  } catch {
    return null; // unreadable or storage unavailable — behave as if unset
  }
}

export function useRecentDestination() {
  const [recent, setRecent] = useState<RecentDestination | null>(load);

  useEffect(() => {
    try {
      if (recent) localStorage.setItem(KEY, JSON.stringify(recent));
      else localStorage.removeItem(KEY);
    } catch {
      /* storage may be unavailable; the feature just goes quiet */
    }
  }, [recent]);

  /** Record a destination the parent has chosen. */
  const remember = useCallback(
    (label: string, coord: Coord, detail?: string) => {
      setRecent((prev) => {
        // Same place chosen again: keep the original label but refresh the
        // clock, so a weekly trip stays on offer.
        if (
          prev &&
          Math.abs(prev.lat - coord.lat) < 1e-6 &&
          Math.abs(prev.lng - coord.lng) < 1e-6
        ) {
          return { ...prev, savedAt: Date.now() };
        }
        return {
          label,
          detail,
          lat: coord.lat,
          lng: coord.lng,
          savedAt: Date.now(),
        };
      });
    },
    [],
  );

  const forget = useCallback(() => setRecent(null), []);

  return {
    recent: isFresh(recent) ? recent : null,
    remember,
    forget,
  };
}
