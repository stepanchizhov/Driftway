import { useEffect, useMemo, useState } from "react";
import type {
  Coord,
  Direction,
  GenerateResponse,
  NavigationOption,
  RoadProfile,
  RouteMode,
  RouteOption,
} from "./types";
import { generateRoutes, saveFavourite } from "./api";
import { useGeolocation } from "./hooks/useGeolocation";
import { useSettings } from "./hooks/useSettings";
import { usePlaces } from "./hooks/usePlaces";
import { useOwner } from "./hooks/useOwner";
import { useRecentDestination } from "./hooks/useRecentDestination";
import { ChipGroup } from "./components/ChipGroup";
import { RouteCard } from "./components/RouteCard";
import { SafetyNote } from "./components/SafetyNote";
import { Feedback } from "./components/Feedback";
import { Favourites } from "./components/Favourites";
import { SettingsScreen } from "./components/SettingsScreen";
import { PlaceSearch } from "./components/PlaceSearch";
import { MeetHalfway } from "./meetup/MeetHalfway";
import { StillAsleep } from "./components/StillAsleep";
import { useStillAsleepTargets } from "./hooks/useStillAsleepTargets";
import { meetHalfwayEnabled } from "./meetup/api";
import { Walks } from "./walking/Walks";
import { walkingEnabled } from "./walking/api";
import type { Endpoint } from "./components/PlaceSearch";

/**
 * Three top-level jobs, per Bible v0.4 section 6. Still Asleep lands first
 * because it is the most time-sensitive: a parent reaching for the phone with
 * a sleeping child should not have to navigate to the urgent thing.
 *
 * Round trip and Go somewhere deliberately do NOT get their own tabs. They are
 * different route primitives but share controls and mental context, so they
 * stay as a segmented choice inside Plan a drive.
 */
type Tab = "stillasleep" | "plan" | "meetup";

/**
 * Where the Plan tab is in its own flow, plus the two secondary surfaces.
 * Saved places and Settings are secondary actions rather than top-level
 * destinations, so they overlay whichever tab is open.
 */
type Screen =
  | { name: "plan" }
  | { name: "loading" }
  | {
      name: "results";
      data: GenerateResponse;
      start: Coord;
      profile: RoadProfile;
      fromLabel: string;
      toLabel: string;
    }
  | { name: "favourites" }
  // The walking experiment. A secondary screen like Saved, deliberately not a
  // fourth tab: the brief rules out a permanent walking tab until a design has
  // been tested, and this way it can be removed without touching navigation.
  | { name: "walks" }
  | { name: "settings" };

const DURATIONS = [5, 10, 15, 20, 30, 45, 60, 90];

