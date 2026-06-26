import { useState } from "react";
import type { Coord, RoadProfile } from "../types";
import { generateRoutes } from "../api";

interface Props {
  current: Coord | null;          // live location (start)
  home: Coord | null;             // default saved place (finish)
  profile: RoadProfile;           // last-used profile, or a sensible default
}

const QUICK_DURATIONS = [15, 30, 60];

// The fast lane: one tap launches a drive of the chosen total duration that
// ends at Home, from wherever you are now. No route comparison, no extra
// screens — removing in-car decisions is deliberate. It's a detour (padded
// route to Home), not a loop, so the backend handles it by start != finish.
export function QuickDrive({ current, home, profile }: Props) {
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!home) return null; // nothing to drive back to yet

  async function go(minutes: number) {
    if (!current || !home) return;
    setError(null);
    setBusy(minutes);
    try {
      const data = await generateRoutes({
        start: current,
        finish: home,
        target_minutes: minutes,
        tolerance_minutes: 10,
        road_profile: profile,
        direction: "surprise",
      });
      const best = data.routes[0];
      if (!best) {
        setError("Couldn't build a drive home right now. Try again.");
        return;
      }
      window.open(best.maps_url, "_blank", "noopener");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="quick" aria-label="Quick drive home">
      <div className="quick-head">
        <span className="quick-title">Quick drive home</span>
        <span className="quick-sub">A longer way back, ending at Home</span>
      </div>
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
      {!current && (
        <p className="quick-note">Waiting for your location…</p>
      )}
      {error && <p className="quick-note quick-err">{error}</p>}
    </section>
  );
}
