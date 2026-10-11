import type { Coord } from "../types";

/**
 * Checkpoints for walks: up to three points the walk must pass, in order.
 *
 * Founder requests: on 10 Oct, place a checkpoint on the map (searching for
 * a long feature such as the Long Walk picked one geocoded midpoint); on
 * 11 Oct, two or three of them. Search and map edit this same list, and
 * nothing here calls a route provider: adding, moving or removing a
 * checkpoint only changes the settings being edited, and walks are made from
 * `applied` when the parent taps "Update walks". Kept as a pure reducer so
 * those rules are tested without a browser.
 *
 * Not kept on the device after the page closes: a checkpoint is a precise
 * place, and remembering it would make the phone a record of where someone
 * walks.
 */

export const MAX_CHECKPOINTS = 3;

export interface Checkpoint {
  coord: Coord;
  label: string;
  source: "search" | "map";
}

export interface CheckpointState {
  /** As edited: what the next "Update walks" will use, in order. */
  pending: Checkpoint[];
  /** What the walks on screen were made with. */
  applied: Checkpoint[];
  /**
   * Map selection mode: which checkpoint is being moved (null: a new one is
   * being added), and the draft pin (null until placed).
   */
  picking: { index: number | null; draft: Coord | null } | null;
}

export type CheckpointAction =
  /** Open the map: move checkpoint `index`, or add a new one. */
  | { type: "open"; index?: number }
  | { type: "place"; coord: Coord }
  | { type: "confirm" }
  | { type: "cancel" }
  /** Remove checkpoint `index`, or every checkpoint. */
  | { type: "remove"; index?: number }
  /** A search result: replaces checkpoint `index`, or is added. */
  | { type: "search"; checkpoint: Checkpoint; index?: number }
  | { type: "apply" }
  | { type: "undo" }
  /** The parent accepts the points the provider moved checkpoints to. */
  | { type: "accept_routed"; coords: (Coord | null)[] };

export const MAP_POINT_LABEL = "Point on map";

export const initialCheckpoint: CheckpointState = {
  pending: [],
  applied: [],
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

export function sameCheckpoints(a: Checkpoint[], b: Checkpoint[]): boolean {
  return (
    a.length === b.length &&
    a.every((p, i) => sameCoord(p.coord, b[i].coord) && p.label === b[i].label)
  );
}

/** Whether the checkpoints being edited differ from the ones in use. */
export function checkpointChanged(s: CheckpointState): boolean {
  return !sameCheckpoints(s.pending, s.applied);
}

/** What a checkpoint is called in messages and walk names: map pins by
 *  their number, searched places by name. */
export function checkpointLabel(p: Checkpoint, index: number): string {
  return p.source === "map" ? `pin ${index + 1}` : p.label;
}

function put(list: Checkpoint[], index: number | null | undefined, item: Checkpoint) {
  if (index == null || index >= list.length) {
    return list.length < MAX_CHECKPOINTS ? [...list, item] : list;
  }
  return list.map((p, i) => (i === index ? item : p));
}

export function checkpointReducer(
  s: CheckpointState,
  a: CheckpointAction,
): CheckpointState {
  switch (a.type) {
    case "open": {
      const index = a.index ?? null;
      if (index === null && s.pending.length >= MAX_CHECKPOINTS) return s;
      // Moving one: start the draft where it already is.
      const draft = index !== null ? s.pending[index]?.coord ?? null : null;
      return { ...s, picking: { index, draft } };
    }
    case "place":
      if (!s.picking || !validCoord(a.coord)) return s;
      return { ...s, picking: { ...s.picking, draft: a.coord } };
    case "confirm":
      if (!s.picking?.draft) return s;
      return {
        ...s,
        pending: put(s.pending, s.picking.index, {
          coord: s.picking.draft,
          label: MAP_POINT_LABEL,
          source: "map",
        }),
        picking: null,
      };
    case "cancel":
      // The checkpoints, whatever they were, stay as they were.
      return { ...s, picking: null };
    case "remove":
      return {
        ...s,
        pending: a.index === undefined ? [] : s.pending.filter((_, i) => i !== a.index),
        picking: null,
      };
    case "search":
      if (!validCoord(a.checkpoint.coord)) return s;
      return { ...s, pending: put(s.pending, a.index, a.checkpoint), picking: null };
    case "apply":
      return { ...s, applied: s.pending };
    case "undo":
      return { ...s, pending: s.applied, picking: null };
    case "accept_routed": {
      if (!s.applied.length) return s;
      // The walks on screen already go to these points, so they become both
      // the edited and the applied checkpoints: accepting makes no request.
      const moved = s.applied.map((p, i) => {
        const c = a.coords[i];
        return c && validCoord(c) ? { ...p, coord: c } : p;
      });
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
