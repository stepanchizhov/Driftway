import type {
  GenerateRequest,
  GenerateResponse,
  FeedbackRequest,
} from "./types";

// In dev, vite proxies /api to localhost:8000 (see vite.config.ts).
// In production, set VITE_API_BASE to your Render URL, e.g.
//   VITE_API_BASE=https://driftway-api.onrender.com
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export async function generateRoutes(
  req: GenerateRequest,
): Promise<GenerateResponse> {
  const res = await fetch(`${API_BASE}/api/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    // The backend returns a helpful message in `detail` for 422s.
    let detail = "Could not generate routes. Please try again.";
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore parse error, use default */
    }
    throw new Error(detail);
  }
  return res.json();
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
