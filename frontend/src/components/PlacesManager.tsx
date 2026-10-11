import { useState } from "react";
import type { Coord } from "../types";
import type { Place } from "../lib/places";
import { LABEL_MAX } from "../lib/places";
import type { PlaceChange, PlaceStore } from "../hooks/usePlaces";
import { PlaceSearch, type Endpoint } from "./PlaceSearch";

type Change = (op:
  | { type: "add"; label: string; coord: Coord; detail?: string; makeHome?: boolean }
  | { type: "rename"; id: string; label: string }
  | { type: "move"; id: string; coord: Coord; detail?: string }
  | { type: "remove"; id: string }
  | { type: "setHome"; id: string }) => PlaceChange;

/**
 * Saved places: add, rename, move, make Home, remove (11 Oct 2026).
 *
 * Saving a place only keeps it: nothing is routed and nothing opens. Every
 * change says whether it was kept on this device, and removing Home says
 * that there will be no Home until one is chosen.
 */
export function PlacesManager({
  places,
  store,
  change,
  here,
}: {
  places: Place[];
  store: PlaceStore;
  change: Change;
  /** The phone's position, when known: "Use my location" when adding. */
  here: Coord | null;
}) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const hasHome = places.some((p) => p.isDefault);

  function report(result: PlaceChange, done: string): boolean {
    if (!result.ok) {
      setStatus({ ok: false, text: result.message });
      return false;
    }
    setStatus(
      result.persisted
        ? { ok: true, text: `${done} on this device.` }
        : {
            ok: false,
            text: `${done} for this visit only: this browser isn't keeping data just now, so it will be gone when Driftway closes.`,
          },
    );
    return true;
  }

  // Home first, then in the order saved.
  const ordered = [...places].sort((a, b) => Number(b.isDefault) - Number(a.isDefault));

  return (
    <section className="places" aria-labelledby="places-title">
      <h2 className="favs-title" id="places-title">
        Places
      </h2>
      <p className="places-note">
        Home and anywhere else you go often: the pool, nursery, grandparents.
        They appear in Still asleep and as one-tap choices wherever you search
        for a place. Kept on this phone, at this web address only: not in your
        account, so they don&rsquo;t appear on another phone or in Driftway
        Next.
      </p>

      {store === "unreadable" && (
        <p className="account-error">
          The places saved on this phone couldn&rsquo;t be read. Saving a place
          starts a new list.
        </p>
      )}
      {store === "unavailable" && !status && (
        <p className="account-error">
          This browser isn&rsquo;t keeping data just now, so places last only
          until Driftway closes.
        </p>
      )}

      {places.length === 0 && !adding && (
        <p className="favs-empty">No places yet.</p>
      )}
      {places.length > 0 && !hasHome && (
        <p className="places-note">
          No Home is set. Choose &ldquo;Make Home&rdquo; on a place, or add one.
        </p>
      )}

      <ul className="places-list">
        {ordered.map((p) => (
          <li key={p.id} className="place-row">
            {editing === p.id ? (
              <PlaceForm
                title={`Edit ${p.label}`}
                initialName={p.label}
                initial={{ coord: { lat: p.lat, lng: p.lng }, label: p.detail ?? "Saved position", source: "saved" }}
                here={here}
                onCancel={() => setEditing(null)}
                onSave={(name, at) => {
                  const renamed = change({ type: "rename", id: p.id, label: name });
                  if (!renamed.ok) return report(renamed, "");
                  const moved =
                    at.coord.lat !== p.lat || at.coord.lng !== p.lng
                      ? change({ type: "move", id: p.id, coord: at.coord, detail: addressOf(at) })
                      : renamed;
                  if (report(moved, "Saved")) setEditing(null);
                  return true;
                }}
              />
            ) : (
              <>
                <div className="place-main">
                  <span className="place-label">{p.label}</span>
                  {p.isDefault && p.label !== "Home" && <span className="place-home">Home</span>}
                  {p.detail && <span className="place-detail">{p.detail}</span>}
                </div>
                {removing === p.id ? (
                  <div className="place-confirm">
                    <p>
                      {p.isDefault
                        ? `Remove ${p.label}? Driftway won't have a Home until you choose one.`
                        : `Remove ${p.label}?`}
                    </p>
                    <div className="place-actions">
                      <button
                        className="btn-quiet"
                        onClick={() => {
                          report(change({ type: "remove", id: p.id }), "Removed");
                          setRemoving(null);
                        }}
                      >
                        Remove
                      </button>
                      <button className="btn-quiet" onClick={() => setRemoving(null)}>
                        Keep it
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="place-actions">
                    <button className="btn-quiet" onClick={() => { setEditing(p.id); setStatus(null); }}>
                      Edit
                    </button>
                    {!p.isDefault && (
                      <button
                        className="btn-quiet"
                        onClick={() => report(change({ type: "setHome", id: p.id }), `Made ${p.label} Home`)}
                      >
                        Make Home
                      </button>
                    )}
                    <button className="btn-quiet" onClick={() => { setRemoving(p.id); setStatus(null); }}>
                      Remove
                    </button>
                  </div>
                )}
              </>
            )}
          </li>
        ))}
      </ul>

      {adding ? (
        <PlaceForm
          title="Add a place"
          initialName={hasHome ? "" : "Home"}
          initial={null}
          here={here}
          offerHome={!hasHome}
          onCancel={() => setAdding(false)}
          onSave={(name, at, makeHome) => {
            const ok = report(
              change({ type: "add", label: name, coord: at.coord, detail: addressOf(at), makeHome }),
              "Saved",
            );
            if (ok) setAdding(false);
            return ok;
          }}
        />
      ) : (
        <button
          className="btn-quiet places-add"
          onClick={() => {
            setAdding(true);
            setEditing(null);
            setStatus(null);
          }}
        >
          Add a place
        </button>
      )}

      {status && (
        <p className={status.ok ? "places-ok" : "account-error"} role="status">
          {status.text}
        </p>
      )}
    </section>
  );
}

