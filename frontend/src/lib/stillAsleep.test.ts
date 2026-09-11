import { describe, expect, it } from "vitest";
import {
  RECENT_ABSOLUTE_MAX_HOURS,
  RECENT_WINDOW_HOURS,
  isRecentEnough,
} from "./stillAsleepConfig";
import { buildStillAsleepTargets } from "../hooks/useStillAsleepTargets";
import type { Place } from "../hooks/usePlaces";
import type { RecentDestination } from "../hooks/useRecentDestination";

/**
 * Still Asleep decides where a hurried parent is sent. Getting it wrong means
 * opening navigation to the wrong place with a sleeping child in the car, so
 * the ordering and recency rules are pinned here rather than trusted.
 */

const NOW = Date.parse("2026-09-11T14:00:00Z");
const HOUR = 60 * 60 * 1000;

const HOME: Place = {
  id: "h1", label: "Home", lat: 51.472, lng: -0.628, isDefault: true,
};
const NURSERY: Place = {
  id: "p2", label: "Nursery", lat: 51.48, lng: -0.61, isDefault: false,
};

function recent(hoursAgo: number): RecentDestination {
  return {
    label: "Windsor Leisure Centre",
    detail: "Stovell Road",
    lat: 51.4857,
    lng: -0.6214,
    savedAt: NOW - hoursAgo * HOUR,
  };
}

describe("recency window", () => {
  it("is about six hours, per Bible v0.4", () => {
    expect(RECENT_WINDOW_HOURS).toBe(6);
    expect(RECENT_ABSOLUTE_MAX_HOURS).toBe(24);
  });

  it("keeps a destination from earlier in the same outing", () => {
    expect(isRecentEnough(NOW - 5 * HOUR, { now: NOW })).toBe(true);
  });

  it("drops one from yesterday", () => {
    expect(isRecentEnough(NOW - 30 * HOUR, { now: NOW })).toBe(false);
  });

  it("drops one just past the window", () => {
    expect(isRecentEnough(NOW - 6.5 * HOUR, { now: NOW })).toBe(false);
  });

  it("extends an explicitly saved place to the 24-hour ceiling, not beyond", () => {
    const opts = { explicitlySaved: true, now: NOW };
    expect(isRecentEnough(NOW - 20 * HOUR, opts)).toBe(true);
    expect(isRecentEnough(NOW - 25 * HOUR, opts)).toBe(false);
  });

  it("treats a future timestamp as stale rather than fresh forever", () => {
    // Clock skew, or a value someone edited in devtools.
    expect(isRecentEnough(NOW + 3 * HOUR, { now: NOW })).toBe(false);
  });
});

describe("target ordering", () => {
  it("puts Home first", () => {
    const targets = buildStillAsleepTargets([NURSERY, HOME], null, NOW);
    expect(targets[0].label).toBe("Home");
    expect(targets[0].kind).toBe("home");
  });

  it("offers a recent destination in addition to saved places, never instead", () => {
    const targets = buildStillAsleepTargets([HOME, NURSERY], recent(2), NOW);
    expect(targets.map((t) => t.kind)).toEqual(["home", "saved", "recent"]);
    // The regression this guards: a one-off search quietly becoming the
    // default target ahead of Home.
    expect(targets[0].label).toBe("Home");
  });

  it("omits a stale recent destination entirely", () => {
    const targets = buildStillAsleepTargets([HOME], recent(30), NOW);
    expect(targets).toHaveLength(1);
    expect(targets[0].kind).toBe("home");
  });

  it("still offers a fresh recent destination when nothing is saved", () => {
    const targets = buildStillAsleepTargets([], recent(1), NOW);
    expect(targets).toHaveLength(1);
    expect(targets[0].kind).toBe("recent");
  });

  it("returns nothing to offer on a cold launch", () => {
    // The screen must still work - it falls back to Choose destination.
    expect(buildStillAsleepTargets([], null, NOW)).toEqual([]);
  });

  it("does not list the same place twice when the recent one is already saved", () => {
    const sameAsHome: RecentDestination = {
      label: "Home again", lat: HOME.lat, lng: HOME.lng, savedAt: NOW - HOUR,
    };
    const targets = buildStillAsleepTargets([HOME], sameAsHome, NOW);
    expect(targets).toHaveLength(1);
    expect(targets[0].kind).toBe("home");
  });

  it("marks a recent target so it can be labelled differently", () => {
    const targets = buildStillAsleepTargets([HOME], recent(1), NOW);
    expect(targets.find((t) => t.kind === "recent")?.label).toBe(
      "Windsor Leisure Centre",
    );
  });

  it("keeps every saved place, not just Home", () => {
    const targets = buildStillAsleepTargets([HOME, NURSERY], null, NOW);
    expect(targets.map((t) => t.label)).toEqual(["Home", "Nursery"]);
  });
});
