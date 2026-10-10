import type { Coord } from "../types";

/**
 * One optional checkpoint for walks: a point the walk must visit.
 *
 * Founder request, 10 Oct: searching for a long feature such as the Long Walk
 * picked one geocoded midpoint, not the stretch the parent meant. Now the
 * checkpoint can also be placed on the map. Search and map edit this same
 * state, and nothing here calls a route provider: confirming or removing a
 * checkpoint only changes the settings being edited, and walks are made from
 * `applied` when the parent taps "Update walks". Kept as a pure reducer so
 * those rules are tested without a browser.
 *
 * Not kept on the device after the page closes: a checkpoint is a precise
 * place, and remembering it would make the phone a record of where someone
 * walks.
 */

export interface Checkpoint {
  coord: Coord;
  label: string;
  source: "search" | "map";
}

export interface CheckpointState {
  /** As edited: what the next "Update walks" will use. */
  pending: Checkpoint | null;
  /** What the walks on screen were made with. */
  applied: Checkpoint | null;
  /** Map selection mode, with its draft marker (null until placed). */
  picking: { draft: Coord | null } | null;
}

export type CheckpointAction =
  | { type: "open" }
  | { type: "place"; coord: Coord }
  | { type: "confirm" }
  | { type: "cancel" }
  | { type: "remove" }
  | { type: "search"; checkpoint: Checkpoint | null }
  | { type: "apply" }
  | { type: "undo" }
  /** The parent accepts the point the provider moved the checkpoint to. */
  | { type: "accept_routed"; coord: Coord };

export const MAP_POINT_LABEL = "Point on map";

export const initialCheckpoint: CheckpointState = {
  pending: null,
  applied: null,
  picking: null,
};

/** Finite and on the globe. Anything else is never sent anywhere. */
export function validCoord(c: Coord | null | undefined): c is Coord {
  return (
    !!c &&
    Number.isFinite(c.lat) &&
    Number.isFinite(c.lng) &&
    Math.abs(c.lat) <= 90 &&
    Math.abs(c.lng) <= 180
  );
}

/** Same place to about 10 cm - for "is this the point already in use". */
export function sameCoord(a: Coord | null | undefined, b: Coord | null | undefined): boolean {
  if (!a || !b) return !a && !b;
  return Math.abs(a.lat - b.lat) < 1e-6 && Math.abs(a.lng - b.lng) < 1e-6;
}

export function sameCheckpoint(a: Checkpoint | null, b: Checkpoint | null): boolean {
  if (!a || !b) return !a && !b;
  return sameCoord(a.coord, b.coord) && a.label === b.label;
}

/** Whether the checkpoint being edited differs from the one in use. */
export function checkpointChanged(s: CheckpointState): boolean {
  return !sameCheckpoint(s.pending, s.applied);
}

export function checkpointReducer(
  s: CheckpointState,
  a: CheckpointAction,
): CheckpointState {
  switch (a.type) {
    case "open":
      // Start the draft where the checkpoint already is, if there is one.
      return { ...s, picking: { draft: s.pending?.coord ?? null } };
    case "place":
      if (!s.picking || !validCoord(a.coord)) return s;
      return { ...s, picking: { draft: a.coord } };
    case "confirm":
      if (!s.picking?.draft) return s;
      return {
        ...s,
        pending: { coord: s.picking.draft, label: MAP_POINT_LABEL, source: "map" },
        picking: null,
      };
    case "cancel":
      // The confirmed checkpoint, whatever it was, stays as it was.
      return { ...s, picking: null };
    case "remove":
      return { ...s, pending: null, picking: null };
    case "search":
      if (a.checkpoint && !validCoord(a.checkpoint.coord)) return s;
      return { ...s, pending: a.checkpoint, picking: null };
    case "apply":
      return { ...s, applied: s.pending };
    case "undo":
      return { ...s, pending: s.applied, picking: null };
    case "accept_routed": {
      if (!s.applied || !validCoord(a.coord)) return s;
      // The walks on screen already go to this point, so it becomes both the
      // edited and the applied checkpoint: accepting it makes no new request.
      const moved: Checkpoint = { ...s.applied, coord: a.coord };
      return { ...s, pending: moved, applied: moved };
    }
  }
}

/**
 * Lets only the newest request's answer through. A slow answer for settings
 * the parent has already changed must never replace walks for newer ones.
 */
export function latestOnly() {
  let n = 0;
  return {
    begin: () => ++n,
    isCurrent: (token: number) => token === n,
  };
}

/** Minutes rounded up to a choice a parent would pick: the next 5. */
export function roundUpMinutes(min: number): number {
  return Math.min(240, Math.max(10, Math.ceil(min / 5) * 5));
}
