import { useState } from "react";
import type { Coord, RoadProfile } from "../types";
import { generateRoutes } from "../api";

/** Somewhere the parent can be sent in one tap, with no typing. */
export interface QuickTarget {
  id: string;
  label: string;
  coord: Coord;
  /** "home" is the saved place; "recent" is the last destination they chose. */
  kind: "home" | "recent";
}

interface Props {
  current: Coord | null; // live location (start)
  targets: QuickTarget[]; // most relevant first
  profile: RoadProfile; // last-used profile, or a sensible default
}

const QUICK_DURATIONS = [15, 30, 45, 60];

/**
 * Delayed arrival: the fast lane.
 *
 * The situation this exists for is a brief stop — engine running, baby just
 * gone under, the parent about to pull away. Anything that needs two hands or
 * three screens is useless then. So: the destination is already known (saved
 * Home, or the last one they looked at), the durations are fixed, and one tap
 * launches navigation.
 *
 * The duration is the TOTAL journey, not extra time added on. If the parent
 * asks for less time than the drive actually takes, the backend says so and
 * returns the direct route; we surface that rather than pretending.
 */
export function QuickDrive({ current, targets, profile }: Props) {
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [targetId, setTargetId] = useState<string | null>(null);

  if (targets.length === 0) return null; // nowhere to be sent yet

  const target =
    targets.find((t) => t.id === targetId) ?? targets[0];

  async function go(minutes: number) {
    if (!current) return;
    setError(null);
    setNote(null);
    setBusy(minutes);
    try {
      const data = await generateRoutes({
        start: current,
        finish: target.coord,
        target_minutes: minutes,
        tolerance_minutes: 10,
        road_profile: profile,
        direction: "surprise",
        mode: "destination",
      });
      const best = data.routes[0];
      if (!best) {
        setError(data.notice ?? "Couldn't build a drive right now. Try again.");
        return;
      }
      if (!best.maps_url) {
        // Simulated: no real route exists. There is no results screen here to
        // show a demo on, so say why nothing opened.
        setError("Live routing is unavailable, so there's no drive to open.");
        return;
      }
      if (best.is_direct && data.direct_minutes != null) {
        // Asked for less time than the journey takes. Still useful — it is the
        // way there — but say so before the navigation app takes the screen.
        setNote(
          `${target.label} is about ${Math.round(data.direct_minutes)} min away, ` +
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

  const heading =
    target.kind === "home" ? "Quick drive home" : "Still asleep?";
  const sub =
    target.kind === "home"
      ? "A longer way back, ending at Home"
      : `A longer way to ${target.label}`;

  return (
    <section className="quick" aria-label="Delayed arrival">
      <div className="quick-head">
        <span className="quick-title">{heading}</span>
        <span className="quick-sub">{sub}</span>
      </div>

      {/* Bible section 9: route setup happens while parked or is done by a
          passenger. This is the screen most likely to be reached mid-journey,
          so it is the screen that has to say so. Calm and non-blocking - it
          offers the alternative rather than just forbidding, and it never
          prevents the tap. */}
      <p className="quick-safety">
        Set this up while parked, or hand it to a passenger.
      </p>

      {targets.length > 1 && (
        <div className="quick-targets" role="group" aria-label="Where to">
          {targets.map((t) => (
            <button
              key={t.id}
              className={`quick-target${t.id === target.id ? " quick-target-on" : ""}`}
              aria-pressed={t.id === target.id}
              onClick={() => {
                setTargetId(t.id);
                setError(null);
                setNote(null);
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      <div className="quick-row">
        {QUICK_DURATIONS.map((m) => (
          <button
            key={m}
            className="quick-btn"
            disabled={!current || busy !== null}
            onClick={() => go(m)}
          >
            {busy === m ? "…" : `${m} min`}
          </button>
        ))}
      </div>

      <p className="quick-note">
        Total journey time, not extra. Times are estimates.
      </p>
      {!current && <p className="quick-note">Waiting for your location…</p>}
      {note && <p className="quick-note">{note}</p>}
      {error && <p className="quick-note quick-err">{error}</p>}
    </section>
  );
}
