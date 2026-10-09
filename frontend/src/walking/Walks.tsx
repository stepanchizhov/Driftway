import { useEffect, useRef, useState } from "react";
import { ChipGroup } from "../components/ChipGroup";
import type { Units } from "../hooks/useSettings";
import {
  NotAdmitted,
  assessWalks,
  generateWalks,
  type GeneratedWalks,
  type Basis,
  type Verdict,
  type Walk,
  type WalkFinding,
  type WalksResponse,
} from "./api";
import { useWalkSetup, type WalkSetup } from "./useWalkSetup";
import { WalkMap } from "./WalkMap";
import { groupWalks } from "./group";
import type { Coord } from "../types";
import { PlaceSearch, type Endpoint } from "../components/PlaceSearch";
import { useDriftwayAuth } from "../auth/AuthProvider";

/**
 * Walks with a pram or a carrier - the experiment.
 *
 * The job of this screen, from the brief's acceptance criterion: a parent can
 * see the difficult sections before leaving, understand what is not known,
 * and choose a walk for a stated reason. So the order on each card is fixed -
 * what stops you, then what is hard, then what nobody has recorded - and an
 * unknown is never shown in the colour of "fine".
 */

const VERDICT_LABEL: Record<Verdict, string> = {
  ok: "No known problems",
  unknown: "No known problems, but parts aren't recorded",
  difficult: "Possible, with harder stretches",
  blocked: "Not suitable for your setup",
};

const BASIS_LABEL: Record<Basis, string> = {
  reported: "seen on foot",
  mapped: "from the map",
  modelled: "from terrain data",
  unknown: "not recorded",
};

const DURATIONS = [20, 30, 45, 60, 90];

function distance(m: number, units: Units): string {
  if (units === "mi") return `${(m / 1609.344).toFixed(1)} mi`;
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}

function at(m: number | null, units: Units): string {
  if (m == null) return "";
  if (units === "mi") return `after ${Math.round(m * 1.0936)} yd`;
  return `after ${Math.round(m / 10) * 10} m`;
}

