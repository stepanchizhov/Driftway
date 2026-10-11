import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Coord } from "../types";
import { MAX_POINTS, lengthOf, metres, LOOP_M } from "./myWalks";

/**
 * Drawing a route of your own: tap the map along the way you walk, in order.
 * Like the checkpoint picker, a tap places a point only when the finger did
 * not drag, so moving and zooming the map never adds one. Nothing here calls
 * a route provider; the route is followed along mapped paths only when it is
 * shown.
 */

const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const LINE = "#7c3aed";

export function RouteDrawer({
  centre,
  units,
  onSave,
  onCancel,
}: {
  centre: Coord | null;
  units: "km" | "mi";
  onSave: (name: string, points: Coord[]) => void;
  onCancel: () => void;
}) {
  const box = useRef<HTMLDivElement | null>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const [points, setPoints] = useState<Coord[]>([]);
  const [backToStart, setBackToStart] = useState(true);
  const [name, setName] = useState("");
  // One point is kept free for the way back to the start.
  const room = MAX_POINTS - 1;
  const add = useRef((c: Coord) => setPoints((p) => (p.length < room ? [...p, c] : p)));

  useEffect(() => {
    if (!box.current) return;
    const c = centre ?? { lat: 51.4816, lng: -0.6105 };
    const m = L.map(box.current, { zoomControl: true }).setView([c.lat, c.lng], 16);
    L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    m.on("click", (e: L.LeafletMouseEvent) => add.current({ lat: e.latlng.lat, lng: e.latlng.lng }));
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
      layer.current = null;
    };
    // Centred once, on opening.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const route = useMemo(() => finished(points, backToStart), [points, backToStart]);

  useEffect(() => {
    const g = layer.current;
    if (!g) return;
    g.clearLayers();
    if (route.length > 1) {
      L.polyline(route.map((p) => [p.lat, p.lng] as [number, number]), {
        color: LINE, weight: 4, opacity: 0.8, dashArray: "6 6",
      }).addTo(g);
    }
    points.forEach((p, i) => {
      L.circleMarker([p.lat, p.lng], {
        radius: i === 0 ? 8 : 5,
        color: "#10162e",
        weight: 2,
        fillColor: i === 0 ? "#ffffff" : LINE,
        fillOpacity: 1,
        interactive: false,
      }).addTo(g);
    });
  }, [points, route]);

  const km = lengthOf(route) / 1000;
  const length = units === "mi" ? `${(km / 1.609344).toFixed(1)} mi` : `${km.toFixed(1)} km`;

  return (
    <div className="cp-picker route-drawer" role="group" aria-label="Draw your route on the map">
      <p className="walks-hint" id="route-drawer-help">
        Tap the map along the way you walk, in order, starting where you start.
        A point at each turn or path you take is enough; between points Driftway
        follows the mapped paths. Moving and zooming the map doesn&rsquo;t add
        points.
      </p>
      <div
        ref={box}
        className="walk-map cp-map"
        role="region"
        aria-label="Map for drawing your route"
        aria-describedby="route-drawer-help"
      />
      <p className="walks-hint cp-status" aria-live="polite">
        {points.length === 0
          ? "No points yet. Tap where your walk starts."
          : `${points.length} point${points.length > 1 ? "s" : ""}, about ${length} as the crow flies` +
            (points.length >= room ? ". That's the most a route can have." : ".")}
      </p>
      <label className="walks-check">
        <input type="checkbox" checked={backToStart} onChange={(e) => setBackToStart(e.target.checked)} />
        Finish where I started
      </label>
      <label className="account-field">
        <span>Name</span>
        <input
          type="text"
          maxLength={80}
          value={name}
          placeholder="e.g. The Long Walk loop"
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <div className="cp-actions">
        <button
          type="button"
          className="btn-quiet"
          disabled={points.length === 0}
          onClick={() => setPoints((p) => p.slice(0, -1))}
        >
          Undo last point
        </button>
        <button
          type="button"
          className="btn-primary"
          disabled={route.length < 2}
          onClick={() => onSave(name || "My walk", route)}
        >
          Save to My walks
        </button>
        <button type="button" className="btn-quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

/** The points as walked: back to the first one at the end, if asked and
 *  not already there. */
function finished(points: Coord[], backToStart: boolean): Coord[] {
  if (!backToStart || points.length < 2) return points;
  const end = points[points.length - 1];
  return metres(points[0], end) <= LOOP_M ? points : [...points, points[0]];
}
