import { describe, expect, it } from "vitest";
import {
  MAP_POINT_LABEL,
  MAX_CHECKPOINTS,
  checkpointChanged,
  checkpointLabel,
  checkpointReducer as r,
  initialCheckpoint,
  latestOnly,
  roundUpMinutes,
  validCoord,
  type CheckpointAction,
  type CheckpointState,
} from "./checkpoint";

// Synthetic points, nobody's address.
const A = { lat: 51.4633, lng: -0.6063 };
const B = { lat: 51.4701, lng: -0.6052 };
const C = { lat: 51.4751, lng: -0.6012 };
const D = { lat: 51.4801, lng: -0.6002 };

function run(...actions: CheckpointAction[]): CheckpointState {
  return actions.reduce(r, initialCheckpoint);
}
const pin = (coord: typeof A): CheckpointAction[] => [
  { type: "open" },
  { type: "place", coord },
  { type: "confirm" },
];

describe("placing a checkpoint on the map", () => {
  it("drops, repositions and confirms a pin", () => {
    const s = run({ type: "open" }, { type: "place", coord: A }, { type: "place", coord: B });
    expect(s.picking?.draft).toEqual(B);
    expect(s.pending).toEqual([]); // nothing confirmed yet
    const done = r(s, { type: "confirm" });
    expect(done.pending).toEqual([{ coord: B, label: MAP_POINT_LABEL, source: "map" }]);
    expect(done.picking).toBeNull();
  });

  it("ignores taps outside selection mode", () => {
    expect(run({ type: "place", coord: A })).toEqual(initialCheckpoint);
  });

  it("cancelling leaves the checkpoints as they were", () => {
    const before = run(...pin(A));
    const s = [
      { type: "open", index: 0 } as const,
      { type: "place", coord: B } as const,
      { type: "cancel" } as const,
    ].reduce(r, before);
    expect(s.pending.map((p) => p.coord)).toEqual([A]);
    expect(s.picking).toBeNull();
  });

  it("moving one starts the draft where it is, and replaces only it", () => {
    const two = run(...pin(A), ...pin(B));
    const opened = r(two, { type: "open", index: 0 });
    expect(opened.picking?.draft).toEqual(A);
    const moved = [{ type: "place", coord: C } as const, { type: "confirm" } as const].reduce(r, opened);
    expect(moved.pending.map((p) => p.coord)).toEqual([C, B]);
  });

  it("cannot confirm before a pin is placed", () => {
    const s = run({ type: "open" }, { type: "confirm" });
    expect(s.pending).toEqual([]);
    expect(s.picking).not.toBeNull();
  });

  it("refuses coordinates that are not real places", () => {
    for (const bad of [
      { lat: Number.NaN, lng: 0 },
      { lat: 0, lng: Number.POSITIVE_INFINITY },
      { lat: 91, lng: 0 },
      { lat: 0, lng: -181 },
    ]) {
      expect(validCoord(bad)).toBe(false);
      expect(run({ type: "open" }, { type: "place", coord: bad }).picking?.draft).toBeNull();
    }
    expect(validCoord(A)).toBe(true);
  });
});

describe("several checkpoints (11 Oct)", () => {
  it("keeps up to three, in the order added", () => {
    const s = run(...pin(A), ...pin(B), ...pin(C));
    expect(s.pending.map((p) => p.coord)).toEqual([A, B, C]);
    expect(MAX_CHECKPOINTS).toBe(3);
    // A fourth cannot be added, by map or by search.
    expect(r(s, { type: "open" })).toBe(s);
    const searched = r(s, { type: "search", checkpoint: { coord: D, label: "D", source: "search" } });
    expect(searched.pending).toHaveLength(3);
  });

  it("removes one, or all", () => {
    const s = run(...pin(A), ...pin(B), ...pin(C));
    expect(r(s, { type: "remove", index: 1 }).pending.map((p) => p.coord)).toEqual([A, C]);
    expect(r(s, { type: "remove" }).pending).toEqual([]);
  });

  it("names map pins by number and searched places by name", () => {
    const s = run(...pin(A), { type: "search", checkpoint: { coord: B, label: "The oak", source: "search" } });
    expect(s.pending.map(checkpointLabel)).toEqual(["pin 1", "The oak"]);
  });

  it("accepting moved points changes only the moved ones, without a request", () => {
    const applied = run(...pin(A), ...pin(B), { type: "apply" });
    const s = r(applied, { type: "accept_routed", coords: [null, C] });
    expect(s.applied.map((p) => p.coord)).toEqual([A, C]);
    expect(checkpointChanged(s)).toBe(false);
  });
});

describe("search and map share one list", () => {
  it("a search result is added, or replaces the one given", () => {
    const s1 = run(...pin(A), { type: "search", checkpoint: { coord: B, label: "The Long Walk", source: "search" } });
    expect(s1.pending.map((p) => p.label)).toEqual([MAP_POINT_LABEL, "The Long Walk"]);
    const s2 = r(s1, { type: "search", index: 0, checkpoint: { coord: C, label: "Snow Hill", source: "search" } });
    expect(s2.pending.map((p) => p.label)).toEqual(["Snow Hill", "The Long Walk"]);
  });
});

describe("nothing is made until Update", () => {
  it("adding or removing marks settings changed but does not apply them", () => {
    const s = run(...pin(A));
    expect(s.applied).toEqual([]);
    expect(checkpointChanged(s)).toBe(true);
    const applied = r(s, { type: "apply" });
    expect(applied.applied.map((p) => p.coord)).toEqual([A]);
    expect(checkpointChanged(applied)).toBe(false);
    const removed = r(applied, { type: "remove", index: 0 });
    expect(removed.applied.map((p) => p.coord)).toEqual([A]); // still in use until Update
    expect(checkpointChanged(removed)).toBe(true);
  });

  it("undo returns to the checkpoints in use", () => {
    const applied = run(...pin(A), { type: "apply" });
    const s = [{ type: "remove" } as const, { type: "undo" } as const].reduce(r, applied);
    expect(s.pending.map((p) => p.coord)).toEqual([A]);
    expect(checkpointChanged(s)).toBe(false);
  });
});

describe("stale answers", () => {
  it("only the newest request may write its walks", () => {
    const gate = latestOnly();
    const first = gate.begin();
    const second = gate.begin();
    expect(gate.isCurrent(first)).toBe(false);
    expect(gate.isCurrent(second)).toBe(true);
  });
});

describe("suggested times", () => {
  it("rounds up to the next 5 minutes, within the allowed range", () => {
    expect(roundUpMinutes(31)).toBe(35);
    expect(roundUpMinutes(35)).toBe(35);
    expect(roundUpMinutes(4)).toBe(10);
    expect(roundUpMinutes(500)).toBe(240);
  });
});
