import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AuthProvider } from "./auth/AuthProvider";
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
