import type {
  GenerateRequest,
  GenerateResponse,
  FeedbackRequest,
  FavouriteCreate,
  Favourite,
  Place,
  SearchResponse,
} from "./types";

// In dev, vite proxies /api to localhost:8000 (see vite.config.ts).
// In production, set VITE_API_BASE to your Render URL, e.g.
//   VITE_API_BASE=https://driftway-api.onrender.com
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

// Generating loops means several routing calls with a rate limit between
// them, so allow a generous ceiling before giving up.
const GENERATE_TIMEOUT_MS = 60_000;

const UNREACHABLE =
  "Can't reach the route server. Start the backend " +
  "(cd backend && uvicorn main:app --reload --port 8000) and try again.";

/** Turn an error response into something a human can act on.
 *
 * The old code collapsed every failure into one sentence, so "the backend
 * isn't running" and "no loop fits these settings" looked identical on screen.
 * They need different fixes, so they get different messages.
 */
async function describeFailure(res: Response): Promise<string> {
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    // The Vite dev proxy answers with an empty 500 body when nothing is
    // listening on port 8000 - the single most likely cause in local dev.
    return res.status >= 500 ? UNREACHABLE : `Request failed (${res.status}).`;
  }

  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{ loc: [...], msg: "..." }, ...]
    const msgs = detail
      .map((d) => {
        const field = Array.isArray(d?.loc) ? d.loc.slice(1).join(".") : "";
        return field ? `${field}: ${d?.msg}` : String(d?.msg ?? "");
      })
      .filter(Boolean);
    if (msgs.length) return `The app sent invalid settings - ${msgs.join("; ")}`;
  }
  return `Request failed (${res.status}).`;
}

export async function generateRoutes(
  req: GenerateRequest,
): Promise<GenerateResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
      signal: AbortSignal.timeout(GENERATE_TIMEOUT_MS),
    });
  } catch (e) {
    // Network-level failure: server down, DNS, CORS, or our own timeout.
    if (e instanceof DOMException && e.name === "TimeoutError") {
      throw new Error("Finding loops took too long. Please try again.");
    }
    throw new Error(UNREACHABLE);
  }

  if (!res.ok) throw new Error(await describeFailure(res));
  return res.json();
}

/** Raised when the search provider itself failed, as opposed to finding
 *  nothing. The two need different words on screen: one is "no matches", the
 *  other is "search is down". */
export class SearchFailed extends Error {}

/**
 * Look up addresses, UK postcodes and named places.
 *
 * The key lives on the backend, so this goes through our own /api/search.
 * Pass the caller's AbortSignal: the picker fires a request per keystroke
 * burst and must be able to drop the ones it no longer wants.
 */
export async function searchPlaces(
  query: string,
  near: { lat: number; lng: number } | null,
  signal?: AbortSignal,
): Promise<Place[]> {
  const params = new URLSearchParams({ q: query });
  if (near) {
    params.set("lat", String(near.lat));
    params.set("lng", String(near.lng));
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/search?${params}`, { signal });
  } catch (e) {
    // An abort is the caller changing its mind, not a failure. Re-throw it
    // unchanged so the picker can ignore it.
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new SearchFailed("Couldn't reach the address search.");
  }

  if (!res.ok) {
    throw new SearchFailed(
      res.status === 503
        ? "Address search is unavailable right now."
        : `Address search failed (${res.status}).`,
    );
  }
  const body: SearchResponse = await res.json();
  return body.places;
}

export async function sendFeedback(fb: FeedbackRequest): Promise<void> {
  try {
    await fetch(`${API_BASE}/api/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fb),
    });
  } catch {
    // Feedback is best-effort in the alpha; never block the UI on it.
  }
}

export async function listFavourites(owner: string): Promise<Favourite[]> {
  const res = await fetch(
    `${API_BASE}/api/favourites?owner=${encodeURIComponent(owner)}`,
  );
  if (!res.ok) return [];
  return res.json();
}

export async function saveFavourite(fav: FavouriteCreate): Promise<Favourite | null> {
  try {
    const res = await fetch(`${API_BASE}/api/favourites`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fav),
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function deleteFavourite(id: string, owner: string): Promise<void> {
  try {
    await fetch(
      `${API_BASE}/api/favourites/${id}?owner=${encodeURIComponent(owner)}`,
      { method: "DELETE" },
    );
  } catch {
    /* best-effort */
  }
}
