import { useCallback, useEffect, useRef, useState } from "react";
import type { Coord, Place } from "../types";
import { searchPlaces, SearchFailed } from "../api";

interface Props {
  /** Shown above the field, e.g. "From" or "To". */
  legend: string;
  /** The endpoint currently chosen, or null if none. */
  value: Endpoint | null;
  onChange: (endpoint: Endpoint | null) => void;
  /** Bias results toward the parent's own area. */
  near?: Coord | null;
  /** Offered as a one-tap choice when available. */
  onUseCurrentLocation?: () => void;
  currentLocationLabel?: string;
  /** Offered as a one-tap choice when a Home is saved. */
  home?: Endpoint | null;
  placeholder?: string;
}

/** A resolved endpoint. `source` records how it was chosen so the UI can say
 *  "Your location" rather than repeating coordinates back at the user. */
export interface Endpoint {
  coord: Coord;
  label: string;
  detail?: string;
  source: "search" | "current" | "home" | "map";
  approximate?: boolean;
}

const DEBOUNCE_MS = 250;
const MIN_QUERY = 2;

const KIND_LABEL: Record<string, string> = {
  postcode: "Postcode",
  postcode_area: "Postcode area",
  address: "Address",
  street: "Street",
  poi: "Place",
  place: "Area",
};

/**
 * Address / postcode / place picker, shared by both endpoints.
 *
 * Two rules drive the whole component:
 *  1. Nothing is routed until the user picks a result. Typing "windsor" and
 *     hitting the button must not quietly drive to whatever came back first.
 *  2. A slow reply for an old query must never overwrite a newer one. Each
 *     search carries a sequence number and an AbortController; late arrivals
 *     are dropped rather than rendered.
 */
export function PlaceSearch({
  legend,
  value,
  onChange,
  near,
  onUseCurrentLocation,
  currentLocationLabel,
  home,
  placeholder = "Search address, postcode or place",
}: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "empty" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  // Monotonic request id. Only the newest may write to state.
  const latestRequest = useRef(0);
  const inFlight = useRef<AbortController | null>(null);

  const runSearch = useCallback(
    async (text: string) => {
      const seq = ++latestRequest.current;
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;

      setStatus("loading");
      setMessage(null);
      try {
        const places = await searchPlaces(text, near ?? null, controller.signal);
        if (seq !== latestRequest.current) return; // a newer query superseded this
        setResults(places);
        setStatus(places.length ? "idle" : "empty");
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        if (seq !== latestRequest.current) return;
        setResults([]);
        setStatus("error");
        setMessage(
          e instanceof SearchFailed ? e.message : "Address search failed.",
        );
      }
    },
    [near],
  );

  useEffect(() => {
    const text = query.trim();
    if (text.length < MIN_QUERY) {
      latestRequest.current++; // invalidate anything still in flight
      inFlight.current?.abort();
      setResults([]);
      setStatus("idle");
      setMessage(null);
      return;
    }
    const timer = setTimeout(() => void runSearch(text), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, runSearch]);

  // Drop any in-flight request when the field goes away.
  useEffect(() => () => inFlight.current?.abort(), []);

  function choose(place: Place) {
    onChange({
      coord: place.coord,
      label: place.label,
      detail: place.detail,
      source: "search",
      approximate: place.approximate,
    });
    setQuery("");
    setResults([]);
    setOpen(false);
    setStatus("idle");
  }

  function clear() {
    onChange(null);
    setQuery("");
    setResults([]);
    setStatus("idle");
    setOpen(true);
  }

  // --- chosen state -------------------------------------------------------
  if (value && !open) {
    return (
      <div className="ps">
        <span className="ps-legend">{legend}</span>
        <div className="ps-chosen">
          <div className="ps-chosen-text">
            <span className="ps-chosen-label">{value.label}</span>
            {value.detail && <span className="ps-chosen-detail">{value.detail}</span>}
          </div>
          <button className="ps-change" onClick={clear}>
            Change
          </button>
        </div>
        {value.approximate && (
          <p className="ps-hint">
            This is an area, not an exact spot. Search again for a street or
            full postcode to be precise.
          </p>
        )}
      </div>
    );
  }

  // --- picking state ------------------------------------------------------
  return (
    <div className="ps">
      <span className="ps-legend">{legend}</span>

      <div className="ps-shortcuts">
        {onUseCurrentLocation && (
          <button
            className="ps-shortcut"
            onClick={() => {
              onUseCurrentLocation();
              setOpen(false);
            }}
          >
            {currentLocationLabel ?? "Use my location"}
          </button>
        )}
        {home && (
          <button
            className="ps-shortcut"
            onClick={() => {
              onChange(home);
              setOpen(false);
            }}
          >
            Home
          </button>
        )}
      </div>

      <input
        className="ps-input"
        type="search"
        value={query}
        placeholder={placeholder}
        aria-label={`${legend}: search for a place`}
        autoComplete="off"
        onChange={(e) => setQuery(e.target.value)}
      />

      {status === "loading" && <p className="ps-note">Searching…</p>}
      {status === "empty" && (
        <p className="ps-note">
          Nothing found for “{query.trim()}”. Try a postcode or a nearby street.
        </p>
      )}
      {status === "error" && <p className="ps-note ps-err">{message}</p>}

      {results.length > 0 && (
        <ul className="ps-results">
          {results.map((place) => (
            <li key={place.id}>
              <button className="ps-result" onClick={() => choose(place)}>
                <span className="ps-result-main">
                  <span className="ps-result-label">{place.label}</span>
                  <span className="ps-kind">{KIND_LABEL[place.kind] ?? "Place"}</span>
                </span>
                {place.detail && (
                  <span className="ps-result-detail">{place.detail}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
