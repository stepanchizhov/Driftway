import { useState } from "react";

// A stable, anonymous per-device id. No account, no personal data — just a
// random token so favourites and feedback can be grouped by device. Persisted
// in localStorage. (When real accounts arrive much later, this becomes the
// fallback for signed-out use.)
const KEY = "driftway.owner.v1";

function loadOrCreate(): string {
  try {
    const existing = localStorage.getItem(KEY);
    if (existing) return existing;
    const id = "d-" + Math.random().toString(36).slice(2, 12);
    localStorage.setItem(KEY, id);
    return id;
  } catch {
    // storage unavailable (private mode): use an ephemeral id for the session
    return "d-ephemeral";
  }
}

export function useOwner(): string {
  const [owner] = useState<string>(loadOrCreate);
  return owner;
}
