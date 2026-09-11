import { useState } from "react";
import type { Coord, RoadProfile } from "../types";
import { generateRoutes } from "../api";
import { PlaceSearch } from "./PlaceSearch";
import type { Endpoint } from "./PlaceSearch";
import type { StillAsleepTarget } from "../hooks/useStillAsleepTargets";
import {
  STILL_ASLEEP_DEFAULT_TOLERANCE,
  STILL_ASLEEP_DURATIONS,
} from "../lib/stillAsleepConfig";

interface Props {
  current: Coord | null;
  targets: StillAsleepTarget[];
  /** Remembered planner defaults, reused rather than re-asked. */
  profile: RoadProfile;
  tolerance: number;
  onOpenPreferences: () => void;
  onRetryLocation: () => void;
}

/**
 * Still Asleep — the default landing view.
 *
 * This is the screen a parent reaches with a sleeping child in the back and
 * seconds to act, so it asks two questions and nothing else: where are you
 * going, and how long should the drive take from now. Everything else —
 * road style, tolerance, direction — reuses remembered defaults and lives
 * behind Route preferences.
 *
 * It must work on a cold launch with no history, which is why "Choose
 * destination" is always available rather than appearing only when the app
 * has nothing remembered.
 */
export function StillAsleep({
  current,
  targets,
  profile,
  tolerance,
  onOpenPreferences,
  onRetryLocation,
}: Props) {
  const [targetId, setTargetId] = useState<string | null>(null);
  const [searched, setSearched] = useState<Endpoint | null>(null);
  const [picking, setPicking] = useState(false);
  const [minutes, setMinutes] = useState<number>(30);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const chosen: StillAsleepTarget | null =
    searched
      ? {
          id: "searched",
          label: searched.label,
          detail: searched.detail,
          coord: searched.coord,
          kind: "recent",
        }
      : targets.find((t) => t.id === targetId) ?? targets[0] ?? null;

  async function findRoute() {
    if (!current || !chosen) return;
    setBusy(true);
    setNote(null);
    setError(null);
    try {
      const data = await generateRoutes({
        start: current,
        finish: chosen.coord,
        target_minutes: minutes,
        tolerance_minutes: tolerance || STILL_ASLEEP_DEFAULT_TOLERANCE,
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
        setError("Live routing is unavailable, so there's no drive to open.");
        return;
      }
      if (best.is_direct && data.direct_minutes != null) {
        // The floor. Total remaining journey time cannot be less than the
        // quickest way there, and saying so beats opening a drive that is not
        // the one they asked for.
        setNote(
          `${chosen.label} is about ${Math.round(data.direct_minutes)} min away, ` +
            `so this is the direct route.`,
        );
      }
      window.open(best.maps_url, "_blank", "noopener");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="sa">
      <header className="sa-head">
        <h1 className="sa-title">Still asleep?</h1>
        <p className="sa-sub">A longer way there, so the nap finishes.</p>
      </header>

      <p className="sa-safety">
        Set this up while parked, or hand it to a passenger.
      </p>

      {/* --- where ------------------------------------------------------ */}
      <section className="sa-block">
        <span className="sa-legend">Drive to</span>

        {picking || targets.length === 0 ? (
          <PlaceSearch
            legend=""
            value={searched}
            onChange={(endpoint) => {
              setSearched(endpoint);
              setPicking(false);
            }}
            near={current}
            placeholder="Search a destination"
          />
        ) : (
          <>
            <div className="sa-targets" role="group" aria-label="Destination">
              {targets.map((t) => (
                <button
                  key={t.id}
                  className={`sa-target${t.id === chosen?.id ? " sa-target-on" : ""}`}
                  aria-pressed={t.id === chosen?.id}
                  onClick={() => {
                    setTargetId(t.id);
                    setSearched(null);
                    setNote(null);
                    setError(null);
                  }}
                >
                  <span className="sa-target-label">{t.label}</span>
                  {/* A recent search is labelled as such, so it is never
                      mistaken for somewhere the parent deliberately kept. */}
                  {t.kind === "recent" && (
                    <span className="sa-target-kind">recent</span>
                  )}
                </button>
              ))}
            </div>
            <button className="sa-choose" onClick={() => setPicking(true)}>
              Choose somewhere else
            </button>
          </>
        )}

        {searched && !picking && (
          <p className="sa-chosen">
            Going to <strong>{searched.label}</strong>
            <button className="btn-quiet" onClick={() => setSearched(null)}>
              Change
            </button>
          </p>
        )}
      </section>

      {/* --- how long --------------------------------------------------- */}
      <section className="sa-block">
        <span className="sa-legend">Make the drive last</span>
        <div className="sa-durations">
          {STILL_ASLEEP_DURATIONS.map((m) => (
            <button
              key={m}
              className={`sa-duration${m === minutes ? " sa-duration-on" : ""}`}
              aria-pressed={m === minutes}
              onClick={() => setMinutes(m)}
            >
              {m}
              <span className="sa-duration-unit">min</span>
            </button>
          ))}
        </div>
        <p className="sa-hint">
          Total journey time from now, not extra. Times are estimates.
        </p>
      </section>

      <button
        className="btn-generate"
        disabled={!current || !chosen || busy}
        onClick={() => void findRoute()}
      >
        {busy ? "Finding a route…" : "Find route"}
      </button>

      {!current && (
        <p className="sa-hint">
          Waiting for your location.{" "}
          <button className="btn-quiet" onClick={onRetryLocation}>
            Retry
          </button>
        </p>
      )}
      {note && <p className="sa-note">{note}</p>}
      {error && <p className="sa-error">{error}</p>}

      <button className="sa-prefs" onClick={onOpenPreferences}>
        Route preferences
        <span className="sa-prefs-now">
          {profile === "motorway" ? "Motorways" : profile === "quiet" ? "Quieter" : "Mixed"}
          {" · ±"}
          {tolerance || STILL_ASLEEP_DEFAULT_TOLERANCE}
        </span>
      </button>
    </main>
  );
}
