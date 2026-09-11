import type { Coord, NavigationOption, RouteOption } from "../types";
import type { Units } from "../hooks/useSettings";
import { formatDistance } from "../lib/units";
import { LoopMark } from "./LoopMark";

interface Props {
  route: RouteOption;
  start: Coord;
  rank: number;
  targetMinutes: number;
  onStart: (route: RouteOption, via?: NavigationOption) => void;
  started?: boolean;
  onSave?: (route: RouteOption) => void;
  saved?: boolean;
  units?: Units;
  /** Destination mode shows time against the direct drive, not a loop delta. */
  destination?: boolean;
  /** The parent's chosen navigation app, honoured only when it can carry
   *  the route intact. */
  preferredNavigation?: string;
}

function deltaLabel(delta: number): { text: string; tone: string } {
  const rounded = Math.round(delta);
  if (rounded === 0) return { text: "on time", tone: "ok" };
  if (rounded > 0) return { text: `${rounded} min over`, tone: "neutral" };
  return { text: `${Math.abs(rounded)} min under`, tone: "neutral" };
}

export function RouteCard({
  route, start, rank, onStart, started, onSave, saved,
  units = "km", destination = false, preferredNavigation = "google_maps",
}: Props) {
  const minutes = Math.round(route.predicted_minutes);
  const distance = formatDistance(route.distance_km, units);
  const delta = deltaLabel(route.delta_minutes);
  // A simulated route is a demo of what the app would do. It has no real
  // geometry, so there is nothing to hand to a navigation app.
  const navigable = !route.simulated && !!route.maps_url;

  // The backend orders these best-first and never lets a preference outrank
  // carrying the shaping points, so the head of the list is the drive that is
  // still the right length.
  const options: NavigationOption[] = route.navigation ?? [];
  const chosen =
    options.find((o) => o.provider_id === preferredNavigation && o.keeps_waypoints) ??
    options.find((o) => o.keeps_waypoints) ??
    options[0];
  // Only worth mentioning when the parent asked for an app that cannot cope.
  const preferredOption = options.find((o) => o.provider_id === preferredNavigation);
  const swapNotice =
    preferredOption && !preferredOption.keeps_waypoints && chosen
      ? preferredOption.notice
      : null;
  const extra =
    destination && route.extra_minutes != null
      ? Math.round(route.extra_minutes)
      : null;

  return (
    <article className={`card${started ? " card-started" : ""}`}>
      <div className="card-top">
        <div className="card-figures">
          <div className="card-minutes">
            <span className="card-min-num">{minutes}</span>
            <span className="card-min-unit">min</span>
          </div>
          <div className="card-meta">
            {route.is_direct ? (
              <span className="tag tag-neutral">quickest way</span>
            ) : (
              <span className={`tag tag-${delta.tone}`}>{delta.text}</span>
            )}
            {extra != null && extra > 0 && (
              <span className="tag tag-neutral">+{extra} min vs direct</span>
            )}
            {route.simulated && <span className="tag tag-demo">demo only</span>}
            <span className="card-distance">{distance}</span>
          </div>
        </div>
        <div className="card-right">
          {onSave && (
            <button
              className={`card-save${saved ? " card-save-on" : ""}`}
              onClick={() => onSave(route)}
              aria-label={saved ? "Saved to favourites" : "Save to favourites"}
              title={saved ? "Saved" : "Save to favourites"}
            >
              {saved ? "★" : "☆"}
            </button>
          )}
          <LoopMark
            start={start}
            waypoints={route.waypoints}
            geometry={route.geometry}
            size={72}
            ring
            showFinish={destination}
          />
        </div>
      </div>

      <p className="card-character">{route.character}</p>

      {route.caveat && <p className="card-caveat">Note: {route.caveat}</p>}

      {swapNotice && <p className="card-nav-notice">{swapNotice}</p>}

      {navigable ? (
        <button className="btn-start" onClick={() => onStart(route, chosen)}>
          {started ? "Reopen in " : "Start in "}
          {chosen?.label ?? "Google Maps"}
          <span className="btn-start-rank">Option {rank}</span>
        </button>
      ) : (
        <div className="btn-start btn-start-off" aria-disabled="true">
          Simulated route — not drivable
          <span className="btn-start-rank">Demo {rank}</span>
        </div>
      )}
    </article>
  );
}
