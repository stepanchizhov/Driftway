import type { Coord } from "../types";

interface Props {
  start: Coord;
  waypoints: Coord[];
  size?: number;
  /** Decorative ring only, used as the app's signature motif. */
  ring?: boolean;
}

// Draws a small outline of the loop: start -> waypoints -> back to start.
// Coordinates are projected to a local plane (good enough at this scale) and
// normalised to fit the box. This is the "simple route preview" the project
// bible asks each card to show.
export function LoopMark({ start, waypoints, size = 64, ring = false }: Props) {
  const pts: Coord[] = [start, ...waypoints, start];

  // Equirectangular projection around the start latitude.
  const latRad = (start.lat * Math.PI) / 180;
  const xy = pts.map((p) => ({
    x: (p.lng - start.lng) * Math.cos(latRad),
    y: -(p.lat - start.lat), // invert so north is up
  }));

  const xs = xy.map((p) => p.x);
  const ys = xy.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const span = Math.max(spanX, spanY);

  const pad = size * 0.18;
  const inner = size - pad * 2;

  // Centre the shape within the box.
  const offX = (size - (spanX / span) * inner) / 2;
  const offY = (size - (spanY / span) * inner) / 2;

  const proj = xy.map((p) => ({
    x: offX + ((p.x - minX) / span) * inner,
    y: offY + ((p.y - minY) / span) * inner,
  }));

  const d =
    proj
      .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
      .join(" ") + " Z";

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      aria-hidden="true"
    >
      {ring && (
        <circle
          cx={size / 2}
          cy={size / 2}
          r={size / 2 - 1}
          stroke="var(--line)"
          strokeWidth="1"
        />
      )}
      <path
        d={d}
        stroke="var(--accent)"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* start / finish marker */}
      <circle cx={proj[0].x} cy={proj[0].y} r="3" fill="var(--accent)" />
    </svg>
  );
}
