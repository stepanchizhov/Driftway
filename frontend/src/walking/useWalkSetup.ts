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
  profile: "pram" | "carrier" | "walker";
  minutes: number;
  /**
   * Most of a walk that may go over ground already walked: 1 = don't mind,
   * 0.15 = a shared lead-in is fine, 0.05 = avoid. Founder feedback, 9 Oct:
   * a yes/no was too blunt - a shared first and last stretch is fine.
   */
  maxRetrace: number;
  /** For walks made from your start: what openrouteservice should favour. */
  character: "any" | "green" | "quiet";
  /** Show walks that need driving or travelling to the start. */
  allowTravel: boolean;
  /**
   * How close a walk must come to a checkpoint, in metres: 25 means "to it".
   * Founder decision, 10 Oct: a walk along the Long Walk "via" the King
   * George III statue need not climb to it; passing 200 m away is the walk.
   */
  checkpointReach: number;
  pram: PramSetup;
  carrier: CarrierSetup;
}

const DEFAULTS: WalkSetup = {
  profile: "pram",
  minutes: 30,
  maxRetrace: 1,
  character: "any",
  allowTravel: true,
  checkpointReach: 25,
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
    // The first version stored a yes/no; "no" meant "a little at most".
    if (saved && saved.maxRetrace === undefined && saved.allowOutAndBack === false) {
      saved.maxRetrace = 0.15;
    }
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
