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
import { arrivalDate, clock, minutesUntil, suggestedArrival } from "./lib/arrival";
import { HelpScreen } from "./components/HelpScreen";
import { Orbit } from "./components/Orbit";
import { useGeolocation } from "./hooks/useGeolocation";
import { useSettings } from "./hooks/useSettings";
import { usePlaces } from "./hooks/usePlaces";
import { PlacesManager } from "./components/PlacesManager";
import { useOwner } from "./hooks/useOwner";
import { useRecentDestination } from "./hooks/useRecentDestination";
import { ChipGroup } from "./components/ChipGroup";
import { RouteCard } from "./components/RouteCard";
import { SafetyNote } from "./components/SafetyNote";
import { Feedback } from "./components/Feedback";
import { Favourites } from "./components/Favourites";
import { SettingsScreen } from "./components/SettingsScreen";
import { AppFeedback } from "./components/AppFeedback";
import { MovedBanner } from "./components/MovedBanner";
import { PlaceSearch } from "./components/PlaceSearch";
import { MeetHalfway } from "./meetup/MeetHalfway";
import { StillAsleep } from "./components/StillAsleep";
import { useStillAsleepTargets } from "./hooks/useStillAsleepTargets";
import { Walks } from "./walking/Walks";
import { useFeatures } from "./hooks/useFeatures";
import type { Endpoint } from "./components/PlaceSearch";

/**
 * The top-level jobs. Still Asleep lands first because it is the most
 * time-sensitive: a parent reaching for the phone with a sleeping child should
 * not have to navigate to the urgent thing.
 *
 * Round trip and Go somewhere deliberately do NOT get their own tabs. They are
 * different route primitives but share controls and mental context, so they
 * stay as a segmented choice inside Plan a drive.
 *
 * Walk is a tab by founder decision, 9 Oct 2026, after using it: as a header
 * button it made the navigation grow in two places at once. That supersedes the
 * brief's caution against a fourth tab before a tested design. It is still
 * behind WALKING_ENABLED, so switching the flag off removes the tab entirely.
 */
type Tab = "stillasleep" | "plan" | "meetup" | "walk";

const TABS: Tab[] = ["stillasleep", "plan", "meetup", "walk"];

/**
 * The tab named in the URL hash, if any. The hash is what lets a refresh - or
 * a return from signing in - land on the same tab. Opening the app fresh (from
 * the home screen, with no hash) still starts on Still asleep.
 */
const START_TAB: Tab = "stillasleep";

/** What a history entry is to this app: a tab above Still asleep, or a
 *  screen (Saved, Settings, results) above a tab. None: the bottom. */
type NavState = { driftway?: "tab" | "screen" } | null;
function navKind(): "tab" | "screen" | undefined {
  return (window.history.state as NavState)?.driftway;
}
function urlFor(tab: Tab): string {
  return `${window.location.pathname}${window.location.search}#${tab}`;
}

