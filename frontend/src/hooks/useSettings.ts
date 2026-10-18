import { useCallback, useEffect, useState } from "react";
import type { Coord, RoadProfile, StopPrefs } from "../types";
import { defaultUnits } from "../lib/defaultUnits";

// Remembers the parent's last choices and saved Home between visits, using
// localStorage. No account, no server. (This is a real deployed PWA running
// on the user's own device, so localStorage is the right tool here.)

export type Units = "km" | "mi";

export interface Settings {
  /** Navigation app to prefer when it can carry the route. */
  preferredNavigation: string;
  home: Coord | null;          // legacy; places now live in usePlaces
  lastDuration: number;
  lastProfile: RoadProfile;
  lastTolerance: number;
  units: Units;
  /** True once the parent picks units in Settings. Until then units follow
   *  the device: miles in the UK (founder, 12 Oct 2026), km elsewhere. */
  unitsChosen?: boolean;
  quickDriveProfile: RoadProfile;  // road style for the one-tap quick drive
  /** What wakes the little one: weighs each kind of stop on drives. */
  stopPrefs: StopPrefs;
  /** Show every setting, or only the ones most parents need (founder,
   *  14 Oct 2026: "they are getting more and more of them"). */
  advanced: boolean;
  /** A maintainer's drives are recorded for analysis (founder, 17 Oct 2026).
   *  Offered only to accounts the server lists as maintainers; the server
   *  ignores it for anyone else. */
  recordDrives: boolean;
  /** The last "Arrive by" time, "HH:MM": lessons and the like recur. */
  lastArrival: string;
}

export const DEFAULT_STOPS: StopPrefs = {
  bumps: "sometimes",
  lights: "sometimes",
  turns: "sometimes",
  works: "sometimes",
};

const DEFAULTS: Settings = {
  preferredNavigation: "google_maps",
  home: null,
  lastDuration: 30,
  lastProfile: "mixed",
  lastTolerance: 10,
  units: "km",
  // Default quick drives to quieter roads — smoothest for a sleeping baby.
  // (True speed-bump/traffic-light avoidance needs the smoothness data layer,
  // which is a later version; "quiet" favours minor roads in the meantime.)
  quickDriveProfile: "quiet",
  stopPrefs: DEFAULT_STOPS,
  advanced: false,
  recordDrives: false,
  lastArrival: "",
};

const KEY = "driftway.settings.v1";

function load(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    const saved = raw ? { ...DEFAULTS, ...JSON.parse(raw) } : { ...DEFAULTS };
    saved.stopPrefs = { ...DEFAULT_STOPS, ...(saved.stopPrefs ?? {}) };
    // Units the parent never chose were only ever the default (every visit
    // saved it): follow the device instead.
    if (!saved.unitsChosen) saved.units = defaultUnits();
    return saved;
  } catch {
    return { ...DEFAULTS, units: defaultUnits() };
  }
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(load);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(settings));
    } catch {
      /* storage may be unavailable in private mode; ignore */
    }
  }, [settings]);

  const update = useCallback((patch: Partial<Settings>) => {
    setSettings((s) => ({ ...s, ...patch, ...(patch.units ? { unitsChosen: true } : {}) }));
  }, []);

  return { settings, update };
}
