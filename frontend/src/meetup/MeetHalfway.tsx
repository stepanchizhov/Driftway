import { useCallback, useEffect, useState } from "react";
import type { Coord, Place } from "../types";
import { PlaceSearch } from "../components/PlaceSearch";
import type { Endpoint } from "../components/PlaceSearch";
import {
  MeetupError,
  addVenue,
  castVote,
  createMeetup,
  generateCandidates,
  joinMeetup,
  readMeetup,
  readResults,
  removeVenue,
  selectVenue,
  clearSelection,
} from "./api";
import type { MeetupView, Prefs, VoteValue } from "./api";
import { CandidateCard } from "./CandidateCard";
import { SelectedVenue } from "./SelectedVenue";

/**
 * Meet Halfway: two parents, private starting points, one agreed venue.
 *
 * Which screen shows is decided by what is in the URL, because the whole
 * feature travels by link. There is no router in this app, so the query string
 * is read once on mount:
 *
 *   ?meetup=<id>&join=<token>   a participant's own view (organiser or invitee)
 *   ?results=<slug>             read-only, no identity, everything coarse
 *   (nothing)                   the create screen
 */

type Screen =
  | { name: "create" }
  | { name: "participant"; meetupId: string; joinToken: string }
  | { name: "results"; slug: string };

function screenFromUrl(): Screen {
  const q = new URLSearchParams(window.location.search);
  const meetupId = q.get("meetup");
  const joinToken = q.get("join");
  const results = q.get("results");
  if (meetupId && joinToken) return { name: "participant", meetupId, joinToken };
  if (results) return { name: "results", slug: results };
  return { name: "create" };
}

function linkFor(params: Record<string, string>): string {
  const url = new URL(window.location.href);
  url.search = new URLSearchParams(params).toString();
  return url.toString();
}

interface Props {
  currentLocation: Coord | null;
  home: Endpoint | null;
  onExit: () => void;
}

