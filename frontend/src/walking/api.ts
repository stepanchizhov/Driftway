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
  geometry: [number, number][];
}

export interface WalkMarker {
  kind: string;
  label?: string;
  lat: number;
  lng: number;
  at_m: number;
  basis: Basis;
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
  shape: "loop" | "out_and_back" | "one_way";
  /** The shape on the ground, measured from the route, not declared. */
  path_shape: "loop" | "lollipop" | "there_and_back" | "one_way";
  /** Share of the walk on ground already walked: 0 (loop) to ~0.5. */
  retrace_share: number;
  /** Share along streets and roads, where known (generated walks). */
  road_share: number | null;
  sample: boolean;
  start: { lat: number; lng: number; label: string };
  verdict: Verdict;
  distance_m: number;
  ascent_m: number | null;
  minutes: number;
  /** How the walk relates to the time asked for. Null if none was asked. */
  fit: {
    kind: "turned" | "about_right" | "shorter" | "longer";
    requested_minutes: number;
    full_minutes: number;
    turn_back_at_m: number | null;
    turn_back_near: string | null;
    can_shorten: boolean;
    whole_shape: "loop" | "out_and_back" | "one_way";
  } | null;
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
  markers: WalkMarker[];
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

/** What happened to a checkpoint: where the walks really go, and whether
 *  they fit the time. Present only on walks made via a checkpoint. */
export interface CheckpointOutcome {
  /** The parent's marker. */
  requested: { lat: number; lng: number };
  /** Where the route provider took the walks - the point they visit. */
  routed: { lat: number; lng: number };
  offset_m: number;
  /** How close the parent asked the walk to come. */
  reach_m: number;
  /** Further than the parent allowed: show both, ask before showing walks. */
  needs_confirmation: boolean;
  /** Every walk through it is longer than the time asked for. */
  over_time: boolean;
  shortest_minutes: number | null;
}

export interface GeneratedWalks {
  walks: Walk[];
  attribution: string;
  checkpoint?: CheckpointOutcome;
}

/** The checkpoint itself is the problem, and the parent can fix it. */
export class CheckpointError extends Error {
  constructor(
    message: string,
    readonly code: "too_close" | "too_far" | "unreachable" | "no_route",
    readonly minimumMinutes: number | null,
  ) {
    super(message);
  }
}

/**
 * Walks made from a chosen start, optionally via a checkpoint. The start and
 * checkpoint go to our server, which sends them to openrouteservice as
 * precise points - with no name, account or label - and keeps neither; the
 * walks are not stored. Errors are reported, never replaced by an invented
 * walk.
 */
export async function generateWalks(body: {
  profile: "pram" | "carrier" | "walker";
  minutes: number;
  allow_out_and_back?: boolean;
  start: { lat: number; lng: number };
  start_label: string;
  character?: "any" | "green" | "quiet";
  via?: { lat: number; lng: number };
  via_label?: string;
  via_reach_m?: number;
  pram?: PramSetup;
  carrier?: CarrierSetup;
}): Promise<GeneratedWalks> {
  let res: Response;
  try {
    res = await authFetch(`${API_BASE}/api/walks/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Can't reach Driftway. Check your connection.");
  }
  if (res.status === 401 || res.status === 403) {
    throw new NotAdmitted("Walks are part of the closed beta.");
  }
  if (!res.ok) {
    let detail = "Couldn't make walks just now.";
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* keep default */
    }
    const d = (body as { detail?: unknown } | null)?.detail;
    if (res.status === 422 && d && typeof d === "object" && "code" in d) {
      const c = d as { code: CheckpointError["code"]; message: string; minimum_minutes: number | null };
      throw new CheckpointError(c.message, c.code, c.minimum_minutes ?? null);
    }
    if (typeof d === "string") detail = d;
    throw new Error(detail);
  }
  return res.json();
}

/** Not in the beta, as opposed to broken. */
export class NotAdmitted extends Error {}

export async function assessWalks(body: {
  profile: "pram" | "carrier" | "walker";
  minutes: number;
  allow_out_and_back?: boolean;
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
