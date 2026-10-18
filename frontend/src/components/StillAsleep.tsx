import { useState } from "react";
import type { Coord, RoadProfile, StopPrefs } from "../types";
import { generateRoutes } from "../api";
import { PlaceSearch } from "./PlaceSearch";
import type { Endpoint } from "./PlaceSearch";
import type { StillAsleepTarget } from "../hooks/useStillAsleepTargets";
import {
  STILL_ASLEEP_DEFAULT_TOLERANCE,
  STILL_ASLEEP_DURATIONS,
} from "../lib/stillAsleepConfig";

interface Props {
  /** Where the phone says it is, when it has said. */
  current: Coord | null;
  /** Still asking the phone. */
  locating?: boolean;
  /** Why the phone's location isn't available, once that is known. */
  locationMessage?: string | null;
  targets: StillAsleepTarget[];
  /** Saved places, Home first: one tap to say where you are parked. */
  savedPlaces?: Endpoint[];
  /** Remembered planner defaults, reused rather than re-asked. */
  profile: RoadProfile;
  tolerance: number;
  /** What wakes the child, from Settings. */
  stops?: StopPrefs;
  /** A maintainer's drives are recorded for analysis. */
  record?: boolean;
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
  current: located,
  locating = false,
  locationMessage = null,
  targets,
  savedPlaces,
  profile,
  tolerance,
  stops,
  record = false,
  onOpenPreferences,
  onRetryLocation,
}: Props) {
  // Where the parent says they are, when the phone can't (founder report,
  // 11 Oct: the app sat on "Waiting for your location" with nothing to do).
  const [typed, setTyped] = useState<Endpoint | null>(null);
  const current: Coord | null = located ?? typed?.coord ?? null;
  const [targetId, setTargetId] = useState<string | null>(null);
  const [searched, setSearched] = useState<Endpoint | null>(null);
  const [picking, setPicking] = useState(false);
  const [minutes, setMinutes] = useState<number>(30);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Set only when the drive we found is not the one they asked for, so the
  // handoff waits for a deliberate second tap instead of happening on its own.
  const [held, setHeld] = useState<string | null>(null);

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
    setHeld(null);
    try {
      const data = await generateRoutes({
        start: current,
        finish: chosen.coord,
        target_minutes: minutes,
        tolerance_minutes: tolerance || STILL_ASLEEP_DEFAULT_TOLERANCE,
        road_profile: profile,
        direction: "surprise",
        mode: "destination",
        stops,
        // Typed in because the phone couldn't say: a picked start.
        start_chosen: (!located && typed !== null) || undefined,
        record: record || undefined,
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
        //
        // So this case stops and says it, rather than handing off at once:
        // previously the note was set and Google Maps opened in the same
        // moment, so the explanation was only visible after coming back.
        setNote(
          `${chosen.label} is about ${Math.round(data.direct_minutes)} min away, ` +
            `so there's no longer way to fill ${minutes} min — only the direct route.`,
        );
        setHeld(best.maps_url);
        return;
      }
      // The ordinary case hands straight off. That is the point of this
      // screen - one tap during a brief stop - and the button says in advance
      // where it goes, so the switch is expected rather than abrupt.
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
        className="btn-generate sa-go"
        disabled={!current || !chosen || busy}
        onClick={() => void findRoute()}
      >
        <span>{busy ? "Finding a route…" : "Find route"}</span>
        {!busy && <span className="sa-go-dest">Opens Google Maps</span>}
      </button>

      {!located && (
        <div className="sa-where">
          <p className="sa-hint">
            {locating && !typed
              ? "Waiting for your location…"
              : locationMessage ?? (typed ? "Starting from the place you chose." : "Location not set.")}{" "}
            <button className="btn-quiet" onClick={onRetryLocation}>
              {locating ? "Ask again" : "Try again"}
            </button>
          </p>
          <PlaceSearch
            legend="Where are you now?"
            value={typed}
            onChange={setTyped}
            saved={savedPlaces}
            placeholder="Search where you're parked"
          />
        </div>
      )}
      {note && <p className="sa-note">{note}</p>}
      {held && (
        <button
          className="btn-quiet sa-held"
          onClick={() => {
            window.open(held, "_blank", "noopener");
            setHeld(null);
          }}
        >
          Open the direct route in Google Maps
        </button>
      )}
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
