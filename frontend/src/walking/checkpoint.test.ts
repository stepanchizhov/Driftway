import { describe, expect, it } from "vitest";
import {
  MAP_POINT_LABEL,
  checkpointChanged,
  checkpointReducer as r,
  initialCheckpoint,
  latestOnly,
  roundUpMinutes,
  validCoord,
  type CheckpointState,
} from "./checkpoint";

// Synthetic points, nobody's address.
const A = { lat: 51.4633, lng: -0.6063 };
const B = { lat: 51.4701, lng: -0.6052 };

function run(...actions: Parameters<typeof r>[1][]): CheckpointState {
  return actions.reduce(r, initialCheckpoint);
}

describe("placing a checkpoint on the map", () => {
  it("places, repositions and confirms one point", () => {
    const s = run({ type: "open" }, { type: "place", coord: A }, { type: "place", coord: B });
    expect(s.picking?.draft).toEqual(B);
    expect(s.pending).toBeNull(); // nothing confirmed yet
    const done = r(s, { type: "confirm" });
    expect(done.pending).toEqual({ coord: B, label: MAP_POINT_LABEL, source: "map" });
    expect(done.picking).toBeNull();
  });

  it("ignores taps outside selection mode", () => {
    const s = run({ type: "place", coord: A });
    expect(s).toEqual(initialCheckpoint);
  });

  it("cancelling restores the previous checkpoint", () => {
    const before = run({ type: "open" }, { type: "place", coord: A }, { type: "confirm" });
    const s = [
      { type: "open" } as const,
      { type: "place", coord: B } as const,
      { type: "cancel" } as const,
    ].reduce(r, before);
    expect(s.pending?.coord).toEqual(A);
    expect(s.picking).toBeNull();
  });

  it("opens with the draft where the checkpoint already is", () => {
    const s = run({ type: "open" }, { type: "place", coord: A }, { type: "confirm" }, { type: "open" });
    expect(s.picking?.draft).toEqual(A);
  });

  it("cannot confirm before a point is placed", () => {
    const s = run({ type: "open" }, { type: "confirm" });
    expect(s.pending).toBeNull();
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

describe("search and map share one checkpoint", () => {
  it("a search result replaces a map point, and the reverse", () => {
    const s1 = run({ type: "open" }, { type: "place", coord: A }, { type: "confirm" },
      { type: "search", checkpoint: { coord: B, label: "The Long Walk", source: "search" } });
    expect(s1.pending?.label).toBe("The Long Walk");
    const s2 = [{ type: "open" } as const, { type: "place", coord: A } as const,
      { type: "confirm" } as const].reduce(r, s1);
    expect(s2.pending).toEqual({ coord: A, label: MAP_POINT_LABEL, source: "map" });
  });

  it("removing clears it whichever way it was set", () => {
    const s = run({ type: "search", checkpoint: { coord: B, label: "X", source: "search" } },
      { type: "remove" });
    expect(s.pending).toBeNull();
  });
});

describe("nothing is made until Update", () => {
  it("confirming or removing marks settings changed but does not apply them", () => {
    const s = run({ type: "open" }, { type: "place", coord: A }, { type: "confirm" });
    expect(s.applied).toBeNull();
    expect(checkpointChanged(s)).toBe(true);
    const applied = r(s, { type: "apply" });
    expect(applied.applied?.coord).toEqual(A);
    expect(checkpointChanged(applied)).toBe(false);
    const removed = r(applied, { type: "remove" });
    expect(removed.applied?.coord).toEqual(A); // still in use until Update
    expect(checkpointChanged(removed)).toBe(true);
  });

  it("undo returns to the checkpoint in use", () => {
    const applied = run({ type: "open" }, { type: "place", coord: A }, { type: "confirm" },
      { type: "apply" });
    const s = [{ type: "remove" } as const, { type: "undo" } as const].reduce(r, applied);
    expect(s.pending?.coord).toEqual(A);
    expect(checkpointChanged(s)).toBe(false);
  });

  it("accepting a moved point changes both without a new request", () => {
    const applied = run({ type: "search", checkpoint: { coord: A, label: "The oak", source: "search" } },
      { type: "apply" });
    const s = r(applied, { type: "accept_routed", coord: B });
    expect(s.pending?.coord).toEqual(B);
    expect(s.applied?.coord).toEqual(B);
    expect(s.pending?.label).toBe("The oak");
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
