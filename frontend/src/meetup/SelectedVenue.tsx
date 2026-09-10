import { useState } from "react";
import type { Coord } from "../types";
import { generateRoutes } from "../api";
import type { MeetupView, VenueCandidate } from "./api";

/**
 * The agreed place, and the two ways to drive to it.
 *
 * "Navigate" is the ordinary journey. "Make my drive longer" is the existing
 * Delayed Arrival flow with this venue as the destination — the same
 * total-duration semantics, the same direct-route floor, no duplicated detour
 * logic. It is one parent's private choice about their own journey: padding
 * your drive so the baby sleeps has nothing to do with the group's fairness
 * numbers, which is why those are never recalculated from a padded route.
 */

const LONGER_OPTIONS = [30, 45, 60, 90];

interface Props {
  view: MeetupView;
  venue: VenueCandidate;
  /** This participant's own exact origin, which only they ever see. */
  yourOrigin: Coord | null;
  canChange: boolean;
  onChange: () => void;
}

export function SelectedVenue({ view, venue, yourOrigin, canChange, onChange }: Props) {
  const [busy, setBusy] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const names = new Map(
    view.participants.map((p) => [p.id, p.is_you ? "You" : p.display_name || "Them"]),
  );

  const directUrl =
    `https://www.google.com/maps/dir/?api=1&destination=` +
    `${venue.coord.lat.toFixed(6)},${venue.coord.lng.toFixed(6)}&travelmode=driving`;

  async function driveLonger(minutes: number) {
    if (!yourOrigin) return;
    setBusy(minutes);
    setNote(null);
    setError(null);
    try {
      const data = await generateRoutes({
        start: yourOrigin,
        finish: venue.coord,
        target_minutes: minutes,
        tolerance_minutes: 10,
        road_profile: "mixed",
        direction: "surprise",
        mode: "destination",
      });
      const best = data.routes[0];
      if (!best) {
        setError(data.notice ?? "Couldn't build a longer drive right now.");
        return;
      }
      if (!best.maps_url) {
        setError("Live routing is unavailable, so there's no drive to open.");
        return;
      }
      if (best.is_direct && data.direct_minutes != null) {
        // The floor: you cannot arrive later by driving the quickest route.
        setNote(
          `${venue.name} is only about ${Math.round(data.direct_minutes)} min away, ` +
            `so this is the direct route.`,
        );
      }
      window.open(best.maps_url, "_blank", "noopener");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mh-card mh-decided">
      <div className="mh-decided-head">
        <span className="mh-decided-tag">Agreed</span>
        {canChange && (
          <button className="btn-quiet" onClick={onChange}>
            Change
          </button>
        )}
      </div>

      <h2 className="mh-decided-name">{venue.name}</h2>
      {venue.address_label && <p className="mh-hint">{venue.address_label}</p>}

      {venue.participant_travel.length > 0 && (
        <ul className="mhc-times">
          {venue.participant_travel.map((t) => (
            <li key={t.participant_id} className="mhc-time">
              <span className="mhc-who">{names.get(t.participant_id) ?? "Someone"}</span>
              <span className="mhc-min">{Math.round(t.direct_minutes)} min</span>
            </li>
          ))}
        </ul>
      )}

      <a className="btn-generate mh-nav-btn" href={directUrl} target="_blank" rel="noopener noreferrer">
        Navigate there
      </a>

      {yourOrigin && (
        <div className="mh-longer">
          <span className="mh-longer-title">Baby asleep? Take longer</span>
          <span className="mh-longer-hint">
            Your journey only — the times above don't change.
          </span>
          <div className="mh-longer-row">
            {LONGER_OPTIONS.map((m) => (
              <button
                key={m}
                className="quick-btn"
                disabled={busy !== null}
                onClick={() => void driveLonger(m)}
              >
                {busy === m ? "…" : `${m} min`}
              </button>
            ))}
          </div>
          <span className="mh-longer-hint">
            Total journey time, not extra. Times are estimates.
          </span>
          {note && <p className="mh-hint">{note}</p>}
          {error && <p className="mh-error">{error}</p>}
        </div>
      )}
    </section>
  );
}