export function MeetHalfway({ currentLocation, home, onExit }: Props) {
  const [screen] = useState<Screen>(screenFromUrl);
  const [view, setView] = useState<MeetupView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Held only for the organiser, only for this session: the two links they
  // need to hand out. They are capabilities, so they are never stored.
  const [invite, setInvite] = useState<{ join: string; results: string } | null>(
    null,
  );

  const run = useCallback(async (task: () => Promise<MeetupView>) => {
    setBusy(true);
    setError(null);
    try {
      setView(await task());
    } catch (e) {
      setError(e instanceof MeetupError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (screen.name === "participant") {
      void run(() => readMeetup(screen.meetupId, screen.joinToken));
    } else if (screen.name === "results") {
      void run(() => readResults(screen.slug));
    }
  }, [screen, run]);

  return (
    <main className="mh">
      <header className="mh-head">
        <div>
          <h1 className="mh-title">Meet halfway</h1>
          <p className="mh-sub">
            Find somewhere that works for both of you, without swapping
            addresses.
          </p>
        </div>
        <button className="btn-quiet" onClick={onExit}>
          ← Driving
        </button>
      </header>

      {error && <p className="mh-error">{error}</p>}

      {screen.name === "create" && (
        <CreateScreen
          currentLocation={currentLocation}
          home={home}
          busy={busy}
          onCreated={(made) => {
            setInvite({
              join: linkFor({ meetup: made.meetup_id, join: made.participant_invite_token }),
              results: linkFor({ results: made.results_slug }),
            });
            // Move into the organiser's own participant view, keeping the URL
            // shareable and reload-safe.
            const url = linkFor({ meetup: made.meetup_id, join: made.your_join_token });
            window.history.replaceState(null, "", url);
            void run(() => readMeetup(made.meetup_id, made.your_join_token));
          }}
          onError={setError}
        />
      )}

      {invite && <InviteLinks invite={invite} />}

      {screen.name === "participant" && view && (
        <ParticipantScreen
          view={view}
          busy={busy}
          currentLocation={currentLocation}
          home={home}
          onJoin={(input) =>
            run(() => joinMeetup(screen.meetupId, screen.joinToken, input))
          }
          onAddVenue={(place) =>
            run(() => addVenue(screen.meetupId, screen.joinToken, place))
          }
          onRemoveVenue={(id) =>
            run(() => removeVenue(screen.meetupId, screen.joinToken, id))
          }
          onGenerate={() =>
            run(() => generateCandidates(screen.meetupId, screen.joinToken))
          }
          onVote={(candidateId, value) =>
            run(() => castVote(screen.meetupId, screen.joinToken, candidateId, value))
          }
          onSelect={(candidateId) =>
            run(() => selectVenue(screen.meetupId, screen.joinToken, candidateId))
          }
          onClearSelection={() =>
            run(() => clearSelection(screen.meetupId, screen.joinToken))
          }
        />
      )}

      {screen.name === "results" && view && (
        <>
          <p className="mh-readonly">
            Shared results. You can see how far each place is for everyone, but
            not change anything.
          </p>
          <Results view={view} onVote={null} onRemove={null} />
        </>
      )}
    </main>
  );
}

// --------------------------------------------------------------- create

function CreateScreen({
  currentLocation,
  home,
  busy,
  onCreated,
  onError,
}: {
  currentLocation: Coord | null;
  home: Endpoint | null;
  busy: boolean;
  onCreated: (made: Awaited<ReturnType<typeof createMeetup>>) => void;
  onError: (message: string) => void;
}) {
  const [start, setStart] = useState<Endpoint | null>(null);
  const [hide, setHide] = useState(true);
  const [name, setName] = useState("");
  const [when, setWhen] = useState("");
  const [prefs, setPrefs] = useState<Prefs>({ tolerance_minutes: 10 });
  const [working, setWorking] = useState(false);

  const coord = start?.coord ?? currentLocation;

  async function submit() {
    if (!coord) return;
    setWorking(true);
    try {
      onCreated(
        await createMeetup({
          scheduled_at: when ? new Date(when).toISOString() : null,
          start: coord,
          hide_exact_origin: hide,
          display_name: name || undefined,
          prefs,
        }),
      );
    } catch (e) {
      onError(e instanceof MeetupError ? e.message : "Couldn't create the meetup.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="mh-card">
      <h2 className="mh-h2">Set one up</h2>

      <label className="mh-field">
        <span className="mh-label">Your name</span>
        <input
          className="mh-input"
          value={name}
          placeholder="So the other parent knows who's who"
          onChange={(e) => setName(e.target.value)}
        />
      </label>

      <label className="mh-field">
        <span className="mh-label">When (optional)</span>
        <input
          className="mh-input"
          type="datetime-local"
          value={when}
          onChange={(e) => setWhen(e.target.value)}
        />
      </label>

      <PlaceSearch
        legend="You're setting off from"
        value={start ?? (currentLocation ? { coord: currentLocation, label: "Your location", source: "current" } : null)}
        onChange={setStart}
        near={currentLocation}
        onUseCurrentLocation={currentLocation ? () => setStart(null) : undefined}
        currentLocationLabel="Use my location"
        home={home}
        placeholder="Search a starting point"
      />

      <PrivacyToggle hide={hide} onChange={setHide} />
      <DrivePrefs prefs={prefs} onChange={setPrefs} />

      <button
        className="btn-generate"
        disabled={!coord || working || busy}
        onClick={() => void submit()}
      >
        {working ? "Creating…" : "Create and get an invite link"}
      </button>
    </section>
  );
}

function InviteLinks({ invite }: { invite: { join: string; results: string } }) {
  return (
    <section className="mh-card mh-links">
      <h2 className="mh-h2">Two different links</h2>
      <LinkRow
        title="Invite parent to this meetup"
        hint="Lets them add where they're setting off from, suggest places and vote."
        value={invite.join}
      />
      <LinkRow
        title="Share results"
        hint="Read-only. No one can change anything with this."
        value={invite.results}
      />
    </section>
  );
}

function LinkRow({ title, hint, value }: { title: string; hint: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mh-link">
      <div className="mh-link-text">
        <span className="mh-link-title">{title}</span>
        <span className="mh-link-hint">{hint}</span>
        <code className="mh-link-url">{value}</code>
      </div>
      <button
        className="btn-quiet"
        onClick={() => {
          void navigator.clipboard?.writeText(value).then(
            () => {
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            },
            () => undefined,
          );
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------- participant

function ParticipantScreen({
  view,
  busy,
  currentLocation,
  home,
  onJoin,
  onAddVenue,
  onRemoveVenue,
  onGenerate,
  onVote,
  onSelect,
  onClearSelection,
}: {
  view: MeetupView;
  busy: boolean;
  currentLocation: Coord | null;
  home: Endpoint | null;
  onJoin: (input: {
    start: Coord;
    hide_exact_origin: boolean;
    display_name?: string;
    prefs: Prefs;
  }) => void;
  onAddVenue: (place: Place) => void;
  onRemoveVenue: (id: string) => void;
  onGenerate: () => void;
  onVote: (candidateId: string, value: VoteValue) => void;
  onSelect: (candidateId: string) => void;
  onClearSelection: () => void;
}) {
  const you = view.participants.find((p) => p.is_you);
  // The placeholder participant created for the invitee starts at 0,0 and has
  // no coordinate yet: that is what "hasn't joined" looks like.
  const youHaveJoined = Boolean(
    you?.display_coord && (you.display_coord.lat !== 0 || you.display_coord.lng !== 0),
  );
  const others = view.participants.filter((p) => !p.is_you);
  const othersReady = others.filter(
    (p) => p.display_coord && (p.display_coord.lat !== 0 || p.display_coord.lng !== 0),
  );

  if (!youHaveJoined) {
    return (
      <JoinScreen
        currentLocation={currentLocation}
        home={home}
        busy={busy}
        onJoin={onJoin}
      />
    );
  }

  const yourVenues = view.candidates.filter((c) => c.added_by_you).length;
  const chosen = view.selected_venue_id
    ? view.candidates.find((c) => c.id === view.selected_venue_id)
    : undefined;
  const isOrganiser = Boolean(view.results_url_slug);

  // A decided meetup is about getting there, not comparing options any more.
  if (chosen) {
    return (
      <SelectedVenue
        view={view}
        venue={chosen}
        yourOrigin={you?.origin_precision === "exact" ? you.display_coord : null}
        canChange={isOrganiser}
        onChange={onClearSelection}
      />
    );
  }

  return (
    <>
      <section className="mh-card">
        <h2 className="mh-h2">Who's coming</h2>
        <ul className="mh-people">
          {view.participants.map((p) => (
            <li key={p.id} className="mh-person">
              <span className="mh-person-name">
                {p.is_you ? "You" : p.display_name || "The other parent"}
              </span>
              <span className="mh-person-where">
                {p.display_coord && (p.display_coord.lat !== 0 || p.display_coord.lng !== 0)
                  ? p.origin_precision === "exact"
                    ? "sharing exact location"
                    : "somewhere private"
                  : "hasn't said where yet"}
              </span>
            </li>
          ))}
        </ul>
        {othersReady.length === 0 && (
          <p className="mh-hint">
            Send them the invite link. Once they say where they're setting off
            from, you'll both see how far each place is.
          </p>
        )}
      </section>

      <section className="mh-card">
        <h2 className="mh-h2">Places you'd both consider</h2>
        <p className="mh-hint">
          Add somewhere you already know works for your children. You'll each
          see how long it takes from where you are.
        </p>

        <VenueAdder
          near={currentLocation}
          onAdd={onAddVenue}
          disabled={busy}
        />

        {/* The nudge for the parent who hasn't contributed. One person doing
            all the adding is the likely failure mode of a shared pool. */}
        {view.candidates.length > 0 && yourVenues === 0 && (
          <p className="mh-nudge">
            All of these were suggested by someone else. Add one you like too —
            it's easier to agree with two lists than one.
          </p>
        )}

        <button
          className="btn-generate"
          disabled={busy || view.candidates.length === 0 || othersReady.length === 0}
          onClick={onGenerate}
        >
          {busy ? "Working it out…" : "Compare travel times"}
        </button>
      </section>

      {view.notice && (
        <p className={`mh-notice${view.no_fit ? " mh-notice-warn" : ""}`}>
          {view.notice}
        </p>
      )}

      <Results
        view={view}
        onVote={onVote}
        onRemove={onRemoveVenue}
        onSelect={isOrganiser ? onSelect : null}
      />
    </>
  );
}

function JoinScreen({
  currentLocation,
  home,
  busy,
  onJoin,
}: {
  currentLocation: Coord | null;
  home: Endpoint | null;
  busy: boolean;
  onJoin: (input: {
    start: Coord;
    hide_exact_origin: boolean;
    display_name?: string;
    prefs: Prefs;
  }) => void;
}) {
  const [start, setStart] = useState<Endpoint | null>(null);
  const [hide, setHide] = useState(true);
  const [name, setName] = useState("");
  const [prefs, setPrefs] = useState<Prefs>({ tolerance_minutes: 10 });
  const coord = start?.coord ?? currentLocation;

  return (
    <section className="mh-card">
      <h2 className="mh-h2">Join this meetup</h2>
      <p className="mh-hint">
        No account needed. Your starting point is used to work out travel times
        and is never shown to anyone else unless you choose to share it.
      </p>

      <label className="mh-field">
        <span className="mh-label">Your name</span>
        <input
          className="mh-input"
          value={name}
          placeholder="So they know who's who"
          onChange={(e) => setName(e.target.value)}
        />
      </label>

      <PlaceSearch
        legend="You're setting off from"
        value={start ?? (currentLocation ? { coord: currentLocation, label: "Your location", source: "current" } : null)}
        onChange={setStart}
        near={currentLocation}
        onUseCurrentLocation={currentLocation ? () => setStart(null) : undefined}
        currentLocationLabel="Use my location"
        home={home}
        placeholder="Search a starting point"
      />

      <PrivacyToggle hide={hide} onChange={setHide} />
      <DrivePrefs prefs={prefs} onChange={setPrefs} />

      <button
        className="btn-generate"
        disabled={!coord || busy}
        onClick={() =>
          coord &&
          onJoin({
            start: coord,
            hide_exact_origin: hide,
            display_name: name || undefined,
            prefs,
          })
        }
      >
        {busy ? "Joining…" : "Join"}
      </button>
    </section>
  );
}

// -------------------------------------------------------------- shared bits

function PrivacyToggle({
  hide,
  onChange,
}: {
  hide: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="mh-check">
      <input
        type="checkbox"
        checked={hide}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <span className="mh-check-label">
          Hide my exact starting location from the other parent
        </span>
        <span className="mh-check-hint">
          They'll see the area you're coming from, not your address. Travel
          times are worked out from your real location either way.
        </span>
      </span>
    </label>
  );
}

function DrivePrefs({
  prefs,
  onChange,
}: {
  prefs: Prefs;
  onChange: (p: Prefs) => void;
}) {
  return (
    <div className="mh-prefs">
      <label className="mh-field mh-field-sm">
        <span className="mh-label">Ideal drive (min)</span>
        <input
          className="mh-input"
          type="number"
          min={1}
          max={240}
          value={prefs.preferred_minutes ?? ""}
          placeholder="any"
          onChange={(e) =>
            onChange({
              ...prefs,
              preferred_minutes: e.target.value ? Number(e.target.value) : null,
            })
          }
        />
      </label>
      <label className="mh-field mh-field-sm">
        <span className="mh-label">Most I'd drive (min)</span>
        <input
          className="mh-input"
          type="number"
          min={1}
          max={240}
          value={prefs.max_minutes ?? ""}
          placeholder="no limit"
          onChange={(e) =>
            onChange({
              ...prefs,
              max_minutes: e.target.value ? Number(e.target.value) : null,
            })
          }
        />
      </label>
    </div>
  );
}

function VenueAdder({
  near,
  onAdd,
  disabled,
}: {
  near: Coord | null;
  onAdd: (place: Place) => void;
  disabled: boolean;
}) {
  // Reuses the same picker as the route planner, so a venue is always a
  // resolved place rather than typed text.
  const [key, setKey] = useState(0);
  return (
    <div className={disabled ? "mh-adder mh-adder-off" : "mh-adder"}>
      <PlaceSearch
        key={key}
        legend="Add a place"
        value={null}
        onChange={(endpoint) => {
          if (!endpoint) return;
          onAdd({
            id: `${endpoint.coord.lat},${endpoint.coord.lng}`,
            label: endpoint.label,
            detail: endpoint.detail ?? "",
            coord: endpoint.coord,
            kind: "poi",
            approximate: endpoint.approximate ?? false,
          });
          setKey((k) => k + 1); // reset the field for the next one
        }}
        near={near}
        placeholder="Search a soft play, park, cafe…"
      />
    </div>
  );
}

function Results({
  view,
  onVote,
  onRemove,
  onSelect = null,
}: {
  view: MeetupView;
  onVote: ((candidateId: string, value: VoteValue) => void) | null;
  onRemove: ((id: string) => void) | null;
  onSelect?: ((candidateId: string) => void) | null;
}) {
  if (view.candidates.length === 0) return null;
  const names = new Map(
    view.participants.map((p) => [
      p.id,
      p.is_you ? "You" : p.display_name || "Them",
    ]),
  );
  return (
    <section className="mh-results">
      {view.candidates.map((c, i) => (
        <CandidateCard
          key={c.id}
          candidate={c}
          rank={i + 1}
          names={names}
          onVote={onVote}
          onRemove={onRemove}
          onSelect={onSelect}
        />
      ))}
    </section>
  );
}
