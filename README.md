# Driftway

Duration-first route planner for parents whose baby sleeps in the car.

Two modes:

- **Round trip** — pick how long you want to drive; get loops that bring you
  back exactly where you started.
- **Go somewhere** — pick a start, a destination and a total journey time; get
  routes that take about that long and still end where you asked. "The pool is
  25 minutes from home, but I want a 60-minute drive."

Both accept addresses, UK postcodes and named places, so a drive can be planned
before setting off.

This repo has two parts:

- `backend/`  — FastAPI route generator (mock router by default, TomTom-ready)
- `frontend/` — React + TypeScript PWA

See each folder's README to run them. Quick start:

```bash
# terminal 1 — backend
cd backend && pip install -r requirements.txt && python -m uvicorn main:app --reload

# terminal 2 — frontend
cd frontend && npm install && npm run dev
```

Then open http://localhost:5173. The backend runs on mock routing until you add
a TomTom key (set ROUTING_PROVIDER=tomtom and TOMTOM_API_KEY in backend/.env).

Status: Alpha 0 — built to be tested on a real drive, not to be pretty in a demo.
