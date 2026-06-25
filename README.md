# Driftway

Duration-first circular route planner for parents whose baby sleeps in the car.
Pick how long you want to drive; get three loops that bring you home.

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
