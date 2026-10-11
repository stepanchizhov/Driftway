import type { Coord } from "../types";

/**
 * Saved places: the rules, kept apart from React and storage so they are
 * tested without a browser (founder request, 11 Oct 2026: more than Home).
 *
 * A saved place is somewhere the parent deliberately keeps - Home, Swimming,
 * Workshop. It is not a saved drive (Favourites), a meetup venue or a recent
 * search: those have their own stores and rules, and none is converted into
 * a place. Places never expire.
 *
 * At most one place is Home (`isDefault`). Removing Home leaves no Home: no
 * other place is promoted silently, because Still Asleep and the quick drive
 * home would then send a parent somewhere they never chose as home.
 *
 * Kept on this device only (localStorage, per web address). The server's
 * `saved_places` table has never been used by the app; places are not synced
 * to an account and do not appear on another phone or on Driftway Next.
 */

export interface Place {
  id: string;
  label: string;
  lat: number;
  lng: number;
  /** This place is Home. At most one is. */
  isDefault: boolean;
  /** The address line chosen in search, if any, to recognise the place by. */
  detail?: string;
}

export const LABEL_MAX = 40;
/** Two saves within this distance and with the same name are one place. */
const SAME_PLACE_M = 25;

export function validPlaceCoord(c: Partial<Coord> | null | undefined): c is Coord {
  return (
    !!c &&
    typeof c.lat === "number" &&
    typeof c.lng === "number" &&
    Number.isFinite(c.lat) &&
    Number.isFinite(c.lng) &&
    Math.abs(c.lat) <= 90 &&
    Math.abs(c.lng) <= 180
  );
}

/** A name a person typed, made safe to keep: trimmed, single-spaced, capped.
 *  Shown through React only, which escapes it; never set as markup. */
export function cleanLabel(raw: string): string {
  return raw.replace(/\s+/g, " ").trim().slice(0, LABEL_MAX);
}

function metres(a: Coord, b: Coord): number {
  const r = Math.PI / 180;
  const h =
    Math.sin(((b.lat - a.lat) * r) / 2) ** 2 +
    Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(((b.lng - a.lng) * r) / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(h));
}

export type LoadResult =
  | { ok: true; places: Place[] }
  /** The stored list could not be read. It is left untouched, never
   *  overwritten by an empty list. */
  | { ok: false; places: Place[] };

/**
 * Read the stored list (`raw`, from driftway.places.v1), or lift Home out of
 * the old settings blob (`oldSettingsRaw`) if there is no list yet.
 */
export function parseStored(raw: string | null, oldSettingsRaw: string | null, makeId: () => string): LoadResult {
  if (raw != null) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return { ok: false, places: [] };
    }
    if (!Array.isArray(parsed)) return { ok: false, places: [] };
    const places: Place[] = [];
    for (const p of parsed) {
      if (!p || typeof p !== "object") continue;
      const c = { lat: (p as Place).lat, lng: (p as Place).lng };
      if (!validPlaceCoord(c)) continue;
      places.push({
        id: typeof p.id === "string" && p.id ? p.id : makeId(),
        label: typeof p.label === "string" && cleanLabel(p.label) ? cleanLabel(p.label) : "Saved place",
        lat: c.lat,
        lng: c.lng,
        isDefault: p.isDefault === true,
        ...(typeof p.detail === "string" && p.detail ? { detail: p.detail.slice(0, 120) } : {}),
      });
    }
    return { ok: true, places: withOneHome(places) };
  }
  // One-time migration: lift an existing Home out of the old settings blob.
  try {
    const old = oldSettingsRaw ? JSON.parse(oldSettingsRaw) : null;
    const c = { lat: old?.home?.lat, lng: old?.home?.lng };
    if (validPlaceCoord(c)) {
      return { ok: true, places: [{ id: makeId(), label: "Home", lat: c.lat, lng: c.lng, isDefault: true }] };
    }
  } catch {
    /* nothing to migrate */
  }
  return { ok: true, places: [] };
}

/**
 * At most one Home. Lists saved before more places existed always marked
 * their Home; a list with none marked but a place called "Home" (written by
 * an older version) gets that one, and nothing else is ever promoted.
 */
function withOneHome(places: Place[]): Place[] {
  const first = places.findIndex((p) => p.isDefault);
  if (first >= 0) return places.map((p, i) => ({ ...p, isDefault: i === first }));
  const named = places.findIndex((p) => p.label === "Home");
  return places.map((p, i) => ({ ...p, isDefault: i === named }));
}

export function homeOf(places: Place[]): Place | null {
  return places.find((p) => p.isDefault) ?? null;
}

export type PlaceOp =
  | { type: "add"; label: string; coord: Coord; detail?: string; makeHome?: boolean; id: string }
  | { type: "rename"; id: string; label: string }
  | { type: "move"; id: string; coord: Coord; detail?: string }
  | { type: "remove"; id: string }
  | { type: "setHome"; id: string }
  /** "Save as Home" from the parent's location: moves Home, or adds one. */
  | { type: "saveHome"; coord: Coord; id: string };

export class PlaceError extends Error {}

/** Apply one change. Throws PlaceError, with a message for the parent, when
 *  the change is not valid; the list is then unchanged. */
export function applyPlaceOp(places: Place[], op: PlaceOp): Place[] {
  switch (op.type) {
    case "add": {
      const label = cleanLabel(op.label);
      if (!label) throw new PlaceError("Give the place a name.");
      if (!validPlaceCoord(op.coord)) throw new PlaceError("Choose where the place is.");
      // The same save twice (a double tap, a retry) is one place.
      const same = places.find(
        (p) => p.label.toLowerCase() === label.toLowerCase() && metres(p, op.coord) <= SAME_PLACE_M,
      );
      if (same) return op.makeHome ? applyPlaceOp(places, { type: "setHome", id: same.id }) : places;
      const added: Place = {
        id: op.id,
        label,
        lat: op.coord.lat,
        lng: op.coord.lng,
        isDefault: !!op.makeHome,
        ...(op.detail ? { detail: op.detail.slice(0, 120) } : {}),
      };
      return [...places.map((p) => (op.makeHome ? { ...p, isDefault: false } : p)), added];
    }
    case "rename": {
      const label = cleanLabel(op.label);
      if (!label) throw new PlaceError("Give the place a name.");
      return places.map((p) => (p.id === op.id ? { ...p, label } : p));
    }
    case "move": {
      if (!validPlaceCoord(op.coord)) throw new PlaceError("Choose where the place is.");
      // Same id: a renamed or moved place stays the same place.
      return places.map((p) => {
        if (p.id !== op.id) return p;
        const { detail: _old, ...rest } = p;
        return { ...rest, lat: op.coord.lat, lng: op.coord.lng, ...(op.detail ? { detail: op.detail.slice(0, 120) } : {}) };
      });
    }
    case "remove":
      // Removing Home leaves no Home. Nothing else is promoted.
      return places.filter((p) => p.id !== op.id);
    case "setHome":
      if (!places.some((p) => p.id === op.id)) return places;
      return places.map((p) => ({ ...p, isDefault: p.id === op.id }));
    case "saveHome": {
      if (!validPlaceCoord(op.coord)) throw new PlaceError("Your location isn't known yet.");
      const home = homeOf(places);
      if (home) return applyPlaceOp(places, { type: "move", id: home.id, coord: op.coord });
      return applyPlaceOp(places, { type: "add", id: op.id, label: "Home", coord: op.coord, makeHome: true });
    }
  }
}
