import { useEffect, useState } from "react";
import { ChipGroup } from "../components/ChipGroup";
import type { Units } from "../hooks/useSettings";
import {
  NotAdmitted,
  assessWalks,
  type Basis,
  type Verdict,
  type Walk,
  type WalkFinding,
  type WalksResponse,
} from "./api";
import { useWalkSetup, type WalkSetup } from "./useWalkSetup";
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

const DURATIONS = [20, 30, 45, 60];

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

const SHAPE_LABEL: Record<Walk["shape"], string> = {
  loop: "Loop",
  out_and_back: "There and back",
  one_way: "One way",
};

function numberOrNull(raw: string): number | null {
  const n = Number(raw.replace(",", "."));
  return raw.trim() === "" || Number.isNaN(n) ? null : n;
}

export function Walks({
  units,
  onOpenSettings,
}: {
  units: Units;
  onOpenSettings: () => void;
}) {
  const { setup, update } = useWalkSetup();
  const auth = useDriftwayAuth();
  const [result, setResult] = useState<WalksResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notAdmitted, setNotAdmitted] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Re-assess whenever the setup changes, after a short pause so that typing
  // "12.5" into a weight field is one request rather than four. `alive` drops
  // any answer that arrives after a newer setup has replaced the one it was for.
  useEffect(() => {
    let alive = true;
    const timer = window.setTimeout(() => {
      setBusy(true);
      setError(null);
      assessWalks({
        profile: setup.profile,
        minutes: setup.minutes,
        ...(setup.profile === "pram" ? { pram: setup.pram } : { carrier: setup.carrier }),
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
  }, [setup]);

  return (
    <main className="walks">
      <header className="walks-head">
        <h2 className="walks-title">
          Walks <span className="walks-badge">Experiment</span>
        </h2>
        <p className="walks-sub">
          A few curated walks, checked against your pram or carrier. What&rsquo;s
          known is shown with where it comes from; what isn&rsquo;t, is said.
        </p>
      </header>

      <ChipGroup
        legend="Going with"
        columns={2}
        options={[
          { value: "pram", label: "Pram" },
          { value: "carrier", label: "Carrier" },
        ]}
        value={setup.profile}
        onChange={(v) => update({ profile: v as "pram" | "carrier" })}
      />

      <SetupPanel setup={setup} update={update} />

      <ChipGroup
        legend="About how long"
        columns={4}
        options={DURATIONS.map((d) => ({ value: d, label: `${d} min` }))}
        value={setup.minutes}
        onChange={(v) => update({ minutes: Number(v) })}
      />

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
          {setup.profile === "carrier" && result.carried_kg != null && (
            <p className="walks-hint">
              You&rsquo;d be carrying about {result.carried_kg} kg. That&rsquo;s
              your own figures added up, not a judgement - limits depend on your
              carrier model.
            </p>
          )}

          <div className="walks-list">
            {result.walks.map((w) => (
              <WalkCard key={w.id} walk={w} units={units} handoff={result.handoff} />
            ))}
          </div>

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

function WalkCard({ walk, units, handoff }: { walk: Walk; units: Units; handoff: string }) {
  const directions =
    `https://www.google.com/maps/dir/?api=1&destination=` +
    `${walk.start.lat},${walk.start.lng}`;

  return (
    <article className={`walk walk-${walk.verdict}`}>
      <header className="walk-head">
        <h3 className="walk-name">{walk.name}</h3>
        <p className="walk-area">{walk.area}</p>
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
          <dd>{walk.ascent_m == null ? "not known" : `${walk.ascent_m} m`}</dd>
        </div>
        <div>
          <dt>Shape</dt>
          <dd>{SHAPE_LABEL[walk.shape]}</dd>
        </div>
      </dl>

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

      <a className="btn-quiet walk-go" href={directions} target="_blank" rel="noopener noreferrer">
        Directions to the start · {walk.start.label}
      </a>
      <p className="walk-handoff">{handoff}</p>
    </article>
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