function duration(min: number): string {
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

/**
 * How this walk fits the time asked for, in one sentence. Never silent: the
 * first version only sorted by duration, so asking for 60 minutes quietly
 * returned 20-minute walks.
 */
function fitSentence(walk: Walk, units: Units): string | null {
  const f = walk.fit;
  if (!f) return null;
  switch (f.kind) {
    case "turned":
      return f.whole_shape === "loop"
        ? `Go out along the circuit and turn back after about ` +
            `${distance(f.turn_back_at_m ?? 0, units)}` +
            (f.turn_back_near ? `, on ${f.turn_back_near},` : "") +
            ` for about ${duration(walk.minutes)}. The full circuit is about ` +
            `${duration(f.full_minutes)}.`
        : `Turn back after about ${distance(f.turn_back_at_m ?? 0, units)}` +
            (f.turn_back_near ? `, on ${f.turn_back_near},` : "") +
            ` for about ${duration(walk.minutes)}. The whole walk there and back ` +
            `is about ${duration(f.full_minutes)}.`;
    case "about_right":
      return null;
    case "shorter":
      return walk.shape === "out_and_back"
        ? `About ${duration(f.full_minutes)} for the whole walk there and back, ` +
            `shorter than the ${duration(f.requested_minutes)} you asked for.`
        : `About ${duration(f.full_minutes)}, shorter than the ` +
            `${duration(f.requested_minutes)} you asked for. ${FIXED[walk.shape]}`;
    case "longer":
      return (
        `About ${duration(f.full_minutes)}, longer than the ` +
        `${duration(f.requested_minutes)} you asked for. ${FIXED[walk.shape]}`
      );
  }
}

/** Why a walk that is not there-and-back cannot be fitted to the time. */
const FIXED: Record<Walk["shape"], string> = {
  loop: "It's a circuit, so it can't be stretched.",
  one_way: "It's a walk to a destination, so its length is fixed.",
  out_and_back: "",
};

/** Named from the shape measured on the ground, not the one declared. */
const SHAPE_LABEL: Record<Walk["path_shape"], string> = {
  loop: "Loop",
  lollipop: "Loop, partly walked twice",
  there_and_back: "There and back",
  one_way: "One way",
};

function numberOrNull(raw: string): number | null {
  const n = Number(raw.replace(",", "."));
  return raw.trim() === "" || Number.isNaN(n) ? null : n;
}

export function Walks({
  units,
  here,
  canGenerate,
  onOpenSettings,
}: {
  units: Units;
  /** Your position, if known. Used on this device only, to group walks. */
  here: Coord | null;
  /** Whether this deployment can make walks from any start. */
  canGenerate: boolean;
  onOpenSettings: () => void;
}) {
  const { setup, update } = useWalkSetup();
  // The own-time field shows a number only while that number is the one in
  // use: tapping a chip afterwards clears it, so the field never contradicts
  // the time the walks are fitted to.
  const [ownTime, setOwnTime] = useState(
    DURATIONS.includes(setup.minutes) ? "" : String(setup.minutes),
  );
  const auth = useDriftwayAuth();
  // The settings being edited, and the settings the walks on screen were made
  // with. Founder feedback, 9 Oct: changes used to do nothing visible until a
  // page refresh. Now nothing recalculates on each tap; an Update bar appears
  // when the two differ, and one tap recalculates everything.
  const [applied, setApplied] = useState<WalkSetup>(setup);
  const dirty = JSON.stringify(setup) !== JSON.stringify(applied);
  const [runToken, setRunToken] = useState(0);
  const [result, setResult] = useState<WalksResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notAdmitted, setNotAdmitted] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Assess the curated walks for the settings in use. `alive` drops an answer
  // that arrives after newer settings have been applied.
  useEffect(() => {
    let alive = true;
    const timer = window.setTimeout(() => {
      setBusy(true);
      setError(null);
      assessWalks({
        profile: applied.profile,
        minutes: applied.minutes,
        allow_out_and_back: applied.maxRetrace >= 0.5,
        ...(applied.profile === "pram"
          ? { pram: applied.pram }
          : applied.profile === "carrier"
            ? { carrier: applied.carrier }
            : {}),
      })
        .then((r) => {
          if (!alive) return;
          setResult(r);
          setNotAdmitted(null);
        })
        .catch((e) => {
          if (!alive) return;
          if (e instanceof NotAdmitted) setNotAdmitted(e.message);
          else setError(e instanceof Error ? e.message : "Something went wrong.");
        })
        .finally(() => alive && setBusy(false));
    }, 300);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [applied]);

  // With no curated walk starting here that fits, make walks straight away.
  const autoMake =
    canGenerate &&
    here !== null &&
    result !== null &&
    groupWalks(result.walks, here, applied).doorstep.length === 0;

  return (
    <main className="walks">
      <header className="walks-head">
        <h2 className="walks-title">
          Walks <span className="walks-badge">Experiment</span>
        </h2>
        <p className="walks-sub">
          Walks from where you are, checked against your pram or carrier.
          What&rsquo;s known is shown with where it comes from; what isn&rsquo;t,
          is said.
        </p>
      </header>

      <ChipGroup
        legend="Going with"
        columns={3}
        options={[
          { value: "pram", label: "Pram" },
          { value: "carrier", label: "Carrier" },
          { value: "walker", label: "Just me" },
        ]}
        value={setup.profile}
        onChange={(v) => update({ profile: v as WalkSetup["profile"] })}
      />

      <SetupPanel setup={setup} update={update} />
      <PrefsPanel setup={setup} update={update} />

      <ChipGroup
        legend="About how long"
        columns={5}
        options={DURATIONS.map((d) => ({ value: d, label: `${d} min` }))}
        value={setup.minutes}
        onChange={(v) => {
          setOwnTime("");
          update({ minutes: Number(v) });
        }}
      />
      <label className="account-field walks-own-time">
        <span>Or your own time, in minutes (10 to 240)</span>
        <input
          id="walk-own-minutes"
          inputMode="numeric"
          placeholder="e.g. 120"
          value={ownTime}
          onChange={(e) => {
            setOwnTime(e.target.value);
            const n = Number(e.target.value);
            if (Number.isInteger(n) && n >= 10 && n <= 240) update({ minutes: n });
          }}
        />
      </label>

      {dirty && (
        <div className="walks-update">
          <button
            className="btn-primary"
            onClick={() => {
              setApplied(setup);
              setRunToken((t) => t + 1);
            }}
          >
            Update walks
          </button>
          <button className="btn-quiet" onClick={() => update(applied)}>
            Undo changes
          </button>
        </div>
      )}

      {notAdmitted && (
        <Gate
          signedIn={auth.isAuthenticated}
          canSignIn={auth.configured}
          onSignIn={() => void auth.signIn()}
          onOpenSettings={onOpenSettings}
        />
      )}
      {error && <p className="account-error">{error}</p>}
      {busy && !result && <p className="walks-hint">Checking the walks…</p>}

      {result && !notAdmitted && (
        <>
          {applied.profile === "carrier" && result.carried_kg != null && (
            <p className="walks-hint">
              You&rsquo;d be carrying about {result.carried_kg} kg. That&rsquo;s
              your own figures added up, not a judgement - limits depend on your
              carrier model.
            </p>
          )}

          {canGenerate && (
            <MakeWalks
              setup={applied}
              here={here}
              units={units}
              handoff={result.handoff}
              runToken={runToken}
              autoMake={autoMake}
            />
          )}

          {/* Curated walks follow, folded when walks can be made: outside the
              founder's own area there are hardly any yet. */}
          <details className="walks-more walks-curated" open={!canGenerate}>
            <summary>Curated walks</summary>
            <WalkGroups
              walks={result.walks}
              here={here}
              units={units}
              setup={applied}
              handoff={result.handoff}
            />
          </details>

          <section className="walks-guidance">
            {result.guidance.map((g) => (
              <div key={g.title} className="walks-guide">
                <h3>{g.title}</h3>
                <ul>
                  {g.points.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
                {g.url && (
                  <p className="walks-cite">
                    <a href={g.url} target="_blank" rel="noopener noreferrer">
                      {g.source}
                    </a>
                    {g.reviewed ? ` · ${g.reviewed}` : ""}
                  </p>
                )}
              </div>
            ))}
          </section>

          <p className="walks-attrib">
            Map data{" "}
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">
              © OpenStreetMap contributors
            </a>
            . Heights from EU-DEM, produced using Copernicus data and information
            funded by the European Union.
          </p>
        </>
      )}
    </main>
  );
}

/**
 * Why the walks are not showing, and the one action that fixes it - in place,
 * rather than a sentence pointing somewhere else.
 *
 * Two different situations, worded differently, because they need different
 * things: someone signed out needs to sign in; someone signed in without an
 * invitation needs to add one, and signing in again would get them nowhere.
 * Signing in from here returns to this tab - the tab is in the URL hash, and
 * the sign-in flow restores the URL it started from.
 */
function Gate({
  signedIn,
  canSignIn,
  onSignIn,
  onOpenSettings,
}: {
  signedIn: boolean;
  canSignIn: boolean;
  onSignIn: () => void;
  onOpenSettings: () => void;
}) {
  if (signedIn) {
    return (
      <div className="walks-gate">
        <p>
          Walks are part of the closed beta, and your account doesn&rsquo;t
          have an invitation yet.
        </p>
        <button className="btn-primary" onClick={onOpenSettings}>
          Add your invitation
        </button>
      </div>
    );
  }
  return (
    <div className="walks-gate">
      <p>Walks are part of the closed beta. Sign in to try them.</p>
      {canSignIn ? (
        <button className="btn-primary" onClick={onSignIn}>
          Sign in
        </button>
      ) : (
        <p className="walks-hint">Sign-in isn&rsquo;t available on this version.</p>
      )}
    </div>
  );
}

/** Walk preferences, kept on this device. */
function PrefsPanel({
  setup,
  update,
}: {
  setup: WalkSetup;
  update: (patch: Partial<WalkSetup>) => void;
}) {
  return (
    <details className="walks-setup">
      <summary>
        Walk preferences
        <span className="walks-setup-now">
          {[
            setup.maxRetrace >= 1 ? null : setup.maxRetrace > 0.1 ? "little retracing" : "no retracing",
            setup.character === "any" ? null : setup.character === "green" ? "greener" : "quieter",
            setup.allowTravel ? null : "doorstep only",
          ]
            .filter(Boolean)
            .join(" · ") || "all walks"}
        </span>
      </summary>
      <ChipGroup
        legend="Walking the same path twice"
        columns={3}
        options={[
          { value: "1", label: "Don't mind" },
          { value: "0.15", label: "A little", sub: "up to ~15%" },
          { value: "0.05", label: "Avoid" },
        ]}
        value={String(setup.maxRetrace)}
        onChange={(v) => update({ maxRetrace: Number(v) })}
      />
      <p className="walks-hint">
        A shared first and last stretch is common. Anything but "Don't mind"
        also stops a long loop being shortened by turning back.
      </p>
      <ChipGroup
        legend="Kind of walk (for walks made from your start)"
        columns={3}
        options={[
          { value: "any", label: "Any" },
          { value: "green", label: "Greener", sub: "parks, fields" },
          { value: "quiet", label: "Quieter", sub: "less traffic" },
        ]}
        value={setup.character}
        onChange={(v) => update({ character: v as WalkSetup["character"] })}
      />
      <p className="walks-hint">
        Rivers, canals and the seaside can&rsquo;t be chosen yet: the route
        provider doesn&rsquo;t offer them.
      </p>
      <ChipGroup
        legend="Walks that need travel to the start"
        columns={2}
        options={[
          { value: "yes", label: "Show" },
          { value: "no", label: "Hide" },
        ]}
        value={setup.allowTravel ? "yes" : "no"}
        onChange={(v) => update({ allowTravel: v === "yes" })}
      />
      <p className="walks-hint">Saved on this device only.</p>
    </details>
  );
}

/**
 * Pram or carrier details. A top-level component on purpose: defined inside
 * Walks it became a new component type on every render, so React remounted it
 * on each keystroke - the field lost focus and the panel snapped shut.
 */
function SetupPanel({
  setup,
  update,
}: {
  setup: WalkSetup;
  update: (patch: Partial<WalkSetup>) => void;
}) {
  // Nothing to push or carry, so nothing to describe.
  if (setup.profile === "walker") return null;
  if (setup.profile === "pram") {
    const p = setup.pram;
    return (
      <details className="walks-setup">
        <summary>
          Your pram
          <span className="walks-setup-now">
            {p.wheels === "compact" ? "small wheels" : p.wheels === "all_terrain" ? "all-terrain" : "standard wheels"}
            {p.width_cm ? ` · ${p.width_cm} cm wide` : ""}
            {p.double ? " · double" : ""}
          </span>
        </summary>
        <ChipGroup
          legend="Wheels"
          columns={3}
          options={[
            { value: "compact", label: "Small", sub: "city/travel" },
            { value: "standard", label: "Standard" },
            { value: "all_terrain", label: "All-terrain", sub: "air tyres" },
          ]}
          value={p.wheels}
          onChange={(v) => update({ pram: { ...p, wheels: v as typeof p.wheels } })}
        />
        <label className="account-field">
          <span>Width in cm (optional)</span>
          <input
            id="walk-pram-width"
            inputMode="numeric"
            value={p.width_cm ?? ""}
            placeholder="e.g. 60"
            onChange={(e) =>
              update({ pram: { ...p, width_cm: numberOrNull(e.target.value) } })
            }
          />
        </label>
        <label className="walks-check">
          <input
            id="walk-pram-double"
            type="checkbox"
            checked={p.double}
            onChange={(e) => update({ pram: { ...p, double: e.target.checked } })}
          />
          Double pram
        </label>
        <p className="walks-hint">Saved on this device only.</p>
      </details>
    );
  }
  const c = setup.carrier;
  return (
    <details className="walks-setup">
      <summary>
        Your carrier
        <span className="walks-setup-now">
          {c.kind === "framed" ? "framed" : "sling or soft"}
        </span>
      </summary>
      <ChipGroup
        legend="Type"
        columns={2}
        options={[
          { value: "soft", label: "Sling or soft" },
          { value: "framed", label: "Framed" },
        ]}
        value={c.kind}
        onChange={(v) => update({ carrier: { ...c, kind: v as typeof c.kind } })}
      />
      <p className="walks-hint">
        Optional, approximate, and only used to add up what you&rsquo;d carry.
      </p>
      {(
        [
          ["child_kg", "Child, kg"],
          ["carrier_kg", "Carrier, kg"],
          ["luggage_kg", "Bag, kg"],
        ] as const
      ).map(([key, label]) => (
        <label key={key} className="account-field">
          <span>{label}</span>
          <input
            id={`walk-${key}`}
            inputMode="decimal"
            value={c[key] ?? ""}
            onChange={(e) =>
              update({ carrier: { ...c, [key]: numberOrNull(e.target.value) } })
            }
          />
        </label>
      ))}
      <ChipGroup
        legend="Who carries the bag"
        columns={2}
        options={[
          { value: "carrier_adult", label: "Me" },
          { value: "companion", label: "Someone else" },
        ]}
        value={c.luggage_with}
        onChange={(v) =>
          update({ carrier: { ...c, luggage_with: v as typeof c.luggage_with } })
        }
      />
      <p className="walks-hint">Saved on this device only.</p>
    </details>
  );
}

function WalkCard({
  walk,
  units,
  handoff,
  fromKm,
}: {
  walk: Walk;
  units: Units;
  handoff: string;
  /** Set when the walk needs travel to its start: how far away that is. */
  fromKm?: number;
}) {
  const directions =
    `https://www.google.com/maps/dir/?api=1&destination=` +
    `${walk.start.lat},${walk.start.lng}`;

  return (
    <article className={`walk walk-${walk.verdict}`}>
      <header className="walk-head">
        <h3 className="walk-name">{walk.name}</h3>
        <p className="walk-area">{walk.area}</p>
        {fromKm !== undefined && (
          <p className="walk-travel">
            Starts {distance(fromKm * 1000, units)} from you
          </p>
        )}
      </header>

      <p className={`walk-verdict verdict-${walk.verdict}`}>{VERDICT_LABEL[walk.verdict]}</p>

      <dl className="walk-stats">
        <div>
          <dt>Distance</dt>
          <dd>{distance(walk.distance_m, units)}</dd>
        </div>
        <div>
          <dt>Time</dt>
          <dd>~{duration(walk.minutes)}</dd>
        </div>
        <div>
          <dt>Climb</dt>
          {/* "m uphill", not "m": a bare "9 m" under the time was read as
              nine minutes. */}
          <dd>{walk.ascent_m == null ? "not known" : `${walk.ascent_m} m uphill`}</dd>
        </div>
        <div>
          <dt>Shape</dt>
          <dd>{SHAPE_LABEL[walk.path_shape]}</dd>
        </div>
      </dl>

      {(walk.path_shape === "lollipop" || walk.road_share !== null) && (
        <p className="walk-facts">
          {[
            walk.path_shape === "lollipop"
              ? `About ${Math.round(walk.retrace_share * 100)}% walked twice`
              : "",
            walk.road_share !== null
              ? `about ${Math.round(walk.road_share * 100)}% along streets and roads`
              : "",
          ]
            .filter(Boolean)
            .join("; ")
            .replace(/^a/, "A")}
          .
        </p>
      )}

      {fitSentence(walk, units) && (
        <p className={`walk-fit fit-${walk.fit?.kind}`}>{fitSentence(walk, units)}</p>
      )}

      <div
        className="walk-strip"
        role="img"
        aria-label={`Route from start to finish: ${walk.sections
          .map((s) => `${s.label}, ${VERDICT_LABEL[s.verdict].toLowerCase()}`)
          .join("; ")}`}
      >
        {walk.sections.map((s, i) => (
          <span
            key={i}
            className={`strip-${s.verdict}`}
            style={{ flexGrow: Math.max(1, s.to_m - s.from_m) }}
            title={`${s.label}: ${s.surface} (${BASIS_LABEL[s.surface_basis]})`}
          />
        ))}
      </div>
      <p className="walk-strip-legend">
        {/* The strip draws every leg walked, so on a there-and-back walk the
            turn is in the middle and the far end is the start again. */}
        <span>Start</span>
        {walk.shape === "out_and_back" && <span>Turn back</span>}
        <span>{walk.shape === "one_way" ? "Arrive" : "Back at start"}</span>
      </p>

      <p className="walk-summary">{walk.summary}</p>

      <Findings title="Stops you" items={walk.blocking} units={units} tone="blocked" />
      <Findings title="Harder going" items={walk.difficult} units={units} tone="difficult" />
      <Findings title="Not recorded" items={walk.unknowns} units={units} tone="unknown" />
      <Findings title="Worth knowing" items={walk.notes} units={units} tone="note" />

      <p className="walk-coverage">
        Surface known for {Math.round(walk.coverage.surface_known_share * 100)}% of
        the way
        {walk.coverage.surface_reported_share > 0
          ? `, ${Math.round(walk.coverage.surface_reported_share * 100)}% checked on foot`
          : ", none of it checked on foot yet"}
        . {walk.assumptions}
      </p>

      {walk.notes_from_curator.length > 0 && (
        <ul className="walk-curator">
          {walk.notes_from_curator.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}

      <WalkMapLazy walk={walk} />

      <div className="walk-links">
        <a className="btn-quiet walk-go" href={directions} target="_blank" rel="noopener noreferrer">
          Directions to the start · {walk.start.label}
        </a>
        <a className="btn-quiet walk-go" href={checkpointsUrl(walk)} target="_blank" rel="noopener noreferrer">
          Walk it in Google Maps, via 3 checkpoints
        </a>
      </div>
      <p className="walk-handoff">
        {handoff} With checkpoints it keeps closer to this walk, but between them
        it still picks its own way. Where they differ, follow the map above.
      </p>
    </article>
  );
}

/**
 * The map, only once its section is opened: a Leaflet map per card on load
 * would fetch map images for walks nobody looked at.
 */
function WalkMapLazy({ walk }: { walk: Walk }) {
  const [open, setOpen] = useState(false);
  return (
    <details className="walk-map-box" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>Show on map</summary>
      {open && <WalkMap walk={walk} />}
    </details>
  );
}

/**
 * A Google Maps walking link through three points of the walk - the most its
 * links accept on a phone (developers.google.com/maps/documentation/urls,
 * checked 9 Oct 2026). Origin is left out so it starts from wherever you are.
 */
function checkpointsUrl(walk: Walk): string {
  const outward =
    walk.shape === "out_and_back"
      ? walk.sections.filter((s) => s.to_m <= walk.distance_m / 2 + 1)
      : walk.sections;
  const line = outward.flatMap((s) => s.geometry);
  if (line.length === 0) return "https://www.google.com/maps";
  const pick = (share: number) =>
    line[Math.min(line.length - 1, Math.round(share * (line.length - 1)))];
  const points =
    walk.shape === "out_and_back"
      ? [pick(1 / 3), pick(2 / 3), pick(1)] // the last is the turning point
      : [pick(0.25), pick(0.5), pick(0.75)];
  const dest: [number, number] =
    walk.shape === "one_way" ? line[line.length - 1] : [walk.start.lat, walk.start.lng];
  const fmt = (p: [number, number]) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`;
  return (
    "https://www.google.com/maps/dir/?api=1&travelmode=walking" +
    `&destination=${fmt(dest)}` +
    `&waypoints=${encodeURIComponent(points.map(fmt).join("|"))}`
  );
}

/**
 * The walks, grouped by what you would have to do to start them.
 *
 * Founder feedback, 9 Oct: walks needing a drive to the start must be clearly
 * apart from ones that start at your doorstep; there-and-back walks and walks
 * needing travel can each be switched off; nothing more than about an hour's
 * drive away is shown. Walks a preference hides are counted, not dropped
 * silently. Grouping happens on the device; your position is not sent for it.
 */
function WalkGroups({
  walks,
  here,
  units,
  setup,
  handoff,
}: {
  walks: Walk[];
  here: Coord | null;
  units: Units;
  setup: WalkSetup;
  handoff: string;
}) {
  const g = groupWalks(walks, here, setup);
  const minutes = setup.minutes;
  const card = (w: Walk, km?: number) => (
    <WalkCard key={w.id} walk={w} units={units} handoff={handoff} fromKm={km} />
  );
  const hiddenNote = [
    g.hidden.outAndBack
      ? `${g.hidden.outAndBack} walk${g.hidden.outAndBack > 1 ? "s" : ""} going over the same path more than you'd like`
      : "",
    g.hidden.travel
      ? `${g.hidden.travel} walk${g.hidden.travel > 1 ? "s" : ""} needing travel to the start`
      : "",
  ].filter(Boolean);

  return (
    <>
      <h3 className="walks-group-title">
        {g.located ? "From your doorstep" : "Curated walks"}
      </h3>
      {!g.located && (
        <p className="walks-hint">Turn on location to see which walks start near you.</p>
      )}
      {g.doorstep.length === 0 ? (
        <p className="walks-hint">
          None of the curated walks starts near you and fits {duration(minutes)}.
        </p>
      ) : (
        <div className="walks-list">{g.doorstep.map((w) => card(w))}</div>
      )}

      {g.travel.length > 0 && (
        <>
          <h3 className="walks-group-title">Needs travel to the start</h3>
          <div className="walks-list">{g.travel.map((t) => card(t.walk, t.km))}</div>
        </>
      )}

      {g.other.length > 0 && (
        <details className="walks-more">
          <summary>
            {g.other.length} more, shorter or longer than {duration(minutes)}
          </summary>
          <div className="walks-list">{g.other.map((w) => card(w))}</div>
        </details>
      )}

      {hiddenNote.length > 0 && (
        <p className="walks-hint">
          Hidden by your preferences: {hiddenNote.join(" and ")}.
        </p>
      )}
    </>
  );
}

/**
 * Make walks from a start you choose - where you are, or anywhere you search.
 *
 * Founder testing showed curated walks starting at fixed public places are the
 * wrong shape for real use: a tester walked eight minutes to the start of her
 * own regular route. Generated loops start where you are.
 */
function MakeWalks({
  setup,
  here,
  units,
  handoff,
  runToken,
  autoMake,
}: {
  setup: WalkSetup;
  here: Coord | null;
  units: Units;
  handoff: string;
  /** Bumped by "Update walks": walks already made are made again. */
  runToken: number;
  /** No curated walk fits here: make walks without waiting to be asked. */
  autoMake: boolean;
}) {
  const [start, setStart] = useState<Endpoint | null>(
    here ? { coord: here, label: "Your location", source: "current" } : null,
  );
  const [via, setVia] = useState<Endpoint | null>(null);
  const [made, setMade] = useState<GeneratedWalks | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const autoTried = useRef(false);

  // Location usually arrives after the screen opens. Use it then - unless a
  // place has already been chosen, which it must not overwrite.
  useEffect(() => {
    if (here && !start) setStart({ coord: here, label: "Your location", source: "current" });
  }, [here, start]);

  async function make() {
    if (!start) return;
    setBusy(true);
    setError(null);
    try {
      setMade(
        await generateWalks({
          profile: setup.profile,
          minutes: setup.minutes,
          allow_out_and_back: setup.maxRetrace >= 0.5,
          character: setup.character,
          ...(via ? { via: via.coord, via_label: via.label } : {}),
          start: start.coord,
          start_label: start.label,
          ...(setup.profile === "pram"
            ? { pram: setup.pram }
            : setup.profile === "carrier"
              ? { carrier: setup.carrier }
              : {}),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't make walks just now.");
    } finally {
      setBusy(false);
    }
  }

  // "Update walks": walks on screen were made with the old settings, so make
  // them again with the new ones, from the same start and checkpoint.
  useEffect(() => {
    if (runToken > 0 && made && start) void make();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runToken]);

  // Nothing curated fits here: make walks once, without waiting to be asked.
  useEffect(() => {
    if (autoMake && start && !made && !busy && !autoTried.current) {
      autoTried.current = true;
      void make();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoMake, start]);

  return (
    <section className="walks-make">
      <PlaceSearch
        legend="Start from"
        value={start}
        onChange={setStart}
        near={here}
        onUseCurrentLocation={
          here
            ? () => setStart({ coord: here, label: "Your location", source: "current" })
            : undefined
        }
        currentLocationLabel="Where I am"
        placeholder="Where I am, or search a place"
      />
      <PlaceSearch
        legend="Via (optional)"
        value={via}
        onChange={setVia}
        near={start?.coord ?? here}
        placeholder="A place to walk through"
      />
      <button className="btn-primary" disabled={!start || busy} onClick={() => void make()}>
        {busy
          ? "Making walks…"
          : via
            ? `Make a walk via ${via.label}`
            : `Make walks of about ${duration(setup.minutes)}`}
      </button>
      <p className="walks-hint">
        {via
          ? "Out to your checkpoint and back a different way where one exists; its length follows from where the checkpoint is."
          : "Up to three walks from mapped paths, judged for your setup."}{" "}
        To plan them, your start{via ? " and checkpoint are" : " is"} sent to
        openrouteservice; nothing is stored.
      </p>
      {error && <p className="account-error">{error}</p>}
      {made && (
        <>
          <h3 className="walks-group-title">From {start?.label ?? "your start"}</h3>
          <div className="walks-list">
            {made.walks
              .filter((w) => w.retrace_share <= setup.maxRetrace + 0.02)
              .map((w) => (
                <WalkCard key={w.id} walk={w} units={units} handoff={handoff} />
              ))}
          </div>
          {made.walks.some((w) => w.retrace_share > setup.maxRetrace + 0.02) && (
            <p className="walks-hint">
              Hidden by your preferences:{" "}
              {made.walks.filter((w) => w.retrace_share > setup.maxRetrace + 0.02).length}{" "}
              that went over the same path more than you&rsquo;d like.
            </p>
          )}
          <p className="walks-attrib">{made.attribution}</p>
        </>
      )}
    </section>
  );
}

function Findings({
  title,
  items,
  units,
  tone,
}: {
  title: string;
  items: WalkFinding[];
  units: Units;
  tone: "blocked" | "difficult" | "unknown" | "note";
}) {
  if (items.length === 0) return null;
  return (
    <section className={`walk-findings findings-${tone}`}>
      <h4>{title}</h4>
      <ul>
        {items.map((f, i) => (
          <li key={i}>
            <span className="finding-reason">{f.reason}</span>
            <span className="finding-meta">
              {[at(f.at_m, units), BASIS_LABEL[f.basis]].filter(Boolean).join(" · ")}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
