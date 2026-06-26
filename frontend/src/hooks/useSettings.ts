import { useCallback, useEffect, useState } from "react";
import type { Coord, RoadProfile } from "../types";

// Remembers the parent's last choices and saved Home between visits, using
// localStorage. No account, no server. (This is a real deployed PWA running
// on the user's own device, so localStorage is the right tool here.)

export type Units = "km" | "mi";

export interface Settings {
  home: Coord | null;          // legacy; places now live in usePlaces
  lastDuration: number;
  lastProfile: RoadProfile;
  lastTolerance: number;
  units: Units;
  quickDriveProfile: RoadProfile;  // road style for the one-tap quick drive
}

const DEFAULTS: Settings = {
  home: null,
  lastDuration: 30,
  lastProfile: "mixed",
  lastTolerance: 10,
  units: "km",
  // Default quick drives to quieter roads — smoothest for a sleeping baby.
  // (True speed-bump/traffic-light avoidance needs the smoothness data layer,
  // which is a later version; "quiet" favours minor roads in the meantime.)
  quickDriveProfile: "quiet",
};

const KEY = "driftway.settings.v1";

function load(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return DEFAULTS;
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
    setSettings((s) => ({ ...s, ...patch }));
  }, []);

  return { settings, update };
}
