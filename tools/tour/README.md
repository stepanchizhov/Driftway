# The tour video

The one-minute tour on `/welcome.html` (`frontend/public/media/driftway-tour.mp4`,
made 18 Oct 2026, 0.8.19). It's built from the app's own screens, captured from a
local run against the live providers. It shows public places in Windsor only;
"Home" is a stand-in on Datchet's village green. It has no sound.

To remake it after the screens change:

1. Run the backend and frontend locally with a scratch database, walks and
   Meet up on, and sign-in off:

   ```powershell
   # backend\ : a throwaway database, never the real one
   $env:DATABASE_URL = "sqlite:///$env:TEMP/tour.db"; $env:WALKING_ENABLED = "true"
   $env:MEET_HALFWAY_ENABLED = "true"; $env:AUTH0_DOMAIN = ""; $env:AUTH0_AUDIENCE = ""
   python -m uvicorn main:app --port 8000
   # frontend\ : sign-in off, so the Account block isn't shown
   $env:VITE_AUTH0_DOMAIN = ""; $env:VITE_AUTH0_CLIENT_ID = ""; $env:VITE_CANONICAL_ORIGIN = ""
   npx vite --port 5173
   ```

   Vite doesn't always notice edits in this OneDrive folder: restart it after
   changing the app.

2. With no Street Manager data, cards say none has arrived. Production has
   data, so store one permit far from Windsor first, as `core.roadworks.store_permit`
   would from a real message. The capture of 18 Oct used one in Manchester.

3. In this folder: `npm i playwright@1.64.1`, then:

   ```
   node capture.mjs drive    # Still asleep, Plan a drive, Arrive by, Settings
   node capture.mjs walk     # Walk and Meet up (needs openrouteservice answering)
   node render.mjs stills 5 12 22 37    # a look at a few moments
   node render.mjs frames                # every frame, 30 fps, about 5 minutes
   ffmpeg -framerate 30 -i frames/f%05d.png -vf scale=720:1280:flags=lanczos -c:v libx264 -preset slow -crf 23 -pix_fmt yuv420p -movflags +faststart -tune stillimage driftway-tour.mp4
   ```

   `capture.mjs` freezes the page clock at 10:12, so "Arrive by 10:55" is 43
   minutes away. `stage.html` holds the story: captions, which screen when, the
   taps and close-ups. `shots/boxes.json` gives the tap positions.

Screens from a real phone are not used: Google Maps there shows the owner's
saved places and position.