const MODE_OPTS: { value: RouteMode; label: string; sub: string }[] = [
  { value: "loop", label: "Round trip", sub: "Back where you started" },
  { value: "destination", label: "Go somewhere", sub: "The long way there" },
];

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
  const { places, defaultPlace, saveHome } = usePlaces();
  const { recent, remember } = useRecentDestination();
  const owner = useOwner();

  // A meetup link opens the meetup directly. Checked once, from the URL,
  // before anything renders, so a shared link never lands on the wrong job.
  const [tab, setTab] = useState<Tab>(() =>
    hasMeetupLink() ? "meetup" : "stillasleep",
  );
  const [screen, setScreen] = useState<Screen>({ name: "plan" });
  const [meetupAvailable, setMeetupAvailable] = useState(false);
  const [walkingAvailable, setWalkingAvailable] = useState(false);
  const [mode, setMode] = useState<RouteMode>("loop");
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

  // Explicitly chosen endpoints. `from` null means "use the device location",
  // which keeps the common case zero-tap while still allowing a parent to plan
  // a drive from the swimming pool while sitting at home.
  const [fromEndpoint, setFromEndpoint] = useState<Endpoint | null>(null);
  const [toEndpoint, setToEndpoint] = useState<Endpoint | null>(null);

  const homeCoord: Coord | null = defaultPlace
    ? { lat: defaultPlace.lat, lng: defaultPlace.lng }
    : null;
  const liveCoord: Coord | null = geo.status === "ready" ? geo.coord : null;

  const homeEndpoint: Endpoint | null = useMemo(
    () =>
      defaultPlace
        ? {
            coord: { lat: defaultPlace.lat, lng: defaultPlace.lng },
            label: defaultPlace.label || "Home",
            source: "home",
          }
        : null,
    [defaultPlace],
  );

  // Remember the destination the moment it is picked, not only when a route is
  // started. The whole point of delayed arrival is that the parent may never
  // have launched anything - they looked up the pool, drove there, and the
  // baby fell asleep on the way back out.
  useEffect(() => {
    if (toEndpoint) {
      remember(toEndpoint.label, toEndpoint.coord, toEndpoint.detail);
    }
  }, [toEndpoint?.coord.lat, toEndpoint?.coord.lng, toEndpoint?.label, remember]);

  // Saved places first, a genuinely recent search appended - never the
  // other way round. See useStillAsleepTargets.
  const stillAsleepTargets = useStillAsleepTargets(places, recent);

  const currentEndpoint: Endpoint | null = useMemo(
    () =>
      liveCoord
        ? { coord: liveCoord, label: "Your location", source: "current" }
        : null,
    [liveCoord?.lat, liveCoord?.lng],
  );

  // The start actually routed from. A searched "From" wins; otherwise the
  // device location. Home is NOT a silent fallback for the start - if location
  // is unavailable the parent is asked to pick a starting point instead.
  const startEndpoint: Endpoint | null = fromEndpoint ?? currentEndpoint;
  const start: Coord | null = startEndpoint?.coord ?? null;

  const canGenerate =
    !!start && (mode === "loop" || !!toEndpoint);

  // Any change to the inputs makes the routes on screen wrong. Drop them
  // rather than leave a stale card whose Google Maps link goes to the old
  // destination.
  useEffect(() => {
    setScreen((prev) => (prev.name === "results" ? { name: "plan" } : prev));
    setStartedId(null);
    setSavedIds(new Set());
  }, [
    mode,
    duration,
    profile,
    tolerance,
    direction,
    fromEndpoint?.coord.lat,
    fromEndpoint?.coord.lng,
    toEndpoint?.coord.lat,
    toEndpoint?.coord.lng,
  ]);

  useEffect(() => {
    void meetHalfwayEnabled().then(setMeetupAvailable);
    // The entry point appears only when the deployment has the experiment on.
    // Whether this person may use it is the server's decision, not this flag's.
    void walkingEnabled().then(setWalkingAvailable);
  }, []);

  async function runGenerate(targetMinutes: number) {
    if (!start) return;
    // A round trip finishes where it started, full stop. A saved Home must
    // never silently become the finish - that bug sent parents on a one-way
    // detour whenever Home was somewhere other than where they were parked.
    const finish =
      mode === "loop" ? start : toEndpoint?.coord ?? null;
    if (!finish) return;

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
        finish,
        target_minutes: targetMinutes,
        tolerance_minutes: tolerance,
        road_profile: profile,
        direction,
        mode,
        preferred_navigation: settings.preferredNavigation,
      });
      setScreen({
        name: "results",
        data,
        start,
        profile,
        fromLabel: startEndpoint?.label ?? "Your location",
        toLabel:
          mode === "loop"
            ? (startEndpoint?.label ?? "Your location")
            : (toEndpoint?.label ?? "your destination"),
      });
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

  function onStartRoute(route: RouteOption, via?: NavigationOption) {
    // A simulated route has no maps_url and must never reach a navigation app.
    if (!route.maps_url) return;
    // Prefer the option the card resolved: it already accounts for whether the
    // parent's chosen app can carry this route's shaping points.
    const url = via?.url ?? route.maps_url;
    // Open Google Maps (new tab / the Maps app on a phone) but STAY on the
    // results screen so the other two routes remain available to compare.
    // The inline feedback prompt appears under the chosen route.
    window.open(url, "_blank", "noopener");
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

  const isSecondary =
    screen.name === "favourites" || screen.name === "settings" || screen.name === "walks";

  return (
    <div className={`app${isSecondary ? "" : " app-tabbed"}`}>
      <header className="masthead">
        <div className="wordmark">
          <span className="wordmark-drift">drift</span>
          <span className="wordmark-way">way</span>
        </div>
        {isSecondary ? (
          <button className="btn-back" onClick={() => setScreen({ name: "plan" })}>
            ← Back
          </button>
        ) : (
          <div className="masthead-actions">
            {walkingAvailable && (
              <button className="btn-back" onClick={() => setScreen({ name: "walks" })}>
                Walks
              </button>
            )}
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

      {tab === "stillasleep" && !isSecondary && (
        <StillAsleep
          current={liveCoord}
          targets={stillAsleepTargets}
          profile={settings.quickDriveProfile}
          tolerance={tolerance}
          onOpenPreferences={() => setScreen({ name: "settings" })}
          onRetryLocation={locate}
        />
      )}

      {tab === "plan" && screen.name === "plan" && (
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

          <ChipGroup
            legend="Route type"
            columns={2}
            options={MODE_OPTS}
            value={mode}
            onChange={setMode}
          />

          <div className="endpoints">
            <PlaceSearch
              legend={mode === "loop" ? "Start and finish" : "From"}
              value={startEndpoint}
              onChange={setFromEndpoint}
              near={liveCoord ?? homeCoord}
              onUseCurrentLocation={
                currentEndpoint ? () => setFromEndpoint(null) : undefined
              }
              currentLocationLabel="Use my location"
              home={homeEndpoint}
              placeholder="Search a starting point"
            />

            {mode === "destination" && (
              <PlaceSearch
                legend="To"
                value={toEndpoint}
                onChange={setToEndpoint}
                near={liveCoord ?? homeCoord}
                home={homeEndpoint}
                placeholder="Search a destination"
              />
            )}
          </div>

          {mode === "loop" && (
            <p className="mode-note">
              This drive ends exactly where it begins.
            </p>
          )}
          {mode === "destination" && (
            <p className="mode-note">
              The time below is the whole journey, not extra time on top.
            </p>
          )}

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
            disabled={!canGenerate}
            onClick={onGenerate}
          >
            {generateLabel(mode, start, toEndpoint)}
          </button>

          <SafetyNote />
        </main>
      )}

      {tab === "plan" && screen.name === "loading" && (
        <main className="loading">
          <div className="loading-ring" />
          <p>Shaping {duration}-minute loops…</p>
        </main>
      )}

      {tab === "plan" && screen.name === "results" && (
        <main className="results">
          <p className="results-head">
            {resultsHeadline(screen.data, screen.fromLabel, screen.toLabel)}
          </p>
          {screen.data.mode === "destination" &&
            screen.data.direct_minutes != null && (
              <p className="results-baseline">
                Driving straight there takes about{" "}
                {Math.round(screen.data.direct_minutes)} min.
              </p>
            )}
          {screen.data.notice && (
            <p
              className={`results-notice${
                screen.data.simulated ? " results-notice-demo" : ""
              }`}
            >
              {screen.data.notice}
            </p>
          )}
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
                destination={screen.data.mode === "destination"}
                preferredNavigation={settings.preferredNavigation}
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
          <div className="extend" hidden={screen.data.routes.every((r) => r.is_direct)}>
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

      {screen.name === "walks" && <Walks units={settings.units} />}

      {/* Persistent job switcher. Hidden on the secondary surfaces so their
          own Back control is unambiguous. */}
      {!isSecondary && (
        <nav className="tabbar" aria-label="Main">
          <TabButton
            id="stillasleep"
            label="Still asleep"
            active={tab}
            onSelect={setTab}
          />
          <TabButton id="plan" label="Plan a drive" active={tab} onSelect={setTab} />
          {meetupAvailable && (
            <TabButton id="meetup" label="Meet up" active={tab} onSelect={setTab} />
          )}
        </nav>
      )}

      {tab === "meetup" && !isSecondary && (
        <MeetHalfway
          currentLocation={liveCoord}
          home={homeEndpoint}
          onExit={() => {
            // Clear the meetup query string so a reload does not bounce
            // straight back into it.
            window.history.replaceState(null, "", window.location.pathname);
            setTab("stillasleep");
          }}
        />
      )}
    </div>
  );
}

function TabButton({
  id,
  label,
  active,
  onSelect,
}: {
  id: Tab;
  label: string;
  active: Tab;
  onSelect: (t: Tab) => void;
}) {
  const on = id === active;
  return (
    <button
      className={`tabbtn${on ? " tabbtn-on" : ""}`}
      aria-current={on ? "page" : undefined}
      onClick={() => onSelect(id)}
    >
      {label}
    </button>
  );
}

/** True when the URL carries a meetup participant or results capability. */
function hasMeetupLink(): boolean {
  const q = new URLSearchParams(window.location.search);
  return Boolean((q.get("meetup") && q.get("join")) || q.get("results"));
}

function generateLabel(
  mode: RouteMode,
  start: Coord | null,
  to: Endpoint | null,
): string {
  if (!start) return "Choose a starting point";
  if (mode === "destination" && !to) return "Choose a destination";
  return mode === "loop" ? "Find three loops" : "Find three routes";
}

function resultsHeadline(
  data: GenerateResponse,
  fromLabel: string,
  toLabel: string,
): string {
  const mins = data.target_minutes;
  if (data.mode === "destination") {
    return `${fromLabel} to ${toLabel}, about ${mins} minutes in total`;
  }
  return `Loops from ${fromLabel} for about ${mins} minutes`;
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
