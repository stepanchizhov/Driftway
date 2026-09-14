/**
 * Auth0 configuration, read once from the build environment.
 *
 * Mirrors the backend's `is_configured()` in core/identity.py deliberately: a
 * deployment either has a real provider or it does not, and both halves of the
 * app must agree on which. If the frontend thought sign-in existed while the
 * backend did not, the app would offer a button that can only ever fail.
 *
 * All three values are required, and the third is the one people forget.
 * Without `audience`, Auth0 issues an *opaque* access token rather than a JWT -
 * a string the backend cannot verify and cannot even parse. The symptom is a
 * sign-in that appears to succeed followed by every API call returning 401,
 * which reads as a backend bug and is not one. Requiring it here turns that
 * into a visible "not configured" instead.
 */

const domain = (import.meta.env.VITE_AUTH0_DOMAIN ?? "").trim();
const clientId = (import.meta.env.VITE_AUTH0_CLIENT_ID ?? "").trim();
const audience = (import.meta.env.VITE_AUTH0_AUDIENCE ?? "").trim();

export const authConfig = { domain, clientId, audience };

/** True only when a real tenant is behind the sign-in. */
export const authConfigured = Boolean(domain && clientId && audience);
