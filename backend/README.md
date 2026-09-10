# Driftway backend (Alpha 0)

Duration-first circular route generator. Generates candidate loops, evaluates
them through a traffic-aware routing provider, scores them, and returns the
best three with a Google Maps handoff URL.

## Run locally (no API key needed)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # ROUTING_PROVIDER=mock by default
uvicorn main:app --reload --port 8000
```

Then open http://localhost:8000/docs for the interactive API.

Quick test:
```bash
curl -X POST localhost:8000/api/generate -H "Content-Type: application/json" \
  -d '{"start":{"lat":53.279,"lng":-2.897},"target_minutes":30,"road_profile":"mixed"}'
```

## Route modes

Two shapes of request, both through `POST /api/generate`:

- **Round trip** — `finish` equals `start` (or is omitted). Returns loops.
- **Go somewhere** — `finish` is a different place. `target_minutes` is the
  **total** journey time, not extra time on top of the direct route. The direct
  drive is measured first and acts as a floor: ask for less than it takes and
  the response explains why and returns the direct route with `is_direct: true`.

The server decides the mode from the coordinates; the optional `mode` field in
the request is advisory and only appears in the logs when the two disagree.

See `docs/ROUTE_MODES.md` for the full behaviour.

## Address search

`GET /api/search?q=...&lat=...&lng=...` proxies TomTom Fuzzy Search so the API
key stays on the server. Set `SEARCH_PROVIDER` to override `ROUTING_PROVIDER`
for search alone. With no key it falls back to a handful of built-in sample
places so the picker still works offline.

## Switch to real TomTom routing

1. Get a free key at https://developer.tomtom.com (Freemium: 2,500 free
   non-tile requests/day, no card required).
2. In `.env` set:
   ```
   ROUTING_PROVIDER=tomtom
   TOMTOM_API_KEY=your_key_here
   ```
3. Restart. No code changes needed.

**Note:** with `ROUTING_PROVIDER=mock` every route is marked `simulated` and
carries an empty `maps_url` — simulated geometry is never handed to a
navigation app. The pipeline runs end to end, but you need a real key to
exercise the Google Maps export.

## Deploy to Render

Push to GitHub, then in Render: **New > Blueprint** and select the repo
(uses `render.yaml`). Set `TOMTOM_API_KEY` in the dashboard, and update
`ALLOWED_ORIGINS` to your PWA's URL once the frontend is deployed.

## Structure

```
backend/
  main.py              FastAPI app + CORS
  routes/api.py        /api/generate, /api/feedback, /api/health
  core/
    models.py          request/response contracts (the frontend depends on these)
    geometry.py        geodesic maths + loop shape templates
    router.py          provider-neutral adapter (MockRouter / TomTomRouter)
    scorer.py          validation + scoring + dedupe
    generator.py       the 7-step pipeline + Google Maps URL builder
```

## Notes / things to tune from real rides

- Profile seed speeds and `LOOP_RADIUS_FACTOR` in `geometry.py` are guesses.
- Scoring weights in `scorer.py` are the project-bible hypotheses.
- TomTom road-class mix is coarse (inferred from profile). Replace with
  section analysis once we know which signal predicts "would use again".
- Feedback currently logs only; wire to Render Postgres for closed beta.