/** The address line kept with a place, to recognise it by: what search
 *  found. A position from the phone has none. */
function addressOf(at: Endpoint): string | undefined {
  if (at.source !== "search") return undefined;
  return [at.label, at.detail].filter(Boolean).join(", ");
}

function PlaceForm({
  title,
  initialName,
  initial,
  here,
  offerHome = false,
  onSave,
  onCancel,
}: {
  title: string;
  initialName: string;
  initial: Endpoint | null;
  here: Coord | null;
  offerHome?: boolean;
  onSave: (name: string, at: Endpoint, makeHome: boolean) => boolean;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initialName);
  const [at, setAt] = useState<Endpoint | null>(initial);
  const [makeHome, setMakeHome] = useState(offerHome);
  const [problem, setProblem] = useState<string | null>(null);

  return (
    <form
      className="place-form"
      aria-label={title}
      onSubmit={(e) => {
        e.preventDefault();
        if (!name.trim()) return setProblem("Give the place a name.");
        if (!at) return setProblem("Choose where the place is.");
        setProblem(null);
        onSave(name, at, makeHome);
      }}
    >
      <label className="account-field">
        <span>Name</span>
        <input
          type="text"
          value={name}
          maxLength={LABEL_MAX}
          placeholder="e.g. Swimming"
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <PlaceSearch
        legend="Where it is"
        value={at}
        onChange={setAt}
        near={here}
        onUseCurrentLocation={
          here ? () => setAt({ coord: here, label: "Where I am now", source: "current" }) : undefined
        }
        currentLocationLabel="Where I am now"
        placeholder="Search an address or postcode"
      />
      {offerHome && (
        <label className="walks-check">
          <input type="checkbox" checked={makeHome} onChange={(e) => setMakeHome(e.target.checked)} />
          This is Home
        </label>
      )}
      {problem && <p className="account-error">{problem}</p>}
      <div className="place-actions">
        <button type="submit" className="btn-primary">
          Save place
        </button>
        <button type="button" className="btn-quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
