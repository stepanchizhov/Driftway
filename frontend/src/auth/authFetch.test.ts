import { afterEach, describe, expect, it, vi } from "vitest";

import { authFetch, currentAccessToken, provideAccessToken } from "./authFetch";

/**
 * The property these protect: signing in must never become a precondition for
 * using Driftway. Route planning and capability-token meetups worked before
 * accounts existed and have to keep working, so every failure to obtain a
 * token has to degrade to an anonymous request rather than throwing.
 *
 * The inverse matters too - a token that IS available must actually be sent,
 * or the backend silently treats a signed-in parent as a stranger.
 */

function captureFetch() {
  const calls: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal("fetch", (url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    return Promise.resolve(new Response("{}", { status: 200 }));
  });
  return calls;
}

function authHeaderOf(init: RequestInit): string | null {
  return new Headers(init.headers).get("Authorization");
}

afterEach(() => {
  provideAccessToken(null);
  vi.unstubAllGlobals();
});

describe("authFetch", () => {
  it("sends no Authorization header when nobody is signed in", async () => {
    const calls = captureFetch();
    await authFetch("/api/health");
    expect(authHeaderOf(calls[0].init)).toBeNull();
  });

  it("attaches the bearer token when one is available", async () => {
    const calls = captureFetch();
    provideAccessToken(async () => "tok-123");
    await authFetch("/api/auth/session", { method: "POST" });
    expect(authHeaderOf(calls[0].init)).toBe("Bearer tok-123");
  });

  it("preserves headers the caller set", async () => {
    const calls = captureFetch();
    provideAccessToken(async () => "tok-123");
    await authFetch("/api/meetups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const headers = new Headers(calls[0].init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Authorization")).toBe("Bearer tok-123");
  });

  it("falls back to an anonymous request when the token getter throws", async () => {
    const calls = captureFetch();
    provideAccessToken(async () => {
      throw new Error("login_required");
    });
    // An expired session must not break route planning.
    await expect(authFetch("/api/generate")).resolves.toBeDefined();
    expect(authHeaderOf(calls[0].init)).toBeNull();
  });

  it("sends anonymously when the getter resolves null", async () => {
    const calls = captureFetch();
    provideAccessToken(async () => null);
    await authFetch("/api/generate");
    expect(authHeaderOf(calls[0].init)).toBeNull();
  });

  it("stops sending the token once the getter is cleared", async () => {
    const calls = captureFetch();
    provideAccessToken(async () => "tok-123");
    await authFetch("/api/one");
    provideAccessToken(null); // signing out
    await authFetch("/api/two");
    expect(authHeaderOf(calls[0].init)).toBe("Bearer tok-123");
    expect(authHeaderOf(calls[1].init)).toBeNull();
  });
});

describe("currentAccessToken", () => {
  it("is null with no getter registered", async () => {
    await expect(currentAccessToken()).resolves.toBeNull();
  });

  it("swallows a rejecting getter rather than propagating", async () => {
    provideAccessToken(async () => {
      throw new Error("consent_required");
    });
    await expect(currentAccessToken()).resolves.toBeNull();
  });
});
