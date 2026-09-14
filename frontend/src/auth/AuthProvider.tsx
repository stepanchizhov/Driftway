import { useEffect, type ReactNode } from "react";
import {
  Auth0Provider,
  useAuth0,
  type AppState,
} from "@auth0/auth0-react";

import { authConfig, authConfigured } from "./config";
import { provideAccessToken } from "./authFetch";

/**
 * Sign-in, wrapped so the rest of the app never has to know whether it exists.
 *
 * When no tenant is configured this renders its children untouched and
 * registers no token getter, so the app behaves exactly as it did before
 * accounts existed. That is not a development convenience - it is the same
 * staged rollout the backend does, where core/identity.py reports itself
 * unconfigured and /api/health says "staging" rather than quietly pretending.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  if (!authConfigured) return <>{children}</>;

  return (
    <Auth0Provider
      domain={authConfig.domain}
      clientId={authConfig.clientId}
      onRedirectCallback={onRedirectCallback}
      authorizationParams={{
        redirect_uri: window.location.origin,
        // Without this the token is opaque and the backend cannot verify it.
        audience: authConfig.audience,
      }}
      // Refresh tokens rather than hidden-iframe silent auth. Safari and
      // Firefox block the third-party cookies that iframe approach depends on,
      // and Driftway is a mobile-first PWA - a parent on an iPhone is the
      // common case, not the edge one. Requires "Allow Offline Access" on the
      // API in the Auth0 dashboard.
      useRefreshTokens={true}
      // Survives a reload and an app relaunch from the home screen. The
      // trade-off is real: localStorage is readable by any script that gets
      // injected into the page, where the in-memory default is not. It is
      // accepted here because the alternative is signing in again every time
      // the PWA is reopened, and because rotation (enabled in the dashboard)
      // means a stolen refresh token is single-use and its reuse is detected.
      cacheLocation="localstorage"
    >
      <TokenBridge />
      {children}
    </Auth0Provider>
  );
}

/**
 * Hand the SDK's token getter to the plain-function API clients.
 *
 * Renders nothing. It exists because `getAccessTokenSilently` is only
 * reachable from a hook, and api.ts is not a component.
 */
function TokenBridge() {
  const { isAuthenticated, getAccessTokenSilently } = useAuth0();

  useEffect(() => {
    if (!isAuthenticated) {
      provideAccessToken(null);
      return;
    }
    // The SDK's return type admits undefined; authFetch treats a missing
    // token as "signed out" and sends the request anonymously.
    provideAccessToken(async () => (await getAccessTokenSilently()) ?? null);
    return () => provideAccessToken(null);
  }, [isAuthenticated, getAccessTokenSilently]);

  return null;
}

/**
 * Put the user back exactly where they were before signing in.
 *
 * The SDK's default replaces the URL with `window.location.pathname` alone,
 * which would silently drop the query string - and Driftway keeps its whole
 * meetup state there (`?meetup=<id>&join=<token>`, see MeetHalfway.tsx). A
 * parent following an invite link, signing in, and landing on an empty home
 * screen would have no way back other than re-opening the original message.
 */
function onRedirectCallback(appState?: AppState): void {
  window.history.replaceState(
    {},
    document.title,
    appState?.returnTo ?? withoutAuthParams(window.location.href),
  );
}

/**
 * The current URL minus the parameters Auth0 appended on the way back.
 *
 * Used as the fallback when there is no `returnTo` - reading
 * `window.location.search` raw at this point would preserve `?code=&state=`
 * and leave the grant sitting in the address bar, in the history, and in
 * anything the user pastes to someone else.
 */
function withoutAuthParams(href: string): string {
  const url = new URL(href);
  for (const key of ["code", "state", "error", "error_description"]) {
    url.searchParams.delete(key);
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * What the rest of the app uses instead of `useAuth0` directly.
 *
 * `signIn` records where the user was so they come back to it; see
 * onRedirectCallback. `signOut` returns them to the app's own origin, which
 * must be listed in Allowed Logout URLs in the dashboard or Auth0 refuses the
 * redirect.
 */
export function useDriftwayAuth() {
  const { isAuthenticated, isLoading, user, loginWithRedirect, logout } =
    useAuth0();

  return {
    configured: authConfigured,
    isAuthenticated,
    isLoading,
    user,
    signIn: () =>
      loginWithRedirect({
        appState: { returnTo: withoutAuthParams(window.location.href) },
      }),
    signOut: () =>
      logout({ logoutParams: { returnTo: window.location.origin } }),
  };
}
