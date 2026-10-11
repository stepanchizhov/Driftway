import { useState } from "react";
import type { Coord } from "../types";
import type { Walk } from "./api";
import { validCoord } from "./checkpoint";

/**
 * Routes of your own (founder request, 11 Oct 2026): the walks Driftway makes
 * are not always the ones a parent actually walks. A route is kept as the
 * points it passes, in order - drawn on the map, read from a GPX file, or
 * taken from a walk Driftway made - and is followed along mapped ways and
 * judged like any other walk each time it is shown.
 *
 * Kept on this device only, because it is a precise record of where someone
 * walks, usually from their door. The parent saves each one deliberately and
 * can delete it. Only its points (at most MAX_POINTS) go to the server when
 * it is shown, and from there to openrouteservice; neither keeps them.
 */

export interface MyWalk {
  id: string;
  name: string;
  points: Coord[];
  source: "made" | "drawn" | "gpx";
  savedAt: string;
}

/** As many points as the server takes (generate.MAX_TRACE_POINTS). */
export const MAX_POINTS = 40;
/** A route ending this close to its start is a loop (TRACE_LOOP_M). */
export const LOOP_M = 150;
/** Points closer than this to the one before add nothing. */
const SAME_M = 5;

const KEY = "driftway.mywalks.v1";

export function metres(a: Coord, b: Coord): number {
  const r = Math.PI / 180;
  const h =
    Math.sin(((b.lat - a.lat) * r) / 2) ** 2 +
    Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(((b.lng - a.lng) * r) / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(h));
}

export function lengthOf(line: Coord[]): number {
  let m = 0;
  for (let i = 1; i < line.length; i++) m += metres(line[i - 1], line[i]);
  return m;
}

export function isLoop(points: Coord[]): boolean {
  return points.length > 2 && metres(points[0], points[points.length - 1]) <= LOOP_M;
}

/** How far the route's end is from its start, in metres. */
export function gapToStart(points: Coord[]): number {
  return points.length > 1 ? metres(points[0], points[points.length - 1]) : 0;
}

/**
 * The route closed back to where it started, so it is walked as a loop
 * rather than there and back. Founder test, 11 Oct 2026: his recorded Long
 * Walk circuit ended about a kilometre short of its start, so it was turned
 * into a there-and-back walk. Thinned again if the extra point goes over.
 */
export function closeLoop(points: Coord[]): Coord[] {
  if (points.length < 2 || isLoop(points)) return points;
  const closed = [...points, points[0]];
  return closed.length <= MAX_POINTS ? closed : [...samplePoints(points, MAX_POINTS - 1), points[0]];
}

/**
 * At most `max` points, evenly spaced along the line by distance, always
 * keeping the first and the last. Invalid and repeated points are dropped.
 */
export function samplePoints(line: Coord[], max = MAX_POINTS): Coord[] {
  const clean: Coord[] = [];
  for (const p of line) {
    if (!validCoord(p)) continue;
    if (clean.length && metres(clean[clean.length - 1], p) < SAME_M) continue;
    clean.push({ lat: p.lat, lng: p.lng });
  }
  if (clean.length <= max) return clean;
  const along = [0];
  for (let i = 1; i < clean.length; i++) along.push(along[i - 1] + metres(clean[i - 1], clean[i]));
  const total = along[along.length - 1];
  const out: Coord[] = [clean[0]];
  let j = 1;
  for (let k = 1; k < max - 1; k++) {
    const want = (total * k) / (max - 1);
    while (j < clean.length - 1 && along[j] < want) j++;
    if (clean[j] !== out[out.length - 1]) out.push(clean[j]);
  }
  out.push(clean[clean.length - 1]);
  return out;
}

/**
 * The track in a GPX file: its track points, else its route points, in
 * order, and its name if it has one. Read as text, not run: a GPX file is
 * XML from anywhere, so nothing in it is evaluated or shown as markup.
 */
export function parseGpx(text: string): { name: string | null; points: Coord[] } {
  const read = (tag: string): Coord[] => {
    const out: Coord[] = [];
    const re = new RegExp(`<${tag}\\b([^>]*)>`, "gi");
    for (const m of text.matchAll(re)) {
      const lat = /\blat\s*=\s*["']([^"']+)["']/i.exec(m[1]);
      const lon = /\blon\s*=\s*["']([^"']+)["']/i.exec(m[1]);
      const p = { lat: Number(lat?.[1]), lng: Number(lon?.[1]) };
      if (lat && lon && validCoord(p)) out.push(p);
    }
    return out;
  };
  const track = read("trkpt");
  const points = track.length ? track : read("rtept");
  // The track's own name first, then the route's, then the file's.
  let name: string | null = null;
  for (const tag of ["trk", "rte", "metadata"]) {
    const m = new RegExp(
      String.raw`<${tag}\b[^>]*>[\s\S]*?<name>\s*(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?\s*</name>`,
      "i",
    ).exec(text);
    const found = m?.[1].replace(/<[^>]*>/g, "").trim().slice(0, 80);
    if (found) {
      name = found;
      break;
    }
  }
  return { name, points };
}

/**
 * The line a walk Driftway made follows, for saving it. A there-and-back walk
 * is saved as its way out: it is walked back the same way anyway.
 */
export function lineOfWalk(walk: Walk): Coord[] {
  const sections =
    walk.shape === "out_and_back"
      ? walk.sections.filter((s) => s.to_m <= walk.distance_m / 2 + 1)
      : walk.sections;
  return sections.flatMap((s) => s.geometry.map(([lat, lng]) => ({ lat, lng })));
}

function load(): MyWalk[] {
  try {
    const raw = localStorage.getItem(KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list)
      ? list.filter(
          (w): w is MyWalk =>
            w && typeof w.name === "string" && Array.isArray(w.points) && w.points.length >= 2,
        )
      : [];
  } catch {
    return [];
  }
}

function store(list: MyWalk[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* private mode: kept for this visit only */
  }
}

export function useMyWalks() {
  const [walks, setWalks] = useState<MyWalk[]>(load);

  function add(name: string, points: Coord[], source: MyWalk["source"]): MyWalk {
    const walk: MyWalk = {
      id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
      name: name.trim().slice(0, 80) || "My walk",
      points: samplePoints(points),
      source,
      savedAt: new Date().toISOString(),
    };
    setWalks((prev) => {
      const next = [walk, ...prev];
      store(next);
      return next;
    });
    return walk;
  }

  function remove(id: string) {
    setWalks((prev) => {
      const next = prev.filter((w) => w.id !== id);
      store(next);
      return next;
    });
  }

  /** Same route, new points (e.g. closed into a loop); the id stays. */
  function replacePoints(id: string, points: Coord[]) {
    setWalks((prev) => {
      const next = prev.map((w) => (w.id === id ? { ...w, points: samplePoints(points) } : w));
      store(next);
      return next;
    });
  }

  return { walks, add, remove, replacePoints };
}
