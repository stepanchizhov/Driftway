# Driftway frontend (Alpha 0)

A mobile-first PWA. Pick a duration and road style, get three circular routes,
tap one to open it in Google Maps.

## Run locally

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 on your computer, or — to test on your phone —
run `npm run dev -- --host` and visit the Network URL it prints from a phone
on the same Wi-Fi.

The dev server proxies `/api` to the backend at `http://localhost:8000`, so
start the backend first (see ../backend/README.md). No CORS setup needed in dev.

## Point at a deployed backend

For a production build talking to your Render backend, set the API base:

```bash
# .env  (or .env.production)
VITE_API_BASE=https://driftway-api.onrender.com
```

Then `npm run build` and deploy the `dist/` folder to any static host
(Netlify, Vercel, Render static site, Cloudflare Pages).

## Install on an Android phone

1. Deploy somewhere with HTTPS (required for PWAs and geolocation).
2. Open the URL in Chrome on the phone.
3. Menu → "Add to Home screen". It launches full-screen like a native app.

## Structure

```
frontend/
  index.html              fonts, manifest link, theme color
  vite.config.ts          dev proxy to the backend
  public/
    manifest.webmanifest  installable PWA metadata
    sw.js                 minimal offline-shell service worker
    icon-192/512.png      app icons (the loop motif)
  src/
    App.tsx               the plan -> results -> feedback flow
    api.ts                backend client
    types.ts              mirrors backend contracts
    hooks/
      useGeolocation.ts   one-tap location, with retry
      useSettings.ts      remembers Home + last choices (localStorage)
    components/
      ChipGroup.tsx       large tappable radio chips
      LoopMark.tsx        draws each route's loop shape (the signature)
      RouteCard.tsx       one result
      SafetyNote.tsx      calm, non-blocking travel-safety note
      Feedback.tsx        "would use again?" + actual duration
    styles.css            design tokens + all styling
```

## Design notes

Calm night-drive direction: deep indigo ground, warm amber accent (dashboard
backlight / streetlight glow). Duration is the hero, in Space Grotesk's
instrument-style numerals. The loop ring is the signature element, echoed in
the app icon and in each route card's drawn shape. Boldness is spent only on
the accent and the ring; everything else stays quiet. Respects
prefers-reduced-motion and has visible keyboard focus.
