import { useState } from "react";
import type {
  Coord,
  Direction,
  GenerateResponse,
  RoadProfile,
  RouteOption,
} from "./types";
import { generateRoutes } from "./api";
import { useGeolocation } from "./hooks/useGeolocation";
import { useSettings } from "./hooks/useSettings";
import { ChipGroup } from "./components/ChipGroup";
import { RouteCard } from "./components/RouteCard";
import { SafetyNote } from "./components/SafetyNote";
import { Feedback } from "./components/Feedback";

type Screen =
  | { name: "plan" }
  | { name: "loading" }
  | { name: "results"; data: GenerateResponse; start: Coord };

const DURATIONS = [20, 30, 45, 60, 90];

const PROFILE_OPTS: { value: RoadProfile; label: string; sub: string }[] = [
  { value: "motorway", label: "Motorways", sub: "Steady & fast" },
  { value: "mixed", label: "Mixed", sub: "A bit of each" },
  { value: "quiet", label: "Quieter", sub: "Local roads" },
];

const DIRECTION_OPTS: { value: Direction; label: string }[] = [
  { value: "surprise", label: "Any" },
  { value: "N", label: "N" },
  { value: "E", label: "E" },
  { value: "S", label: "S" },
  { value: "W", label: "W" },
];

export default function App() {
  const { state: geo, locate } = useGeolocation();
  const { settings, update } = useSettings();

  const [screen, setScreen] = useState<Screen>({ name: "plan" });
  const [duration, setDuration] = useState<number>(settings.lastDuration);
  const [profile, setProfile] = useState<RoadProfile>(settings.lastProfile);
  const [tolerance, setTolerance] = useState<number>(settings.lastTolerance);
  const [direction, setDirection] = useState<Direction>("surprise");
  const [error, setError] = useState<string | null>(null);
  // Which route the user has launched in Google Maps (drives the inline
  // feedback prompt). Null means none started yet.
  const [startedId, setStartedId] = useState<string | null>(null);

  // Resolve the start point: live location, or saved Home as a fallback.
  const start: Coord | null =
    geo.status === "ready" ? geo.coord : settings.home;

  async function onGenerate() {
    if (!start) return;
    setError(null);
    setStartedId(null);
    setScreen({ name: "loading" });
    update({
      lastDuration: duration,
      lastProfile: profile,
      lastTolerance: tolerance,
    });
    try {
      const data = await generateRoutes({
        start,
        finish: settings.home ?? start,
        target_minutes: duration,
        tolerance_minutes: tolerance,
        road_profile: profile,
        direction,
      });
      setScreen({ name: "results", data, start });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setScreen({ name: "plan" });
    }
  }

  function onStartRoute(route: RouteOption) {
    // Open Google Maps (new tab / the Maps app on a phone) but STAY on the
    // results screen so the other two routes remain available to compare.
    // The inline feedback prompt appears under the chosen route.
    window.open(route.maps_url, "_blank", "noopener");
    setStartedId(route.id);
  }

  function saveHomeFromLocation() {
    if (geo.status === "ready") update({ home: geo.coord });
  }

  return (
    <div className="app">
      <header className="masthead">
        <div className="wordmark">
          <span className="wordmark-drift">drift</span>
          <span className="wordmark-way">way</span>
        </div>
        {screen.name !== "plan" && (
          <button
            className="btn-back"
            onClick={() => setScreen({ name: "plan" })}
          >
            ← Plan
          </button>
        )}
      </header>

      {screen.name === "plan" && (
        <main className="plan">
          <p className="tagline">
            Pick how long you want to drive. We'll make a smooth loop and bring
            you home.
          </p>

          <LocationRow
            geo={geo}
            home={settings.home}
            onRetry={locate}
            onSaveHome={saveHomeFromLocation}
          />

          <div className="duration-hero">
            <div className="duration-ring">
              <span className="duration-num">{duration}</span>
              <span className="duration-unit">minutes</span>
            </div>
          </div>

          <ChipGroup
            legend="How long"
            columns={5}
            options={DURATIONS.map((d) => ({ value: d, label: String(d) }))}
            value={DURATIONS.includes(duration) ? duration : 0}
            onChange={(d) => setDuration(d)}
          />

          <ChipGroup
            legend="Road style"
            columns={3}
            options={PROFILE_OPTS}
            value={profile}
            onChange={setProfile}
          />

          <div className="row-split">
            <ChipGroup
              legend="Tolerance"
              columns={2}
              options={[
                { value: 5, label: "±5" },
                { value: 10, label: "±10" },
              ]}
              value={tolerance}
              onChange={setTolerance}
            />
            <ChipGroup
              legend="Direction"
              columns={5}
              options={DIRECTION_OPTS}
              value={direction}
              onChange={setDirection}
            />
          </div>

          {error && <p className="error">{error}</p>}

          <button
            className="btn-generate"
            disabled={!start}
            onClick={onGenerate}
          >
            {start ? "Find three loops" : "Waiting for location…"}
          </button>

          <SafetyNote />
        </main>
      )}

      {screen.name === "loading" && (
        <main className="loading">
          <div className="loading-ring" />
          <p>Shaping {duration}-minute loops…</p>
        </main>
      )}

      {screen.name === "results" && (
        <main className="results">
          <p className="results-head">
            Three loops for about {screen.data.target_minutes} minutes
          </p>
          {screen.data.routes.map((r, i) => (
            <div key={r.id}>
              <RouteCard
                route={r}
                start={screen.start}
                rank={i + 1}
                targetMinutes={screen.data.target_minutes}
                onStart={onStartRoute}
                started={startedId === r.id}
              />
              {startedId === r.id && (
                <Feedback route={r} onDone={() => setStartedId(null)} />
              )}
            </div>
          ))}
          <p className="results-foot">
            {startedId
              ? "Started in Google Maps. You can still compare the other loops above."
              : "Times use current traffic and may shift as you drive."}
          </p>
        </main>
      )}
    </div>
  );
}

// --- location status row -------------------------------------------------

function LocationRow({
  geo,
  home,
  onRetry,
  onSaveHome,
}: {
  geo: ReturnType<typeof useGeolocation>["state"];
  home: Coord | null;
  onRetry: () => void;
  onSaveHome: () => void;
}) {
  if (geo.status === "ready") {
    return (
      <div className="loc loc-ok">
        <span>Using your location</span>
        <button className="btn-quiet" onClick={onSaveHome}>
          {home ? "Update Home" : "Save as Home"}
        </button>
      </div>
    );
  }
  if (geo.status === "locating") {
    return <div className="loc">Finding your location…</div>;
  }
  // idle or error
  return (
    <div className="loc loc-warn">
      <span>
        {geo.status === "error" ? geo.message : "Location not set."}
        {home ? " Using saved Home." : ""}
      </span>
      <button className="btn-quiet" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
