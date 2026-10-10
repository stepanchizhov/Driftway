import { authFetch } from "./auth/authFetch";
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
): Promise<{ places: Place[]; provider: string }> {
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
  // The provider is returned so results from the stand-in can carry its
  // attribution, which its terms require wherever they are shown.
  return { places: body.places, provider: body.provider ?? "" };
}

export async function sendFeedback(fb: FeedbackRequest): Promise<void> {
  try {
    await authFetch(`${API_BASE}/api/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fb),
    });
  } catch {
    // Feedback is best-effort in the alpha; never block the UI on it.
  }
}

export class AuthExpired extends Error {}

export async function listFavourites(owner: string): Promise<Favourite[]> {
  const res = await authFetch(
    `${API_BASE}/api/favourites?owner=${encodeURIComponent(owner)}`,
  );
  // A rejected credential is not "no saved places". Swallowing it here would
  // show an empty list to someone whose session merely expired, which reads
  // as data loss.
  if (res.status === 401) throw new AuthExpired(await describeFailure(res));
  if (!res.ok) return [];
  return res.json();
}

export async function saveFavourite(fav: FavouriteCreate): Promise<Favourite | null> {
  let res: Response;
  try {
    res = await authFetch(`${API_BASE}/api/favourites`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fav),
    });
  } catch {
    return null; // offline; saving is best-effort
  }
  // The server refuses rather than filing this under a device id the parent
  // will never see again. Surface that instead of pretending it saved - and
  // do not retry, which would risk a duplicate once the session is renewed.
  if (res.status === 401) throw new AuthExpired(await describeFailure(res));
  if (!res.ok) return null;
  return res.json();
}

/**
 * Move this device's saved places onto the signed-in account.
 *
 * Deliberately a separate, user-initiated call rather than something that
 * happens on sign-in: a browser can be shared, and absorbing whatever is on it
 * into whoever signed in most recently would attach one parent's saved drives
 * to another parent's account.
 */
export async function claimFavourites(owner: string): Promise<Favourite[]> {
  const res = await authFetch(
    `${API_BASE}/api/favourites/claim?owner=${encodeURIComponent(owner)}`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await describeFailure(res));
  return res.json();
}

export async function deleteFavourite(id: string, owner: string): Promise<void> {
  try {
    await authFetch(
      `${API_BASE}/api/favourites/${id}?owner=${encodeURIComponent(owner)}`,
      { method: "DELETE" },
    );
  } catch {
    /* best-effort */
  }
}
