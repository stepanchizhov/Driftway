import { useEffect, useState } from "react";
import type { Coord } from "../types";
import type { Units } from "../hooks/useSettings";
import { askForArea, type AreaAnswer } from "./api";
import { kmBetween } from "./group";

/**
 * Walks where Driftway has none yet (founder decision, 11 Oct 2026; the flow
 * is in backend core/walking/areas.py).
 *
 * When no curated walk starts within NEAR_KM, the app asks the server for
 * the parent's area. The server keeps only a grid square, about 10 km
 * across, queues it for the scheduled job that builds checked walks, and
 * lists the trails mapped there right away. Asked once per square per visit.
 */

/** Curated walks starting this close count as "walks here already". */
export const NEAR_KM = 15;

function squareOf(c: Coord): string {
  return `${Math.floor(c.lat * 10)}:${Math.floor(c.lng * 10)}`;
}

export function needsArea(here: Coord | null, curatedStarts: { lat: number; lng: number }[]): boolean {
  return here !== null && !curatedStarts.some((s) => kmBetween(here, s) <= NEAR_KM);
}

export function NearbyTrails({ here, units }: { here: Coord; units: Units }) {
  const [answer, setAnswer] = useState<AreaAnswer | null>(null);
  const [failed, setFailed] = useState(false);
  const square = squareOf(here);

  useEffect(() => {
    let alive = true;
    const key = `driftway.area.${square}`;
    let cached: AreaAnswer | null = null;
    try {
      const raw = sessionStorage.getItem(key);
      cached = raw ? (JSON.parse(raw) as AreaAnswer) : null;
    } catch {
      /* no session storage: ask */
    }
    if (cached) {
      setAnswer(cached);
      return;
    }
    askForArea(here)
      .then((a) => {
        if (!alive) return;
        setAnswer(a);
        try {
          sessionStorage.setItem(key, JSON.stringify(a));
        } catch {
          /* fine */
        }
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
    // Once per square, not on every small move.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [square]);

  if (failed) return null;
  if (!answer) return <p className="walks-hint">Looking for trails mapped near you…</p>;

  const km = (k: number) => (units === "mi" ? `${(k / 1.609344).toFixed(1)} mi` : `${k} km`);
  const trails = answer.trails ?? [];

  return (
    <section className="walks-checkpoint nearby-trails" aria-labelledby="nearby-title">
      <h3 className="nearby-title" id="nearby-title">
        Trails mapped near you
      </h3>
      <p className="walks-hint">
        {answer.status === "empty"
          ? "None of the trails mapped here passed our checks yet. Walks made from your start still work."
          : answer.status === "failed"
            ? "We couldn't build walks for your area this time; we'll try again."
            : "Driftway has no prepared walks here yet, so we've asked for some: they usually appear within a day, judged for your pram or carrier from map data like every other walk. Meanwhile, these are the trails others have mapped."}
      </p>
      {trails.length > 0 ? (
        <ul className="nearby-list">
          {trails.map((t, i) => (
            <li key={`${i}-${t.name}`} className="nearby-row">
              <span className="nearby-name">{t.name}</span>
              <span className="nearby-meta">
                {[t.km != null ? km(t.km) : null, t.circular ? "circular" : null, t.operator]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              {t.website && (
                <a className="nearby-link" href={t.website} target="_blank" rel="noopener noreferrer">
                  Trail&rsquo;s page
                </a>
              )}
            </li>
          ))}
        </ul>
      ) : (
        answer.trails !== null && <p className="walks-hint">No trails are mapped in this area.</p>
      )}
      <p className="walks-hint">
        Not checked yet: these are as mapped on OpenStreetMap, with nothing judged for a pram or
        carrier. To ask, Driftway sent a rough area about 10 km across, never your position.
        {" "}
        {answer.attribution}
      </p>
    </section>
  );
}
