import { useEffect, useState } from "react";

/**
 * Which optional features this deployment has switched on.
 *
 * One request to /api/health, not one per feature: there used to be two, each
 * fetching the same document. And the answer is remembered on the device, so
 * the tab bar renders complete straight away on every visit after the first
 * instead of growing a tab once the reply arrives - which, on a free Render
 * instance waking from sleep, could be several seconds of a visibly changing
 * menu.
 *
 * The cached value is only ever a first guess. The live answer replaces it,
 * and the server still enforces every flag on its own endpoints, so a stale
 * cache can at worst show a tab whose screen then says it is unavailable.
 */

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const KEY = "driftway.features.v1";

export interface Features {
  meetHalfway: boolean;
  walking: boolean;
  /** Walks can be made from any start (an openrouteservice key is set). */
  walkGeneration: boolean;
}

const NONE: Features = { meetHalfway: false, walking: false, walkGeneration: false };

function cached(): Features {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...NONE, ...JSON.parse(raw) } : NONE;
  } catch {
    return NONE;
  }
}

export function useFeatures(): Features {
  const [features, setFeatures] = useState<Features>(cached);

  useEffect(() => {
    let alive = true;
    fetch(`${API_BASE}/api/health`)
      .then((res) => (res.ok ? res.json() : null))
      .then((body) => {
        if (!alive || !body) return;
        const live: Features = {
          meetHalfway: Boolean(body.meet_halfway),
          walking: Boolean(body.walking),
          walkGeneration: Boolean(body.walk_generation),
        };
        setFeatures(live);
        try {
          localStorage.setItem(KEY, JSON.stringify(live));
        } catch {
          /* private mode: works, just not remembered */
        }
      })
      .catch(() => {
        // Unreachable server: keep the cached guess rather than hiding tabs
        // the parent used yesterday. Their screens report the outage.
      });
    return () => {
      alive = false;
    };
  }, []);

  return features;
}
