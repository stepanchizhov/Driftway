import { useState } from "react";

/**
 * "Driftway has a new address" - shown on the old address only.
 *
 * Founder decision, 10 Oct 2026: the app moves to driftway.stepan.chizhov.com
 * (the Android app needs its final web address). What a browser keeps for a
 * site belongs to that address, so moving loses, on each device:
 *   - Home, settings, walk preferences and the recent destination,
 *   - the sign-in session (sign in again; the account itself is unaffected),
 *   - drives saved without an account, which are tied to a device id kept
 *     there. Signing in on the old address and moving them to the account
 *     (Saved) brings them along.
 * Nothing is carried across automatically: the device id acts like a
 * password, and must not travel in a link. The link keeps the page and any
 * meetup link the person is on - the same URL on Driftway's new address.
 *
 * Off until VITE_CANONICAL_ORIGIN is set at build time, and never shown on
 * that address itself.
 */
export function MovedBanner() {
  const canonical = (import.meta.env.VITE_CANONICAL_ORIGIN ?? "").replace(/\/$/, "");
  const [hidden, setHidden] = useState(false);
  if (!canonical || hidden || window.location.origin === canonical) return null;
  const target = canonical + window.location.pathname + window.location.search + window.location.hash;

  return (
    <div className="moved-banner" role="status">
      <p>
        <strong>Driftway has a new address.</strong> Your account comes with you.
        On the new address you&rsquo;ll set Home and settings again. Drives you
        saved without signing in stay here unless you sign in first and move
        them to your account from Saved.
      </p>
      <div className="moved-actions">
        <a className="btn-primary" href={target}>
          Go to the new address
        </a>
        <button className="btn-quiet" onClick={() => setHidden(true)}>
          Not now
        </button>
      </div>
    </div>
  );
}
