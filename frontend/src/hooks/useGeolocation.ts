import { useCallback, useEffect, useState } from "react";
import type { Coord } from "../types";

type GeoState =
  | { status: "idle" }
  | { status: "locating" }
  | { status: "ready"; coord: Coord }
  | { status: "error"; message: string };

// Wraps the browser geolocation API. Asks once on mount, and exposes a
// `locate()` to retry. Designed for a parked, stationary parent.
export function useGeolocation() {
  const [state, setState] = useState<GeoState>({ status: "idle" });

  const locate = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setState({
        status: "error",
        message: "This device can't share its location.",
      });
      return;
    }
    setState({ status: "locating" });
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        setState({
          status: "ready",
          coord: { lat: pos.coords.latitude, lng: pos.coords.longitude },
        }),
      (err) => {
        const message =
          err.code === err.PERMISSION_DENIED
            ? "Location is off. Turn it on, or set a Home below."
            : "Couldn't find your location. Try again, or set a Home.";
        setState({ status: "error", message });
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    );
  }, []);

  useEffect(() => {
    locate();
  }, [locate]);

  return { state, locate };
}
