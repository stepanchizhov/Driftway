import { describe, expect, it } from "vitest";
import { PlaceError, applyPlaceOp, cleanLabel, homeOf, parseStored, type Place } from "./places";

// Synthetic points, nobody's address.
const A = { lat: 51.47, lng: -0.62 };
const B = { lat: 51.48, lng: -0.61 };
let n = 0;
const id = () => `id${++n}`;

const HOME: Place = { id: "h", label: "Home", lat: A.lat, lng: A.lng, isDefault: true };

describe("upgrading", () => {
  it("keeps an existing Home as it was", () => {
    const r = parseStored(JSON.stringify([HOME]), null, id);
    expect(r).toEqual({ ok: true, places: [HOME] });
  });

  it("lifts Home out of the oldest settings, once", () => {
    const r = parseStored(null, JSON.stringify({ home: A }), id);
    expect(r.ok && r.places.map((p) => [p.label, p.isDefault])).toEqual([["Home", true]]);
  });

  it("does not take a second place for Home when the list says none", () => {
    const two = [{ ...HOME, isDefault: false, label: "Nursery" }, { ...HOME, id: "x", isDefault: false, label: "Pool" }];
    const r = parseStored(JSON.stringify(two), null, id);
    expect(r.ok && homeOf(r.places)).toBeNull();
  });

  it("treats an unreadable store as unreadable, not as empty", () => {
    expect(parseStored("{nope", null, id).ok).toBe(false);
    expect(parseStored('"text"', null, id).ok).toBe(false);
  });

  it("drops entries that aren't places, and keeps the rest", () => {
    const r = parseStored(JSON.stringify([HOME, { label: "Bad", lat: "x" }, null]), null, id);
    expect(r.ok && r.places).toEqual([HOME]);
  });
});

describe("adding, editing and removing", () => {
  it("adds a second place without touching Home", () => {
    const p = applyPlaceOp([HOME], { type: "add", id: "s", label: "Swimming", coord: B });
    expect(p.map((x) => x.label)).toEqual(["Home", "Swimming"]);
    expect(homeOf(p)?.id).toBe("h");
  });

  it("refuses a place without a name or a real position", () => {
    expect(() => applyPlaceOp([], { type: "add", id: "s", label: "   ", coord: B })).toThrow(PlaceError);
    expect(() => applyPlaceOp([], { type: "add", id: "s", label: "Pool", coord: { lat: Number.NaN, lng: 0 } })).toThrow(
      PlaceError,
    );
  });

  it("saves the same place twice as one", () => {
    const once = applyPlaceOp([HOME], { type: "add", id: "s1", label: "Swimming", coord: B });
    const twice = applyPlaceOp(once, { type: "add", id: "s2", label: "swimming ", coord: { lat: B.lat + 0.0001, lng: B.lng } });
    expect(twice).toHaveLength(2);
  });

  it("renames and moves a place, keeping its identity", () => {
    let p = applyPlaceOp([HOME], { type: "add", id: "s", label: "Swimming", coord: B, detail: "Old Road" });
    p = applyPlaceOp(p, { type: "rename", id: "s", label: "  Pool   lessons " });
    p = applyPlaceOp(p, { type: "move", id: "s", coord: A });
    const s = p.find((x) => x.id === "s")!;
    expect([s.label, s.lat, s.detail]).toEqual(["Pool lessons", A.lat, undefined]);
  });

  it("removing Home leaves no Home, and promotes nothing", () => {
    const p = applyPlaceOp(applyPlaceOp([HOME], { type: "add", id: "s", label: "Swimming", coord: B }), {
      type: "remove",
      id: "h",
    });
    expect(p.map((x) => x.label)).toEqual(["Swimming"]);
    expect(homeOf(p)).toBeNull();
  });

  it("makes another place Home, explicitly", () => {
    const p = applyPlaceOp(applyPlaceOp([HOME], { type: "add", id: "s", label: "Flat", coord: B }), {
      type: "setHome",
      id: "s",
    });
    expect(p.filter((x) => x.isDefault).map((x) => x.id)).toEqual(["s"]);
  });

  it("Save as Home moves the Home there is, or adds one", () => {
    expect(applyPlaceOp([HOME], { type: "saveHome", id: "z", coord: B })).toEqual([{ ...HOME, lat: B.lat, lng: B.lng }]);
    const none = applyPlaceOp([], { type: "saveHome", id: "z", coord: B });
    expect(none.map((x) => [x.label, x.isDefault])).toEqual([["Home", true]]);
  });

  it("caps and tidies names", () => {
    expect(cleanLabel("  a\n b ")).toBe("a b");
    expect(cleanLabel("x".repeat(100))).toHaveLength(40);
  });
});
