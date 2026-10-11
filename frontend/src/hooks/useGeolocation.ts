import { useCallback, useEffect, useRef, useState } from "react";
import type { Coord } from "../types";

type GeoState =
  | { status: "idle" }
  | { status: "locating" }
  | { status: "ready"; coord: Coord }
  | { status: "error"; message: string };

/** How long Driftway waits before saying it can't find the phone. */
export const LOCATE_DEADLINE_MS = 12000;
/** How long the requests stay open: a late fix still replaces the message. */
export const LOCATE_LISTEN_MS = 30000;

export const LOCATION_DENIED =
  "Location is off for Driftway. Turn it on in your phone's settings, or say where you are below.";
export const LOCATION_UNAVAILABLE =
  "Couldn't get your location from this phone just now. Try again, or say where you are below.";

/**
 * The browser's geolocation, asked once on mount, with `locate()` to retry.
 * Designed for a parked, stationary parent.
 *
 * It never waits forever. Founder report, 11 Oct 2026: the app on his phone
 * sat on "Waiting for your location" with every tab blocked, while the same
 * site in a browser tab found him. In the Android app, Android answers for
 * location on the app's behalf, and when that hand-over stalls, the browser's
 * own `timeout` does not fire. So:
 *   - a precise fix is asked for first;
 *   - if that fails for any reason but refusal, or nothing at all has
 *     arrived after a few seconds, one coarse request follows (it works
 *     indoors, and with "approximate location");
 *   - after LOCATE_DEADLINE_MS with no answer, it says so - but keeps
 *     listening until LOCATE_LISTEN_MS, and a position that arrives late
 *     replaces the message. On the founder's phone (11 Oct, Android app,
 *     first use after install) the first fix took longer than 12 s; the
 *     next load found him at once.
 * Answers that arrive after a newer attempt has started are ignored.
 */
export function useGeolocation() {
  const [state, setState] = useState<GeoState>({ status: "idle" });
  const attempt = useRef(0);

  const locate = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setState({ status: "error", message: "This device can't share its location." });
      return;
    }
    const id = ++attempt.current;
    let settled = false;
    let coarseAsked = false;
    const timers: number[] = [];

    const finish = (next: GeoState) => {
      if (settled || id !== attempt.current) return;
      settled = true;
      timers.forEach((t) => window.clearTimeout(t));
      setState(next);
    };
    // The message at the deadline does not settle the attempt: a position
    // may still arrive, and then wins.
    const tooSlow = () => {
      if (!settled && id === attempt.current) {
        setState({ status: "error", message: LOCATION_UNAVAILABLE });
      }
    };
    const ok = (pos: GeolocationPosition) =>
      finish({ status: "ready", coord: { lat: pos.coords.latitude, lng: pos.coords.longitude } });
    const coarse = () => {
      if (coarseAsked || settled) return;
      coarseAsked = true;
      navigator.geolocation.getCurrentPosition(
        ok,
        (err) =>
          finish({
            status: "error",
            message: err.code === err.PERMISSION_DENIED ? LOCATION_DENIED : LOCATION_UNAVAILABLE,
          }),
        { enableHighAccuracy: false, timeout: LOCATE_LISTEN_MS, maximumAge: 300000 },
      );
    };

    setState({ status: "locating" });
    navigator.geolocation.getCurrentPosition(
      ok,
      (err) =>
        err.code === err.PERMISSION_DENIED
          ? finish({ status: "error", message: LOCATION_DENIED })
          : coarse(),
      { enableHighAccuracy: true, timeout: LOCATE_LISTEN_MS, maximumAge: 30000 },
    );
    // Nothing yet after 4 s: ask coarsely too, whichever answers first wins.
    timers.push(window.setTimeout(coarse, 4000));
    // Say so after a while, and stop listening later still. Never forever.
    timers.push(window.setTimeout(tooSlow, LOCATE_DEADLINE_MS));
    timers.push(
      window.setTimeout(
        () => finish({ status: "error", message: LOCATION_UNAVAILABLE }),
        LOCATE_LISTEN_MS + 1000,
      ),
    );
  }, []);

  useEffect(() => {
    locate();
  }, [locate]);

  return { state, locate };
}
