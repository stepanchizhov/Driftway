import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Coord } from "../types";

/**
 * Choosing a checkpoint on the map - an explicit mode, opened by "Choose on
 * map" and closed by "Use this point" or "Cancel".
 *
 * Only this map moves the checkpoint. Inside it, a tap places the draft marker
 * (Leaflet reports a click only when the finger did not drag, so panning and
 * zooming never place anything) and dragging the marker moves it. The cross in
 * the middle and "Place at centre" give the same result without precise
 * gestures, and from the keyboard. The map is centred once, when it opens, and
 * never re-fitted while the parent is choosing.
 *
 * Nothing here calls a route provider or a geocoder: the point is labelled
 * "Point on map" and only used when the parent taps "Update walks".
 */

const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const CASING = "#10162e";
const CHECKPOINT = "#7c3aed";

const draftIcon = L.divIcon({
  className: "cp-pin",
  html: '<span class="cp-pin-dot"></span>',
  iconSize: [28, 28],
  iconAnchor: [14, 14],
});

export function CheckpointPicker({
  start,
  draft,
  confirmed,
  onPlace,
  onConfirm,
  onCancel,
}: {
  start: Coord | null;
  /** The marker being placed, if any. */
  draft: Coord | null;
  /** The checkpoint already chosen, shown faintly for comparison. */
  confirmed: Coord | null;
  onPlace: (c: Coord) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const box = useRef<HTMLDivElement | null>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.Marker | null>(null);
  // Leaflet handlers are bound once; read the latest callback through a ref.
  const place = useRef(onPlace);
  place.current = onPlace;

  useEffect(() => {
    if (!box.current) return;
    const centre = draft ?? confirmed ?? start ?? { lat: 51.4816, lng: -0.6105 };
    const m = L.map(box.current, { zoomControl: true }).setView(
      [centre.lat, centre.lng],
      16,
    );
    L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(m);
    if (start) {
      L.circleMarker([start.lat, start.lng], {
        radius: 9, color: CASING, weight: 3, fillColor: "#ffffff", fillOpacity: 1,
      }).bindTooltip("Start").addTo(m);
    }
    if (confirmed) {
      L.circleMarker([confirmed.lat, confirmed.lng], {
        radius: 8, color: CHECKPOINT, weight: 2, dashArray: "3 3", fillOpacity: 0,
      }).bindTooltip("Current checkpoint").addTo(m);
    }
    m.on("click", (e: L.LeafletMouseEvent) =>
      place.current({ lat: e.latlng.lat, lng: e.latlng.lng }),
    );
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
      marker.current = null;
    };
    // Centred once, on opening; never re-fitted while choosing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Show the draft where it is now, without moving the map.
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    if (!draft) {
      marker.current?.remove();
      marker.current = null;
      return;
    }
    if (!marker.current) {
      marker.current = L.marker([draft.lat, draft.lng], {
        icon: draftIcon,
        draggable: true,
        keyboard: false,
        title: "Your checkpoint",
      })
        .on("dragend", (e) => {
          const p = (e.target as L.Marker).getLatLng();
          place.current({ lat: p.lat, lng: p.lng });
        })
        .addTo(m);
    } else {
      marker.current.setLatLng([draft.lat, draft.lng]);
    }
  }, [draft]);

  function placeAtCentre() {
    const c = map.current?.getCenter();
    if (c) onPlace({ lat: c.lat, lng: c.lng });
  }

  return (
    <div className="cp-picker" role="group" aria-label="Choose a checkpoint on the map">
      <p className="walks-hint" id="cp-picker-help">
        Tap the map where the walk should go, or drag the marker. Moving and
        zooming the map doesn&rsquo;t move it. Or line the cross up with the
        spot and use &ldquo;Place at centre&rdquo;.
      </p>
      <div className="cp-map-wrap">
        <div
          ref={box}
          className="walk-map cp-map"
          role="region"
          aria-label="Map for choosing a checkpoint"
          aria-describedby="cp-picker-help"
        />
        <span className="cp-cross" aria-hidden="true" />
      </div>
      <p className="walks-hint cp-status" aria-live="polite">
        {draft
          ? `Marker placed at ${draft.lat.toFixed(5)}, ${draft.lng.toFixed(5)}.`
          : "No marker placed yet."}
      </p>
      <div className="cp-actions">
        <button type="button" className="btn-quiet" onClick={placeAtCentre}>
          Place at centre
        </button>
        <button type="button" className="btn-primary" disabled={!draft} onClick={onConfirm}>
          Use this point
        </button>
        <button type="button" className="btn-quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
