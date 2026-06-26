import type { Coord, RouteOption } from "../types";
import { LoopMark } from "./LoopMark";

interface Props {
  route: RouteOption;
  start: Coord;
  rank: number;
  targetMinutes: number;
  onStart: (route: RouteOption) => void;
  started?: boolean;
}

function deltaLabel(delta: number): { text: string; tone: string } {
  const rounded = Math.round(delta);
  if (rounded === 0) return { text: "on time", tone: "ok" };
  if (rounded > 0) return { text: `${rounded} min over`, tone: "neutral" };
  return { text: `${Math.abs(rounded)} min under`, tone: "neutral" };
}

export function RouteCard({ route, start, rank, onStart, started }: Props) {
  const minutes = Math.round(route.predicted_minutes);
  const distance = route.distance_km.toFixed(0);
  const delta = deltaLabel(route.delta_minutes);

  return (
    <article className={`card${started ? " card-started" : ""}`}>
      <div className="card-top">
        <div className="card-figures">
          <div className="card-minutes">
            <span className="card-min-num">{minutes}</span>
            <span className="card-min-unit">min</span>
          </div>
          <div className="card-meta">
            <span className={`tag tag-${delta.tone}`}>{delta.text}</span>
            <span className="card-distance">{distance} km</span>
          </div>
        </div>
        <LoopMark
          start={start}
          waypoints={route.waypoints}
          geometry={route.geometry}
          size={72}
          ring
        />
      </div>

      <p className="card-character">{route.character}</p>

      <button className="btn-start" onClick={() => onStart(route)}>
        {started ? "Reopen in Google Maps" : "Start in Google Maps"}
        <span className="btn-start-rank">Option {rank}</span>
      </button>
    </article>
  );
}
