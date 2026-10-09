import { describe, expect, it } from "vitest";
import type { Walk } from "./api";
import { groupWalks } from "./group";

const WINDSOR = { lat: 51.4836, lng: -0.6045 };

function walk(id: string, start: { lat: number; lng: number }, kind: string | null): Walk {
  return {
    id,
    start: { ...start, label: id },
    fit: kind
      ? {
          kind: kind as "turned",
          requested_minutes: 60,
          full_minutes: 60,
          turn_back_at_m: null,
          turn_back_near: null,
          can_shorten: true,
          whole_shape: "loop",
        }
      : null,
  } as unknown as Walk;
}

const longWalk = walk("long-walk", { lat: 51.48, lng: -0.6036 }, "turned");
const castle = walk("castle-hill", { lat: 51.4857, lng: -0.6081 }, "shorter");
const koepenick = walk("berlin", { lat: 52.4466, lng: 13.5636 }, "turned");

describe("groupWalks", () => {
  it("keeps Berlin walks out of a Windsor list", () => {
    const g = groupWalks([longWalk, castle, koepenick], WINDSOR);
    expect(g.fitting.map((w) => w.id)).toEqual(["long-walk"]);
    expect(g.far.map((w) => w.id)).toEqual(["berlin"]);
  });

  it("separates walks that cannot reach the time", () => {
    const g = groupWalks([longWalk, castle], WINDSOR);
    expect(g.other.map((w) => w.id)).toEqual(["castle-hill"]);
  });

  it("hides nothing from someone who has not shared a position", () => {
    const g = groupWalks([longWalk, castle, koepenick], null);
    expect(g.far).toEqual([]);
    expect(g.fitting.length + g.other.length).toBe(3);
  });
});
