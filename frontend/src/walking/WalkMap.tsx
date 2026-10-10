import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Walk } from "./api";

/**
 * The walk on a map, with you on it.
 *
 * Why an in-app map for walks and not for driving: Google Maps cannot be made
 * to follow a walk. Its URLs take at most three checkpoints on a phone, and
 * between them it picks its own way - which may be the steps the walk was
 * curated to avoid. So the walk is drawn here, coloured by what is known about
 * each stretch, with the turning point and the gates marked, and your position
 * as a dot so you can follow it. It is not turn-by-turn navigation.
 *
 * Map images come from tile.openstreetmap.org. Its usage policy (checked 9 Oct
 * 2026) allows light use with attribution shown on the map, a real Referer,
 * honoured caching, and no bulk or offline download; access can be withdrawn
 * without notice, especially for commercial services. Fine for a beta. A tile
 * provider is the change to make before wider use - see docs/WALKING.md.
 */

const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

/** Read a colour from the app's own theme tokens, so the map matches it. */
function token(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

const MARKER_LABEL: Record<string, string> = {
  steps: "Steps",
  stile: "Stile",
  kissing_gate: "Kissing gate",
  gate: "Gate",
  bollard: "Bollards",
  other: "Barrier",
  turn_back: "Turn back here",
  via: "Checkpoint",
  via_requested: "Your checkpoint",
};

export function WalkMap({ walk }: { walk: Walk }) {
  const box = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!box.current) return;
    const map = L.map(box.current, { zoomControl: true, attributionControl: true });
    L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map);

    // Colours for a LIGHT map, not the app's dark-theme pastels: founder
    // feedback, 9 Oct - pale green vanished into parks and amber into fields.
    // Saturated colours over a dark casing read on any map background.
    const colour = {
      ok: "#14a04f",
      unknown: "#6b7aa6",
      difficult: "#f08c00",
      blocked: "#d62f2f",
    };
    const CASING = "#10162e";

    // Only the way out is drawn on a there-and-back walk: the way back is the
    // same line, and drawing it twice hides nothing but costs clarity.
    const half =
      walk.shape === "out_and_back"
        ? walk.sections.filter((s) => s.to_m <= walk.distance_m / 2 + 1)
        : walk.sections;
    const bounds = L.latLngBounds([]);
    for (const s of half) {
      if (s.geometry.length < 2) continue;
      const line = s.geometry.map(([a, b]) => L.latLng(a, b));
      // A dark outline first, then the coloured line on top of it.
      L.polyline(line, { color: CASING, weight: 10, opacity: 0.85 }).addTo(map);
      L.polyline(line, {
        color: colour[s.verdict],
        weight: 6,
        opacity: 1,
        dashArray: s.verdict === "unknown" ? "8 8" : undefined,
      })
        .bindTooltip(`${s.label}: ${s.surface}`)
        .addTo(map);
      line.forEach((p) => bounds.extend(p));
    }

    // Start, turning point and checkpoint each look different: founder
    // feedback, 9 Oct - start and turn-back were identical orange dots.
    L.circleMarker([walk.start.lat, walk.start.lng], {
      radius: 9, color: CASING, weight: 3, fillColor: "#ffffff", fillOpacity: 1,
    }).bindTooltip(`Start: ${walk.start.label}`).addTo(map);

    for (const m of walk.markers) {
      if (m.kind === "via_requested") {
        // The parent's own marker, where the provider moved the checkpoint
        // away from it: a hollow ring, joined to nothing - no line is drawn
        // across ground nobody has mapped as passable.
        L.circleMarker([m.lat, m.lng], {
          radius: 9, color: "#7c3aed", weight: 3, dashArray: "4 3", fillOpacity: 0,
        })
          .bindTooltip(`${MARKER_LABEL.via_requested}: ${m.label ?? ""}`)
          .addTo(map);
        bounds.extend([m.lat, m.lng]);
        continue;
      }
      const fill =
        m.kind === "turn_back" ? token("--accent", "#f2b179")
        : m.kind === "via" ? "#7c3aed"
        : colour.difficult;
      L.circleMarker([m.lat, m.lng], {
        radius: m.kind === "turn_back" || m.kind === "via" ? 8 : 6,
        color: CASING,
        weight: 2,
        fillColor: fill,
        fillOpacity: 1,
      })
        .bindTooltip(m.label ? `${MARKER_LABEL[m.kind] ?? m.kind}: ${m.label}` : MARKER_LABEL[m.kind] ?? m.kind)
        .addTo(map);
    }

    if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });

    // You, as a dot - only while the map is open, and never sent anywhere.
    let you: L.CircleMarker | null = null;
    let watch: number | null = null;
    if ("geolocation" in navigator) {
      watch = navigator.geolocation.watchPosition(
        (pos) => {
          const p = L.latLng(pos.coords.latitude, pos.coords.longitude);
          if (!you) {
            you = L.circleMarker(p, {
              radius: 7, color: "#fff", weight: 2, fillColor: "#3b82f6", fillOpacity: 1,
            }).bindTooltip("You").addTo(map);
          } else {
            you.setLatLng(p);
          }
        },
        () => {
          /* no permission or no fix: the walk still shows */
        },
        { enableHighAccuracy: true, maximumAge: 10000 },
      );
    }

    return () => {
      if (watch !== null) navigator.geolocation.clearWatch(watch);
      map.remove();
    };
  }, [walk]);

  return <div ref={box} className="walk-map" role="region" aria-label={`Map of ${walk.name}`} />;
}