function tabFromHash(): Tab | null {
  const raw = window.location.hash.replace("#", "") as Tab;
  return TABS.includes(raw) ? raw : null;
}

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
      /** Planned to arrive by this time (ms), rather than by length. */
      arriveAt?: number;
    }
  | { name: "favourites" }
  | { name: "settings" }
  | { name: "help" };

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
  const { places, defaultPlace, saveHome, change: changePlace, store: placeStore } = usePlaces();
  const { recent, remember } = useRecentDestination();
  const owner = useOwner();
  // Feedback about the app, from any tab (0.8, for the beta).
  const [feedbackOpen, setFeedbackOpen] = useState(false);

  // A meetup link opens the meetup directly. Checked once, from the URL,
  // before anything renders, so a shared link never lands on the wrong job.
  const [tab, setTabState] = useState<Tab>(() =>
    hasMeetupLink() ? "meetup" : tabFromHash() ?? "stillasleep",
  );
  // Android's Back button (founder report, 11 Oct 2026: it closed the app
  // from anywhere). It walks this app's history, so the history now has
  // levels, the usual Android pattern:
  //   - Still asleep, nothing open: the bottom. Back leaves the app.
  //   - another tab: one entry above it. Back returns to Still asleep.
  //   - Saved, Settings or drive results: one entry above the tab. Back
  //     closes them and returns to the tab.
  // Switching between other tabs replaces that one entry rather than adding
  // one per tap. The query string is kept: it may carry a meetup capability.
  function setTab(next: Tab) {
    const kind = navKind();
    setTabState(next);
    if (kind === "screen") {
      // Tab bar used while drive results are open: Back still closes them.
      window.history.replaceState({ driftway: "screen" }, "", urlFor(next));
    } else if (next === START_TAB && kind === "tab") {
      window.history.back(); // the popstate below shows Still asleep
    } else if (next === START_TAB || kind === "tab") {
      window.history.replaceState(kind ? { driftway: kind } : null, "", urlFor(next));
    } else {
      window.history.pushState({ driftway: "tab" }, "", urlFor(next));
    }
  }
  // A link to /#help (the welcome page for testers) opens Help.
  const [screen, setScreenState] = useState<Screen>(() =>
    window.location.hash === "#help" ? { name: "help" } : { name: "plan" },
  );
  useEffect(() => {
    if (window.location.hash !== "#help") return;
    // Help above Still asleep, so Back (and the Back button) shows the app.
    window.history.replaceState(null, "", urlFor(START_TAB));
    window.history.pushState({ driftway: "screen" }, "", urlFor(START_TAB));
  }, []);
  /** Help from Settings: one level above it, so Back returns to Settings. */
  function openHelp() {
    setScreenState({ name: "help" });
    window.history.pushState({ driftway: "screen" }, "", urlFor(tab));
  }
  /** Show Saved, Settings or results: one Back closes them again. */
  function openScreen(next: Screen) {
    setScreenState(next);
    if (navKind() === "screen") window.history.replaceState({ driftway: "screen" }, "", urlFor(tab));
    else window.history.pushState({ driftway: "screen" }, "", urlFor(tab));
  }
  /** Close them from the app's own controls, as Back would. */
  function closeScreen() {
    if (navKind() === "screen") window.history.back();
    else setScreenState({ name: "plan" });
  }
  // Any other change of screen (loading, back to the form) is not a level.
  const setScreen = setScreenState;
  useEffect(() => {
    function onPop(e: PopStateEvent) {
      const kind = (e.state as NavState)?.driftway;
      if (kind !== "screen") {
        setScreenState((prev) =>
          prev.name === "favourites" ||
          prev.name === "settings" ||
          prev.name === "help" ||
          prev.name === "results"
            ? { name: "plan" }
            : prev,
        );
      } else {
        // Back from Help opened in Settings.
        setScreenState((prev) => (prev.name === "help" ? { name: "settings" } : prev));
      }
      if (kind === undefined) {
        // Back at the bottom: Still asleep, whatever the first entry was.
        setTabState(START_TAB);
        window.history.replaceState(null, "", urlFor(START_TAB));
      } else {
        setTabState(tabFromHash() ?? START_TAB);
      }
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const features = useFeatures();
  const [mode, setMode] = useState<RouteMode>("loop");
  const [duration, setDuration] = useState<number>(settings.lastDuration);
  const [profile, setProfile] = useState<RoadProfile>(settings.lastProfile);
  const [tolerance, setTolerance] = useState<number>(settings.lastTolerance);
  const [direction, setDirection] = useState<Direction>("surprise");
  // By length, or by when to arrive (founder, 18 Oct 2026: "sometimes it's
  // easier than calculating which time period fits"). Each visit starts by
  // length; the last arrival time is remembered.
  const [planBy, setPlanBy] = useState<"length" | "arrival">("length");
  const [arrival, setArrival] = useState<string>(
    () => settings.lastArrival || suggestedArrival(new Date()),
  );
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (planBy !== "arrival") return;
    setNow(new Date());
    const t = window.setInterval(() => setNow(new Date()), 15000);
    return () => window.clearInterval(t);
  }, [planBy]);
  const until = minutesUntil(arrival, now);
  const arrivalAt = arrivalDate(arrival, now);
  const arrivalLabel = arrivalAt ? clock(arrivalAt) : "";
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

  // Every saved place, Home first, for the one-tap choices in each place
  // search (11 Oct 2026: more than Home).
  const placeEndpoints: Endpoint[] = useMemo(
    () =>
      [...places]
        .sort((a, b) => Number(b.isDefault) - Number(a.isDefault))
        .map((p) => ({
          coord: { lat: p.lat, lng: p.lng },
          label: p.label,
          detail: p.detail,
          source: p.isDefault ? ("home" as const) : ("saved" as const),
        })),
    [places],
  );

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
    !!start &&
    (mode === "loop" || !!toEndpoint) &&
    (planBy === "length" || until.problem === null);

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
    planBy,
    arrival,
    profile,
    tolerance,
    direction,
    fromEndpoint?.coord.lat,
    fromEndpoint?.coord.lng,
    toEndpoint?.coord.lat,
    toEndpoint?.coord.lng,
  ]);

  async function runGenerate(targetMinutes: number, arriveAt?: Date) {
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
      ...(arriveAt ? { lastArrival: arrival } : {}),
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
        stops: settings.stopPrefs,
        arrive_by: arriveAt ? true : undefined,
        // From the phone's own location the links carry no start, so Google
        // Maps starts from wherever the phone is by then (founder, 17-18 Oct).
        start_chosen: startEndpoint?.source !== "current" || undefined,
        record: settings.recordDrives || undefined,
      });
      openScreen({
        name: "results",
        data,
        start,
        profile,
        fromLabel: startEndpoint?.label ?? "Your location",
        toLabel:
          mode === "loop"
            ? (startEndpoint?.label ?? "Your location")
            : (toEndpoint?.label ?? "your destination"),
        arriveAt: arriveAt?.getTime(),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setScreen({ name: "plan" });
    }
  }

  function onGenerate() {
    if (planBy === "length") {
      void runGenerate(duration);
      return;
    }
    // The minutes from this moment, not from when the screen last ticked.
    const fresh = new Date();
    const left = minutesUntil(arrival, fresh);
    const at = arrivalDate(arrival, fresh);
    if (left.problem || !at) {
      setError(left.problem);
      return;
    }
    void runGenerate(left.minutes, at);
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

  // "Save as Home" says whether it was kept, never "saved" when it wasn't.
  const [homeNote, setHomeNote] = useState<string | null>(null);
  function saveHomeFromLocation() {
    if (geo.status !== "ready") return;
    const r = saveHome(geo.coord);
    setHomeNote(
      !r.ok
        ? r.message
        : r.persisted
          ? "Home saved on this device."
          : "Home is set for this visit only: this browser isn't keeping data just now.",
    );
  }

  const isSecondary =
    screen.name === "favourites" || screen.name === "settings" || screen.name === "help";

  return (
    <div className={`app${isSecondary ? "" : " app-tabbed"}`}>
      {feedbackOpen && (
        <AppFeedback
          context={isSecondary ? "settings" : tab === "plan" ? "plan" : tab}
          owner={owner}
          onClose={() => setFeedbackOpen(false)}
        />
      )}
      <MovedBanner />
      <header className="masthead">
        <div className="wordmark">
          <span className="wordmark-drift">drift</span>
          <span className="wordmark-way">way</span>
        </div>
        {isSecondary ? (
          <button className="btn-back" onClick={closeScreen}>
            ← Back
          </button>
        ) : (
          <div className="masthead-actions">
            <button className="btn-back" onClick={() => setFeedbackOpen(true)}>
              Feedback
            </button>
            <button
              className="btn-back"
              onClick={() => openScreen({ name: "favourites" })}
            >
              ★ Saved
            </button>
            <button
              className="btn-back"
              onClick={() => openScreen({ name: "settings" })}
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
          locating={geo.status === "locating" || geo.status === "idle"}
          locationMessage={geo.status === "error" ? geo.message : null}
          targets={stillAsleepTargets}
          savedPlaces={placeEndpoints}
          profile={settings.quickDriveProfile}
          tolerance={tolerance}
          stops={settings.stopPrefs}
          record={settings.recordDrives}
          onOpenPreferences={() => openScreen({ name: "settings" })}
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
          {homeNote && <p className="mode-note" role="status">{homeNote}</p>}

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
              saved={placeEndpoints}
              placeholder="Search a starting point"
            />

            {mode === "destination" && (
              <PlaceSearch
                legend="To"
                value={toEndpoint}
                onChange={setToEndpoint}
                near={liveCoord ?? homeCoord}
                saved={placeEndpoints}
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
              {planBy === "length"
                ? "The time below is the whole journey, not extra time on top."
                : "Drives get you to your destination by the time below."}
            </p>
          )}

          <ChipGroup
            legend="Plan by"
            columns={2}
            options={[
              { value: "length" as const, label: "How long" },
              {
                value: "arrival" as const,
                label: mode === "loop" ? "Back by" : "Arrive by",
                sub: "a time",
              },
            ]}
            value={planBy}
            onChange={setPlanBy}
          />

          <div className="duration-hero">
            <div className="duration-ring">
              <span className="duration-num">
                {planBy === "length" ? duration : until.problem ? "–" : until.minutes}
              </span>
              <span className="duration-unit">
                {planBy === "length" ? "minutes" : `min until ${arrivalLabel}`}
              </span>
            </div>
          </div>

          {planBy === "length" ? (
            <ChipGroup
              legend="How long"
              columns={5}
              options={DURATIONS.map((d) => ({ value: d, label: String(d) }))}
              value={DURATIONS.includes(duration) ? duration : 0}
              onChange={(d) => setDuration(d)}
            />
          ) : (
            <div className="arrive">
              <label className="account-field arrive-field">
                <span>{mode === "loop" ? "Back by" : "Arrive by"}</span>
                <input
                  type="time"
                  value={arrival}
                  onChange={(e) => setArrival(e.target.value)}
                />
              </label>
              <p className={until.problem ? "error" : "mode-note"} role="status">
                {until.problem ??
                  (mode === "loop"
                    ? "Every loop is back by then, a few minutes early, if you leave now. Each one says when to leave by."
                    : "Every drive arrives by then, a few minutes early, if you leave now. Each one says when to leave by.")}
              </p>
            </div>
          )}

          <ChipGroup
            legend="Road style"
            columns={3}
            options={PROFILE_OPTS}
            value={profile}
            onChange={setProfile}
          />

          {/* Finer options: shown with "All" settings, or once changed. */}
          {(settings.advanced || tolerance !== 10 || direction !== "surprise") && (
            <div className="row-split">
              {(settings.advanced || tolerance !== 10) && (
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
              )}
              {(settings.advanced || direction !== "surprise") && (
                <ChipGroup
                  legend="Direction"
                  columns={5}
                  options={DIRECTION_OPTS}
                  value={direction}
                  onChange={setDirection}
                />
              )}
            </div>
          )}

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
          <Orbit />
          <p>
            {planBy === "arrival"
              ? `Shaping drives that ${mode === "loop" ? "are back" : "arrive"} by ${arrivalLabel}…`
              : `Shaping ${duration}-minute ${mode === "loop" ? "loops" : "drives"}…`}
          </p>
        </main>
      )}

      {tab === "plan" && screen.name === "results" && (
        <main className="results">
          <p className="results-head">
            {resultsHeadline(screen.data, screen.fromLabel, screen.toLabel, screen.arriveAt)}
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
                arriveAt={screen.arriveAt}
                now={now}
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
          {/* Not with an arrival time (longer would be late), nor for the
              direct way (there is nothing to lengthen). */}
          {screen.arriveAt == null && !screen.data.routes.every((r) => r.is_direct) && (
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
          )}
          <p className="results-foot">
            {startedId
              ? "Started in Google Maps. You can still compare the other loops above."
              : "Times use current traffic and may shift as you drive."}
          </p>
        </main>
      )}

      {screen.name === "favourites" && (
        <PlacesManager places={places} store={placeStore} change={changePlace} here={liveCoord} />
      )}
      {screen.name === "favourites" && (
        <Favourites
          owner={owner}
          units={settings.units}
          onBack={closeScreen}
        />
      )}

      {screen.name === "settings" && (
        <SettingsScreen
          settings={settings}
          update={update}
          server={features.server}
          onOpenHelp={openHelp}
        />
      )}
      {screen.name === "help" && (
        <HelpScreen meetHalfway={features.meetHalfway} walking={features.walking} />
      )}

      {tab === "walk" && !isSecondary && (
        <Walks
          units={settings.units}
          here={liveCoord}
          savedPlaces={placeEndpoints}
          canGenerate={features.walkGeneration}
          onOpenSettings={() => openScreen({ name: "settings" })}
          advanced={settings.advanced}
        />
      )}

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
          {features.meetHalfway && (
            <TabButton id="meetup" label="Meet up" active={tab} onSelect={setTab} />
          )}
          {/* Whether this person may use walks is the server's decision; the
              flag only says the experiment exists on this deployment. */}
          {features.walking && (
            <TabButton id="walk" label="Walk" active={tab} onSelect={setTab} />
          )}
        </nav>
      )}

      {tab === "meetup" && !isSecondary && (
        <MeetHalfway
          currentLocation={liveCoord}
          home={homeEndpoint}
          saved={placeEndpoints}
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
  arriveAt?: number,
): string {
  const mins = data.target_minutes;
  // Mid-sentence, "Your location" is "your location".
  const loopFrom = fromLabel === "Your location" ? "your location" : fromLabel;
  if (arriveAt != null) {
    const by = clock(new Date(arriveAt));
    return data.mode === "destination"
      ? `${fromLabel} to ${toLabel}, arriving by ${by}`
      : `Loops from ${loopFrom}, back by ${by}`;
  }
  if (data.mode === "destination") {
    return `${fromLabel} to ${toLabel}, about ${mins} minutes in total`;
  }
  return `Loops from ${loopFrom} for about ${mins} minutes`;
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
