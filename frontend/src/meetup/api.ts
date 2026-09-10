import type { Coord, Place } from "../types";

// Same base as the main API client: dev proxies /api, production uses
// VITE_API_BASE.
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

// ---------------------------------------------------------------- contracts

export type VoteValue = "works" | "maybe" | "too_far" | "not_this_venue";

export interface ParticipantPublic {
  id: string;
  display_name: string | null;
  locality_label: string | null;
  display_coord: Coord | null;
  /** "exact" only for yourself, or for someone who chose to share. */
  origin_precision: "exact" | "approximate";
  preferred_minutes: number | null;
  max_minutes: number | null;
  is_you: boolean;
}

export interface ParticipantTravel {
  participant_id: string;
  direct_minutes: number;
  preferred_delta_minutes: number | null;
  exceeds_maximum: boolean;
}

export interface VenueCandidate {
  id: string;
  name: string;
  added_by_participant_id: string | null;
  added_by_you: boolean;
  coord: Coord;
  address_label: string | null;
  canonical_categories: string[];
  provider_rating: number | null;
  opening_status: "open" | "closed" | "unknown";
  suitability: "allowed" | "conditional";
  participant_travel: ParticipantTravel[];
  fairness_spread_minutes: number;
  total_travel_minutes: number;
  max_travel_minutes: number;
  group_fit_label: string;
  score: number;
  votes: Record<string, number>;
  your_vote: VoteValue | null;
}

export interface MeetupView {
  id: string;
  status: string;
  mode: "filtered" | "explore";
  scheduled_at: string | null;
  participants: ParticipantPublic[];
  candidates: VenueCandidate[];
  selected_venue_id: string | null;
  results_url_slug: string | null;
  notice: string | null;
  /** No venue satisfies everyone's stated maximum. */
  no_fit: boolean;
}

export interface MeetupCreated {
  meetup_id: string;
  your_join_token: string;
  participant_invite_token: string;
  results_slug: string;
}

export interface Prefs {
  preferred_minutes?: number | null;
  tolerance_minutes?: number | null;
  max_minutes?: number | null;
}

// ------------------------------------------------------------------ client

export class MeetupError extends Error {}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new MeetupError("Can't reach the server. Check your connection.");
  }
  if (res.status === 503) {
    // The backend distinguishes "storage is down" from "the app is broken",
    // and so should the message.
    throw new MeetupError(
      "Meetups are temporarily unavailable. Route planning still works.",
    );
  }
  if (!res.ok) {
    let detail = `Something went wrong (${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep the default */
    }
    throw new MeetupError(detail);
  }
  return res.json() as Promise<T>;
}

export function createMeetup(input: {
  scheduled_at?: string | null;
  start: Coord;
  hide_exact_origin: boolean;
  display_name?: string;
  prefs: Prefs;
}): Promise<MeetupCreated> {
  return call<MeetupCreated>("/api/meetups", {
    method: "POST",
    body: JSON.stringify({
      scheduled_at: input.scheduled_at ?? null,
      mode: "explore",
      categories: [],
      organiser: {
        start: input.start,
        hide_exact_origin: input.hide_exact_origin,
        display_name: input.display_name,
        ...input.prefs,
      },
    }),
  });
}

export function joinMeetup(
  meetupId: string,
  joinToken: string,
  input: {
    start: Coord;
    hide_exact_origin: boolean;
    display_name?: string;
    prefs: Prefs;
  },
): Promise<MeetupView> {
  return call<MeetupView>(
    `/api/meetups/${meetupId}/participants/${encodeURIComponent(joinToken)}`,
    {
      method: "POST",
      body: JSON.stringify({
        start: input.start,
        hide_exact_origin: input.hide_exact_origin,
        display_name: input.display_name,
        ...input.prefs,
      }),
    },
  );
}

export function readMeetup(meetupId: string, joinToken: string): Promise<MeetupView> {
  return call<MeetupView>(
    `/api/meetups/${meetupId}/${encodeURIComponent(joinToken)}`,
  );
}

export function readResults(slug: string): Promise<MeetupView> {
  return call<MeetupView>(`/api/meetups/results/${encodeURIComponent(slug)}`);
}

export function addVenue(
  meetupId: string,
  joinToken: string,
  place: Place,
): Promise<MeetupView> {
  return call<MeetupView>(
    `/api/meetups/${meetupId}/venues/${encodeURIComponent(joinToken)}`,
    {
      method: "POST",
      body: JSON.stringify({
        name: place.label,
        coord: place.coord,
        address_label: place.detail || null,
        categories: [],
      }),
    },
  );
}

export function removeVenue(
  meetupId: string,
  joinToken: string,
  candidateId: string,
): Promise<MeetupView> {
  return call<MeetupView>(
    `/api/meetups/${meetupId}/venues/${encodeURIComponent(joinToken)}/${candidateId}`,
    { method: "DELETE" },
  );
}

export function generateCandidates(
  meetupId: string,
  joinToken: string,
): Promise<MeetupView> {
  return call<MeetupView>(
    `/api/meetups/${meetupId}/candidates/${encodeURIComponent(joinToken)}`,
    { method: "POST" },
  );
}

export function castVote(
  meetupId: string,
  joinToken: string,
  candidateId: string,
  value: VoteValue,
): Promise<MeetupView> {
  const q = new URLSearchParams({ join_token: joinToken });
  return call<MeetupView>(
    `/api/meetups/${meetupId}/votes/${candidateId}?${q}`,
    { method: "PUT", body: JSON.stringify({ value }) },
  );
}

export function selectVenue(
  meetupId: string,
  joinToken: string,
  candidateId: string,
): Promise<MeetupView> {
  const q = new URLSearchParams({ candidate_id: candidateId });
  return call<MeetupView>(
    `/api/meetups/${meetupId}/selection/${encodeURIComponent(joinToken)}?${q}`,
    { method: "POST" },
  );
}

export function clearSelection(
  meetupId: string,
  joinToken: string,
): Promise<MeetupView> {
  return call<MeetupView>(
    `/api/meetups/${meetupId}/selection/${encodeURIComponent(joinToken)}`,
    { method: "DELETE" },
  );
}

/** Whether this deployment has Meet Halfway switched on. */
export async function meetHalfwayEnabled(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (!res.ok) return false;
    return Boolean((await res.json())?.meet_halfway);
  } catch {
    return false;
  }
}
