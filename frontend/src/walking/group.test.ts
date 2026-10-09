import { describe, expect, it } from "vitest";
import type { Walk } from "./api";
import { groupWalks } from "./group";

const HOME = { lat: 51.4697, lng: -0.6217 };   // a Windsor car park
const ALL = { maxRetrace: 1, allowTravel: true };

function walk(
  id: string,
  start: { lat: number; lng: number },
  kind: string,
  shape: Walk["path_shape"] = "loop",
): Walk {
  return {
    id,
    path_shape: shape,
    retrace_share: shape === "there_and_back" ? 0.5 : shape === "lollipop" ? 0.12 : 0,
    start: { ...start, label: id },
    fit: {
      kind: kind as "turned",
      requested_minutes: 60,
      full_minutes: 60,
      turn_back_at_m: null,
      turn_back_near: null,
      can_shorten: true,
      whole_shape: "loop",
    },
  } as unknown as Walk;
}

const circuit = walk("snow-hill", { lat: 51.4699, lng: -0.6219 }, "about_right");
const longWalk = walk("long-walk", { lat: 51.4802, lng: -0.6036 }, "turned", "there_and_back");
const castle = walk("castle-hill", { lat: 51.4857, lng: -0.6081 }, "shorter", "there_and_back");
const berlin = walk("berlin", { lat: 52.4466, lng: 13.5636 }, "turned", "there_and_back");

describe("groupWalks", () => {
  it("lets a shared lead-in through under 'a little', but not under 'avoid'", () => {
    const leadIn = walk("lead-in", { lat: 51.4699, lng: -0.6219 }, "about_right", "lollipop");
    expect(groupWalks([leadIn], HOME, { ...ALL, maxRetrace: 0.15 }).doorstep.length).toBe(1);
    expect(groupWalks([leadIn], HOME, { ...ALL, maxRetrace: 0.05 }).hidden.outAndBack).toBe(1);
  });

  it("separates walks from your doorstep from ones that need travel", () => {
    const g = groupWalks([circuit, longWalk], HOME, ALL);
    expect(g.doorstep.map((w) => w.id)).toEqual(["snow-hill"]);
    expect(g.travel.map((t) => t.walk.id)).toEqual(["long-walk"]);
    expect(g.travel[0].km).toBeGreaterThan(1);
  });

  it("does not show walks more than about an hour's drive away at all", () => {
    const g = groupWalks([circuit, berlin], HOME, ALL);
    const shown = [...g.doorstep, ...g.other, ...g.travel.map((t) => t.walk)];
    expect(shown.map((w) => w.id)).toEqual(["snow-hill"]);
  });

  it("hides there-and-back walks when asked, and says how many", () => {
    const g = groupWalks([circuit, longWalk, castle], HOME, { ...ALL, maxRetrace: 0.15 });
    expect(g.doorstep.map((w) => w.id)).toEqual(["snow-hill"]);
    expect(g.hidden.outAndBack).toBe(2);
  });

  it("hides walks that need travel when asked, and says how many", () => {
    const g = groupWalks([circuit, longWalk], HOME, { ...ALL, allowTravel: false });
    expect(g.travel).toEqual([]);
    expect(g.hidden.travel).toBe(1);
  });

  it("keeps walks that cannot reach the time apart", () => {
    const g = groupWalks([castle], HOME, ALL);
    expect(g.other.map((w) => w.id)).toEqual(["castle-hill"]);
  });

  it("without a position, calls nothing doorstep-or-travel and hides nothing far", () => {
    const g = groupWalks([circuit, berlin], null, ALL);
    expect(g.located).toBe(false);
    expect(g.doorstep.length).toBe(2);
    expect(g.travel).toEqual([]);
  });
});
