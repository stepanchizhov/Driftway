import { useCallback, useEffect, useRef, useState } from "react";
import type { Coord } from "../types";
import {
  PlaceError,
  applyPlaceOp,
  homeOf,
  parseStored,
  type Place,
  type PlaceOp,
} from "../lib/places";

export type { Place } from "../lib/places";

/**
 * Saved places on this device: Home and any others the parent keeps
 * (11 Oct 2026; the rules live in lib/places.ts). The rest of the app asks
 * for places through this hook and never touches the store directly.
 *
 * Every change says whether it was kept. A browser that refuses storage
 * (private mode, full, blocked) still lets the parent use the place for this
 * visit, and the screen says so rather than "Saved".
 */

const KEY = "driftway.places.v1";
const OLD_SETTINGS_KEY = "driftway.settings.v1"; // for one-time Home migration

/** "ok": kept on this device. "unreadable": the stored list could not be
 *  read (left as it was until the parent saves). "unavailable": the browser
 *  is not keeping data, so changes last for this visit only. */
export type PlaceStore = "ok" | "unreadable" | "unavailable";

export type PlaceChange =
  | { ok: true; persisted: boolean }
  | { ok: false; message: string };

function uid(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return Math.random().toString(36).slice(2, 12);
  }
}

function read(): { places: Place[]; store: PlaceStore } {
  let raw: string | null = null;
  let old: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
    if (raw == null) old = localStorage.getItem(OLD_SETTINGS_KEY);
  } catch {
    return { places: [], store: "unavailable" };
  }
  const r = parseStored(raw, old, uid);
  return { places: r.places, store: r.ok ? "ok" : "unreadable" };
}

type OpInput = PlaceOp extends infer O ? (O extends { id: string; type: "add" | "saveHome" } ? Omit<O, "id"> : O) : never;

export function usePlaces() {
  const [initial] = useState(read);
  const [places, setPlaces] = useState<Place[]>(initial.places);
  const [store, setStore] = useState<PlaceStore>(initial.store);
  // The list as last changed, so two changes in one event both apply.
  const current = useRef(places);

  // Another tab changed the places: follow it.
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key !== KEY) return;
      const next = read();
      current.current = next.places;
      setPlaces(next.places);
      setStore(next.store);
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const change = useCallback((input: OpInput): PlaceChange => {
    const op = ("id" in input ? input : { ...input, id: uid() }) as PlaceOp;
    let next: Place[];
    try {
      next = applyPlaceOp(current.current, op);
    } catch (e) {
      if (e instanceof PlaceError) return { ok: false, message: e.message };
      throw e;
    }
    let persisted = true;
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      persisted = false;
    }
    current.current = next;
    setPlaces(next);
    setStore(persisted ? "ok" : "unavailable");
    return { ok: true, persisted };
  }, []);

  // "Save as Home" from the parent's location (Plan a drive).
  const saveHome = useCallback((coord: Coord) => change({ type: "saveHome", coord }), [change]);

  const home = homeOf(places);
  // `defaultPlace` is Home, or nothing: never another place standing in.
  return { places, home, defaultPlace: home, saveHome, change, store };
}
