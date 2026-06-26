import { useState } from "react";
import type {
  Coord,
  Direction,
  GenerateResponse,
  RoadProfile,
  RouteOption,
} from "./types";
import { generateRoutes, saveFavourite } from "./api";
import { useGeolocation } from "./hooks/useGeolocation";
import { useSettings } from "./hooks/useSettings";
import { usePlaces } from "./hooks/usePlaces";
import { useOwner } from "./hooks/useOwner";
import { ChipGroup } from "./components/ChipGroup";
import { RouteCard } from "./components/RouteCard";
import { SafetyNote } from "./components/SafetyNote";
import { Feedback } from "./components/Feedback";
import { QuickDrive } from "./components/QuickDrive";
import { Favourites } from "./components/Favourites";
import { SettingsScreen } from "./components/SettingsScreen";

type Screen =
  | { name: "plan" }
  | { name: "loading" }
  | { name: "results"; data: GenerateResponse; start: Coord; profile: RoadProfile }
  | { name: "favourites" }
  | { name: "settings" };

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
  const { defaultPlace, saveHome } = usePlaces();
  const owner = useOwner();

  const [screen, setScreen] = useState<Screen>({ name: "plan" });
  const [duration, setDuration] = useState<number>(settings.lastDuration);
  const [profile, setProfile] = useState<RoadProfile>(settings.lastProfile);
  const [tolerance, setTolerance] = useState<number>(settings.lastTolerance);
  const [direction, setDirection] = useState<Direction>("surprise");
  const [error, setError] = useState<string | null>(null);
  // Which route the user has launched in Google Maps (drives the inline
  // feedback prompt). Null means none started yet.
  const [startedId, setStartedId] = useState<string | null>(null);
  // Route ids saved to favourites this session (fills the star).
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());

  // Resolve the start point: live location, or saved Home as a fallback.
  const homeCoord: Coord | null = defaultPlace
    ? { lat: defaultPlace.lat, lng: defaultPlace.lng }
    : null;
  const liveCoord: Coord | null =
    geo.status === "ready" ? geo.coord : null;
  const start: Coord | null = liveCoord ?? homeCoord;

  async function runGenerate(targetMinutes: number) {
    if (!start) return;
    setError(null);
    setStartedId(null);
    setSavedIds(new Set());
    setScreen({ name: "loading" });
    update({
      lastDuration: duration,
      lastProfile: profile,
      lastTolerance: tolerance,
    });
    try {
      const data = await generateRoutes({
        start,
        finish: homeCoord ?? start,
        target_minutes: targetMinutes,
        tolerance_minutes: tolerance,
        road_profile: profile,
        direction,
      });
      setScreen({ name: "results", data, start, profile });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setScreen({ name: "plan" });
    }
  }

  function onGenerate() {
    void runGenerate(duration);
  }

  // Pre-launch variants (Option C): regenerate a longer companion before
  // setting off, so a parent can pre-decide on a bit more driving.
  function onExtendPlan(extraMinutes: number) {
    if (screen.name !== "results") return;
    void runGenerate(screen.data.target_minutes + extraMinutes);
  }

  function onStartRoute(route: RouteOption) {
    // Open Google Maps (new tab / the Maps app on a phone) but STAY on the
    // results screen so the other two routes remain available to compare.
    // The inline feedback prompt appears under the chosen route.
    window.open(route.maps_url, "_blank", "noopener");
    setStartedId(route.id);
  }

  async function onSaveRoute(route: RouteOption) {
    if (screen.name !== "results") return;
    if (savedIds.has(route.id)) return; // already saved
    setSavedIds((prev) => new Set(prev).add(route.id)); // optimistic
    await saveFavourite({
      owner,
      duration_minutes: screen.data.target_minutes,
      distance_km: route.distance_km,
      road_profile: screen.profile,
      character: route.character,
      maps_url: route.maps_url,
      place_label: defaultPlace?.label ?? "Home",
    });
  }

  function saveHomeFromLocation() {
    if (geo.status === "ready") saveHome(geo.coord);
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
        {screen.name === "plan" && (
          <div className="masthead-actions">
            <button
              className="btn-back"
              onClick={() => setScreen({ name: "favourites" })}
            >
              ★ Saved
            </button>
            <button
              className="btn-back"
              onClick={() => setScreen({ name: "settings" })}
              aria-label="Settings"
            >
              ⚙
            </button>
          </div>
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
            home={homeCoord}
            onRetry={locate}
            onSaveHome={saveHomeFromLocation}
          />

          <QuickDrive
            current={liveCoord}
            home={homeCoord}
            profile={settings.quickDriveProfile}
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
                onSave={onSaveRoute}
                saved={savedIds.has(r.id)}
                units={settings.units}
              />
              {startedId === r.id && (
                <Feedback
                  route={r}
                  owner={owner}
                  onDone={() => setStartedId(null)}
                />
              )}
            </div>
          ))}
          <div className="extend">
            <span className="extend-label">Want a bit longer?</span>
            <div className="extend-btns">
              <button className="extend-btn" onClick={() => onExtendPlan(15)}>
                +15 min
              </button>
              <button className="extend-btn" onClick={() => onExtendPlan(30)}>
                +30 min
              </button>
            </div>
          </div>
          <p className="results-foot">
            {startedId
              ? "Started in Google Maps. You can still compare the other loops above."
              : "Times use current traffic and may shift as you drive."}
          </p>
        </main>
      )}

      {screen.name === "favourites" && (
        <Favourites
          owner={owner}
          units={settings.units}
          onBack={() => setScreen({ name: "plan" })}
        />
      )}

      {screen.name === "settings" && (
        <SettingsScreen settings={settings} update={update} />
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
