import { useState } from "react";
import type { CarrierSetup, PramSetup } from "./api";

/**
 * Pram and carrier details, kept on this device only.
 *
 * The brief is explicit that equipment and approximate load stay local first,
 * and there is a plainer reason too: the server never needs to remember them.
 * They are sent with each assessment and discarded. No child's name, birth
 * date or weight history is asked for, so none can be stored.
 */

const KEY = "driftway.walk.v1";

export interface WalkSetup {
  profile: "pram" | "carrier";
  minutes: number;
  /** Show walks that go out and come back the same way. */
  allowOutAndBack: boolean;
  /** Show walks that need driving or travelling to the start. */
  allowTravel: boolean;
  pram: PramSetup;
  carrier: CarrierSetup;
}

const DEFAULTS: WalkSetup = {
  profile: "pram",
  minutes: 30,
  allowOutAndBack: true,
  allowTravel: true,
  pram: { wheels: "standard", width_cm: null, double: false },
  carrier: {
    kind: "soft",
    child_kg: null,
    carrier_kg: null,
    luggage_kg: null,
    luggage_with: "carrier_adult",
  },
};

function load(): WalkSetup {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    const saved = JSON.parse(raw);
    // Merge over defaults so a field added later does not arrive undefined.
    return {
      ...DEFAULTS,
      ...saved,
      pram: { ...DEFAULTS.pram, ...saved?.pram },
      carrier: { ...DEFAULTS.carrier, ...saved?.carrier },
    };
  } catch {
    return DEFAULTS;
  }
}

export function useWalkSetup() {
  const [setup, setSetup] = useState<WalkSetup>(load);

  function update(patch: Partial<WalkSetup>) {
    setSetup((prev) => {
      const next = { ...prev, ...patch };
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        /* private mode: works for this visit, just not remembered */
      }
      return next;
    });
  }

  return { setup, update };
}
