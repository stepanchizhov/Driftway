import { useRef, useState, type ReactNode } from "react";
import type { Coord } from "../types";
import type { Units } from "../hooks/useSettings";
import { NotAdmitted, traceWalks, type GeneratedWalks, type TraceFidelity, type Walk } from "./api";
import { MAX_POINTS, closeLoop, gapToStart, isLoop, lengthOf, parseGpx, type MyWalk } from "./myWalks";
import { RouteDrawer } from "./RouteDrawer";
import type { WalkSetup } from "./useWalkSetup";

/**
 * My walks: routes of your own, kept on this device (founder request,
 * 11 Oct 2026). Draw one on the map, import a GPX file, or save a walk
 * Driftway made; each is followed along mapped paths and judged for the
 * current pram, carrier, time and pace when it is shown.
 */
export function MyWalksSection({
  walks,
  onAdd,
  onRemove,
  onReplacePoints,
  centre,
  setup,
  units,
  renderWalk,
}: {
  walks: MyWalk[];
  onAdd: (name: string, points: Coord[], source: MyWalk["source"]) => MyWalk;
  onRemove: (id: string) => void;
  /** Same route, new points: closing it into a loop. */
  onReplacePoints: (id: string, points: Coord[]) => void;
  centre: Coord | null;
  setup: WalkSetup;
  units: Units;
  /** Draws a walk card; `source` is the parent's own route, for the map. */
  renderWalk: (walk: Walk, source?: Coord[]) => ReactNode;
}) {
  const [drawing, setDrawing] = useState(false);
  const [imported, setImported] = useState<{
    name: string;
    points: Coord[];
    count: number;
    /** Finish where it started: walked as a loop. */
    close: boolean;
  } | null>(null);
  const [shown, setShown] = useState<{
    id: string;
    key: string;
    result: GeneratedWalks & { trace?: TraceFidelity };
  } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const file = useRef<HTMLInputElement | null>(null);
  const settingsKey = JSON.stringify(setup);

  async function show(w: MyWalk) {
    setBusyId(w.id);
    setError(null);
    try {
      const result = await traceWalks({
        profile: setup.profile,
        minutes: setup.minutes,
        pace_kmh: setup.paceKmh,
        allow_out_and_back: setup.maxRetrace >= 0.5,
        points: w.points,
        name: w.name,
        start_label: `start of ${w.name}`.slice(0, 80),
        ...(setup.profile === "pram"
          ? { pram: setup.pram }
          : setup.profile === "carrier"
            ? { carrier: setup.carrier }
            : {}),
      });
      setShown({ id: w.id, key: settingsKey, result });
    } catch (e) {
      setShown(null);
      setError(
        e instanceof NotAdmitted
          ? "Your own routes need the same access as walks made from your start."
          : e instanceof Error
            ? e.message
            : "Couldn't follow your route just now.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function readGpx(f: File) {
    setError(null);
    try {
      const { name, points } = parseGpx(await f.text());
      if (points.length < 2) {
        setError("No track found in that file. Driftway reads GPX files with a track or a route.");
        return;
      }
      // A recorded circuit often stops short of where it began (the
      // recording ended on the way in). Offered closed when the gap is small
      // enough to be that; the parent decides.
      setImported({
        name: name ?? f.name.replace(/\.gpx$/i, ""),
        points,
        count: points.length,
        close: !isLoop(points) && gapToStart(points) <= 2000,
      });
    } catch {
      setError("Couldn't read that file.");
    }
  }

  const km = (pts: Coord[]) => {
    const k = lengthOf(pts) / 1000;
    return units === "mi" ? `${(k / 1.609344).toFixed(1)} mi` : `${k.toFixed(1)} km`;
  };

  return (
    <fieldset className="walks-checkpoint my-walks">
      <legend>My walks</legend>
      <p className="walks-hint">
        Routes you actually walk. Draw one on the map, import a GPX file from an
        app that recorded it, or save a walk Driftway made. Each is checked for
        your {setup.profile === "pram" ? "pram" : setup.profile === "carrier" ? "carrier" : "walk"},
        time and pace when you show it.
      </p>

      {walks.length > 0 && (
        <ul className="cp-list">
          {walks.map((w) => (
            <li key={w.id} className="cp-row my-walk-row">
              <span className="cp-name">
                {w.name}
                <span className="my-walk-meta">
                  {" "}
                  · {km(w.points)} {isLoop(w.points) ? "loop" : "there and back"}
                </span>
              </span>
              {confirmDelete === w.id ? (
                <>
                  <button
                    type="button"
                    className="btn-quiet cp-small"
                    onClick={() => {
                      onRemove(w.id);
                      setConfirmDelete(null);
                      if (shown?.id === w.id) setShown(null);
                    }}
                  >
                    Delete
                  </button>
                  <button type="button" className="btn-quiet cp-small" onClick={() => setConfirmDelete(null)}>
                    Keep
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    className="btn-quiet cp-small"
                    disabled={busyId !== null}
                    onClick={() => void show(w)}
                  >
                    {busyId === w.id ? "Checking…" : "Show"}
                  </button>
                  {!isLoop(w.points) && (
                    <button
                      type="button"
                      className="btn-quiet cp-small"
                      title={`It ends ${distanceText(gapToStart(w.points), units)} from its start`}
                      onClick={() => {
                        onReplacePoints(w.id, closeLoop(w.points));
                        if (shown?.id === w.id) setShown(null);
                      }}
                    >
                      Make it a loop
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn-quiet cp-small"
                    aria-label={`Delete ${w.name}`}
                    onClick={() => setConfirmDelete(w.id)}
                  >
                    Delete
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {!drawing && !imported && (
        <div className="cp-buttons">
          <button type="button" className="btn-quiet" onClick={() => setDrawing(true)}>
            Draw a route on the map
          </button>
          <button type="button" className="btn-quiet" onClick={() => file.current?.click()}>
            Import a GPX file
          </button>
          <input
            ref={file}
            type="file"
            accept=".gpx,application/gpx+xml"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void readGpx(f);
            }}
          />
        </div>
      )}

      {drawing && (
        <RouteDrawer
          centre={centre}
          units={units}
          onCancel={() => setDrawing(false)}
          onSave={(name, points) => {
            const w = onAdd(name, points, "drawn");
            setDrawing(false);
            void show(w);
          }}
        />
      )}

      {imported && (
        <div className="cp-picker">
          <p className="walks-hint">
            Found a route of {km(imported.points)}, {imported.count} points.
            {imported.count > MAX_POINTS
              ? ` It's kept as ${MAX_POINTS} points spread along the way; between them Driftway follows the mapped paths.`
              : ""}
          </p>
          {!isLoop(imported.points) && (
            <label className="walks-check">
              <input
                type="checkbox"
                checked={imported.close}
                onChange={(e) => setImported({ ...imported, close: e.target.checked })}
              />
              Finish where I started (it ends {distanceText(gapToStart(imported.points), units)} from its
              start). Otherwise it&rsquo;s walked there and back.
            </label>
          )}
          <label className="account-field">
            <span>Name</span>
            <input
              type="text"
              maxLength={80}
              value={imported.name}
              onChange={(e) => setImported({ ...imported, name: e.target.value })}
            />
          </label>
          <div className="cp-actions">
            <button
              type="button"
              className="btn-primary"
              onClick={() => {
                const w = onAdd(
                  imported.name,
                  imported.close ? closeLoop(imported.points) : imported.points,
                  "gpx",
                );
                setImported(null);
                void show(w);
              }}
            >
              Save to My walks
            </button>
            <button type="button" className="btn-quiet" onClick={() => setImported(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && <p className="account-error">{error}</p>}

      {shown && (
        <div className="walks-list">
          {shown.key !== settingsKey && (
            <p className="walks-hint">
              Your settings changed since this was checked.{" "}
              <button
                type="button"
                className="btn-quiet cp-small"
                onClick={() => {
                  const w = walks.find((x) => x.id === shown.id);
                  if (w) void show(w);
                }}
              >
                Check again
              </button>
            </p>
          )}
          <Fidelity
            trace={shown.result.trace}
            source={walks.find((x) => x.id === shown.id)?.source}
            units={units}
          />
          {shown.result.walks.map((w) => renderWalk(w, walks.find((x) => x.id === shown.id)?.points))}
          <p className="walks-hint">{shown.result.attribution}</p>
        </div>
      )}

      <p className="walks-hint">
        Kept on this phone only. When you show one, its points go to Driftway
        and on to openrouteservice to follow the paths, like a walk&rsquo;s
        start; neither keeps them.
      </p>
    </fieldset>
  );
}

/**
 * What the screen says about how the walk shown relates to the parent's own
 * route: always that it was recalculated, and where it differs when it does.
 * The saved route itself is never changed to match.
 */
function Fidelity({
  trace,
  source,
  units,
}: {
  trace?: TraceFidelity;
  source?: MyWalk["source"];
  units: Units;
}) {
  const what = source === "gpx" ? "your recorded track" : source === "made" ? "the walk you saved" : "your drawing";
  const m = (x: number) =>
    units === "mi" ? `${Math.round(x * 1.0936)} yd` : `${Math.round(x)} m`;
  if (!trace || !trace.changed) {
    return (
      <p className="walks-hint">
        Recalculated along mapped paths through your points, so it can differ a
        little from {what}. On the map, your own line is the dotted purple one.
      </p>
    );
  }
  const parts: string[] = [];
  if (trace.far_points.length) {
    const list = trace.far_points.slice(0, 5).join(", ");
    parts.push(
      `it doesn't pass near point${trace.far_points.length > 1 ? "s" : ""} ${list}` +
        `${trace.far_points.length > 5 ? " and others" : ""} (up to ${m(trace.max_offset_m)} away)`,
    );
  }
  if (trace.longer_share > 0.3) {
    parts.push(`it's about ${Math.round(trace.longer_share * 100)}% longer than the line through your points`);
  }
  return (
    <div className="walks-gate" role="status">
      <p>
        <strong>This walk differs from {what}:</strong> {parts.join(", and ")}.
        Mapped paths may not join up where you walk, or the way may not suit
        your settings.
      </p>
      <p className="walks-hint">
        Compare them on the map: your own line is the dotted purple one. Adding
        a point where they part, or moving it onto the path you take, keeps the
        walk closer. Your saved route is unchanged.
      </p>
    </div>
  );
}

function distanceText(m: number, units: Units): string {
  if (units === "mi") return m < 1609 ? `${Math.round(m * 1.0936)} yd` : `${(m / 1609.344).toFixed(1)} mi`;
  return m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`;
}

