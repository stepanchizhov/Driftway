/**
 * The walking experiment's one endpoint, plus the flag that says it exists.
 *
 * The server is the control: it refuses anyone who is not an admitted beta
 * account. This client just reports what it was told, distinguishing "you are
 * not in the beta" from "something went wrong", because the two need different
 * words on screen.
 */

import { authFetch } from "../auth/authFetch";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export type Verdict = "ok" | "difficult" | "blocked" | "unknown";
export type Basis = "reported" | "mapped" | "modelled" | "unknown";

export interface WalkFinding {
  verdict: Verdict;
  kind: string;
  reason: string;
  basis: Basis;
  source: string;
  at_m: number | null;
  preference: boolean;
}

export interface WalkSection {
  label: string;
  from_m: number;
  to_m: number;
  surface: string;
  surface_basis: Basis;
  verdict: Verdict;
}

export interface WalkSource {
  id: string;
  label: string;
  attribution?: string;
  limitation?: string;
  as_of?: string;
}

export interface Walk {
  id: string;
  name: string;
  area: string;
  summary: string;
  shape: "loop" | "out_and_back";
  sample: boolean;
  start: { lat: number; lng: number; label: string };
  verdict: Verdict;
  distance_m: number;
  ascent_m: number | null;
  minutes: number;
  assumptions: string;
  blocking: WalkFinding[];
  difficult: WalkFinding[];
  unknowns: WalkFinding[];
  notes: WalkFinding[];
  coverage: {
    surface_known_share: number;
    surface_reported_share: number;
    gradient: "modelled" | "unknown";
  };
  sections: WalkSection[];
  sources: WalkSource[];
  built_on: string;
  notes_from_curator: string[];
}

export interface Guidance {
  title: string;
  points: string[];
  source: string | null;
  url: string | null;
  reviewed: string | null;
}

export interface WalksResponse {
  walks: Walk[];
  guidance: Guidance[];
  carried_kg: number | null;
  handoff: string;
}

export interface PramSetup {
  wheels: "compact" | "standard" | "all_terrain";
  width_cm: number | null;
  double: boolean;
}

export interface CarrierSetup {
  kind: "soft" | "framed";
  child_kg: number | null;
  carrier_kg: number | null;
  luggage_kg: number | null;
  luggage_with: "carrier_adult" | "companion";
}

/** Not in the beta, as opposed to broken. */
export class NotAdmitted extends Error {}

export async function walkingEnabled(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (!res.ok) return false;
    return Boolean((await res.json())?.walking);
  } catch {
    return false;
  }
}

export async function assessWalks(body: {
  profile: "pram" | "carrier";
  minutes: number;
  pram?: PramSetup;
  carrier?: CarrierSetup;
}): Promise<WalksResponse> {
  let res: Response;
  try {
    res = await authFetch(`${API_BASE}/api/walks/assess`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Can't reach Driftway. Check your connection.");
  }
  if (res.status === 401 || res.status === 403) {
    let detail = "Walks are part of the closed beta.";
    try {
      const b = await res.json();
      if (typeof b?.detail === "string") detail = b.detail;
    } catch {
      /* keep default */
    }
    throw new NotAdmitted(detail);
  }
  if (!res.ok) throw new Error("Walks are unavailable right now.");
  return res.json();
}
