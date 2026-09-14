/**
 * A `fetch` that attaches the signed-in user's access token when there is one.
 *
 * Why a module-level getter rather than a React context: the API clients in
 * api.ts and meetup/api.ts are plain async functions called from event
 * handlers, effects and non-component code. Hooks cannot be called from any of
 * those, so the token has to reach them by some route other than the component
 * tree. `AuthProvider` registers the getter on mount and clears it on unmount;
 * everything else just calls `authFetch`.
 *
 * The important property: **an unauthenticated request is a valid request.**
 * Driftway works today with no accounts at all - a meetup runs entirely on the
 * capability tokens in its URLs - and signing in must remain an addition to
 * that, never a precondition. So every failure path here degrades to an
 * anonymous call instead of throwing. A token that cannot be fetched means the
 * user is treated as signed out, which is true, rather than the app breaking.
 */

type TokenGetter = () => Promise<string | null>;

let getToken: TokenGetter | null = null;

/** Called by AuthProvider. `null` clears it, restoring anonymous requests. */
export function provideAccessToken(getter: TokenGetter | null): void {
  getToken = getter;
}

/** The current access token, or null if nobody is signed in. */
export async function currentAccessToken(): Promise<string | null> {
  if (!getToken) return null;
  try {
    return await getToken();
  } catch {
    // Expired session, refresh refused, provider unreachable. All of these
    // mean "not signed in right now", which is a state the app handles.
    return null;
  }
}

export async function authFetch(
  input: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await currentAccessToken();
  if (!token) return fetch(input, init);

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(input, { ...init, headers });
}
