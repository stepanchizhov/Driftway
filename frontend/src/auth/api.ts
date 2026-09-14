/**
 * The account endpoints: who am I, let me in, give me my data, delete me.
 *
 * Every call here goes through authFetch, so the Auth0 bearer token rides
 * along automatically once someone is signed in.
 */

import { authFetch } from "./authFetch";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export interface Account {
  id: string;
  display_name: string | null;
  status: string;
  default_hide_exact_origin: boolean;
}

/** How the deployment's front door is set, per GET /api/health. */
export type RegistrationMode = "closed" | "invite_only" | "open";

export class AccountError extends Error {}

async function detail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    /* no JSON body */
  }
  return fallback;
}

export async function fetchRegistrationMode(): Promise<RegistrationMode> {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (!res.ok) return "invite_only";
    const body = await res.json();
    const mode = body?.registration;
    return mode === "open" || mode === "closed" ? mode : "invite_only";
  } catch {
    // Assume the stricter of the two. Guessing "open" would show a
    // create-account button that the server would then refuse.
    return "invite_only";
  }
}

/**
 * The signed-in user's Driftway account, or null if they have none yet.
 *
 * Signing in to Auth0 and having an account here are different things: the
 * first says who you are, the second says you were admitted. A parent who has
 * signed in but not redeemed an invitation gets null, which is the cue to show
 * the invitation screen rather than an error.
 */
export async function fetchAccount(): Promise<Account | null> {
  const res = await authFetch(`${API_BASE}/api/auth/session`, {
    method: "POST",
  });
  if (res.status === 403 || res.status === 401) return null;
  if (!res.ok) {
    throw new AccountError(await detail(res, "Couldn't check your account."));
  }
  return res.json();
}

/**
 * Redeem an invitation, or create an account outright where registration is
 * open. The server decides which of those is allowed; this just sends what it
 * has and reports what comes back.
 */
export async function redeemInvite(input: {
  inviteToken?: string;
  displayName?: string;
}): Promise<Account> {
  const res = await authFetch(`${API_BASE}/api/auth/accept-beta-invite`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      invite_token: input.inviteToken?.trim() || undefined,
      display_name: input.displayName?.trim() || undefined,
    }),
  });
  if (!res.ok) {
    throw new AccountError(await detail(res, "That didn't work."));
  }
  return res.json();
}

/** Everything held about you, as a file you keep. */
export async function downloadMyData(): Promise<void> {
  const res = await authFetch(`${API_BASE}/api/account/export`);
  if (!res.ok) {
    throw new AccountError(await detail(res, "Couldn't fetch your data."));
  }
  const body = await res.json();

  const url = URL.createObjectURL(
    new Blob([JSON.stringify(body, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `driftway-my-data-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoking immediately can race the download on some browsers; a tick is
  // enough and the object is small.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Delete the account and everything linked to it. Not reversible. */
export async function eraseMyAccount(): Promise<void> {
  const res = await authFetch(`${API_BASE}/api/account`, { method: "DELETE" });
  if (!res.ok) {
    throw new AccountError(await detail(res, "Couldn't delete your account."));
  }
}
