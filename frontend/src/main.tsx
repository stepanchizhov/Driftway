import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AuthProvider } from "./auth/AuthProvider";
// Fonts are served with the app rather than from Google Fonts (0.8): one
// less outside service receiving testers' IP addresses, a faster first
// paint, and type that works offline in the Android app. OFL-1.1.
import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/600.css";
import "@fontsource/space-grotesk/700.css";
import "@fontsource/hanken-grotesk/400.css";
import "@fontsource/hanken-grotesk/500.css";
import "@fontsource/hanken-grotesk/600.css";
import "@fontsource/hanken-grotesk/700.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </StrictMode>,
);

// Register the service worker so the app is installable on Android.
// Vite serves /sw.js from the public folder.
//
// Production only. In development the worker caches every module it sees, so
// the moment the dev server hiccups the browser starts serving yesterday's
// bundle and the app appears not to have changed - a genuinely confusing hour
// to debug. Any worker registered by an earlier dev session is torn down here
// so it cannot keep haunting localhost.
if ("serviceWorker" in navigator) {
  if (import.meta.env.PROD) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* SW is a progressive enhancement; ignore failures */
      });
    });
  } else {
    void navigator.serviceWorker
      .getRegistrations()
      .then((regs) => regs.forEach((r) => void r.unregister()))
      .catch(() => {
        /* nothing registered, or storage unavailable */
      });
    void caches
      ?.keys()
      .then((keys) => keys.forEach((k) => void caches.delete(k)))
      .catch(() => {});
  }
}
