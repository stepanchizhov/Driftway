"""
The scheduled walk-area job (core/walking/areas.py; founder decision, 11 Oct
2026: GitHub Actions, AI descriptions only after the founder approves them).

    python -m tools.walk_area_job

Each run:
  1. takes up to MAX_AREAS queued areas from the API, builds the walking
     routes mapped in each into curated walks (tools/import_osm_routes.py,
     with its faithfulness gate), uploads those that pass, and marks the
     area ready, empty or failed with a note;
  2. writes a short description for up to MAX_DESCRIPTIONS walks that have
     none, from that walk's own data, with Anthropic's Claude. Each is
     checked here (plain text, length, no number the walk's data doesn't
     contain) and uploaded as pending: nobody sees it until the founder
     approves it.

Settings, from the environment (GitHub Actions secrets and variables):
  API                 the Driftway API, default https://driftway.onrender.com
  WALKS_JOB_TOKEN     the job's own token (same value as on the API)
  Anthropic access, either (preferred, founder 12 Oct 2026) Workload
  Identity Federation, with no key stored anywhere: the workflow grants
  `id-token: write`, and these four repository variables (IDs, not secrets)
  name the Console's federation rule:
    ANTHROPIC_FEDERATION_RULE_ID, ANTHROPIC_ORGANIZATION_ID,
    ANTHROPIC_SERVICE_ACCOUNT_ID, ANTHROPIC_WORKSPACE_ID
  or, as a fallback, ANTHROPIC_API_KEY. With neither, step 2 is skipped.
  DESCRIPTION_MODEL   default claude-sonnet-5-5
  MAX_AREAS, MAX_DESCRIPTIONS   per-run caps, default 3 and 20

The job sends Anthropic only public map facts about a walk (name, length,
surfaces, gates, slopes, operator). Nothing about any person.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.import_osm_routes import import_area  # noqa: E402

API = os.getenv("API", "https://driftway.onrender.com").rstrip("/")
MODEL = os.getenv("DESCRIPTION_MODEL", "claude-sonnet-5-5")
MAX_AREAS = int(os.getenv("MAX_AREAS", "3"))
MAX_DESCRIPTIONS = int(os.getenv("MAX_DESCRIPTIONS", "20"))
DESCRIPTION_MAX = 450

SYSTEM = (
    "You write short descriptions of walks for Driftway, an app for parents "
    "walking with a pram, with a baby carrier, or on their own. Use only the "
    "facts given. Never add a fact, place, feature, view, facility or "
    "opinion that isn't in them, and never say a walk is safe, easy or "
    "suitable: the app judges that separately. If something isn't recorded, "
    "leave it out. Plain British English, two or three sentences, under "
    f"{DESCRIPTION_MAX} characters. No marketing language, no exclamation "
    "marks, no emoji, no markdown. Write only the description."
)


class ApiRefused(RuntimeError):
    pass


#: What a refusal from the API means for whoever reads the run's summary.
_MEANING = {
    403: "the API refused the job's token: WALKS_JOB_TOKEN must be exactly the "
         "same in the GitHub secret and on the Render API (check for a missing "
         "or extra character), and Render must have restarted since it was set",
    503: "the API says the walk-area job isn't configured there, or its "
         "database is unavailable: set WALKS_JOB_TOKEN on the Render API",
    404: "the API doesn't have the walk-area endpoints: is it running 0.8.9 or later?",
}


def _call(method: str, path: str, body: Optional[Dict] = None, token: str = "") -> object:
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "X-Walks-Job-Token": token,
                 "User-Agent": "Driftway-walk-area-job (+https://github.com/stepanchizhov/Driftway)"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise ApiRefused(f"{method} {path}: {e.code} {detail}. "
                         + _MEANING.get(e.code, "see the API's logs")) from None
    except urllib.error.URLError as e:
        raise ApiRefused(f"{method} {path}: couldn't reach {API} ({e.reason})") from None


# ------------------------------------------------------------------ areas

def process_areas(token: str) -> None:
    areas = _call("GET", f"/api/admin/walk-areas?status=queued&limit={MAX_AREAS}", token=token)
    print(f"{len(areas)} queued area(s)")
    for area in areas:
        cell = area["cell"]
        s, w, n, e = area["bbox"]
        print(f"\narea {cell} ({area['requests']} request(s))")
        work = tempfile.mkdtemp(prefix="walks-")
        try:
            results = import_area(s, w, n, e, specs_dir=os.path.join(work, "specs"),
                                  out_dir=os.path.join(work, "walks"), force=True, broad=True)
        except Exception as ex:  # noqa: BLE001
            _call("POST", f"/api/admin/walk-areas/{cell}",
                  {"status": "failed", "note": f"{type(ex).__name__}: {ex}"[:1000]}, token)
            print(f"  failed: {type(ex).__name__}")
            continue
        built = 0
        for r in results:
            if r["status"] != "built":
                continue
            with open(r["out"], encoding="utf-8") as f:
                route = json.load(f)
            _call("PUT", f"/api/admin/curated-walks/{route['id']}",
                  {"cell": cell, "source": f"osm_relation:{r['relation']}", "route": route}, token)
            built += 1
        note = "; ".join(f"{r['status']}: {r['id'] or ''} {r['reason']}".strip() for r in results)
        _call("POST", f"/api/admin/walk-areas/{cell}",
              {"status": "ready" if built else "empty",
               "note": (f"{built} built. " + note)[:4000]}, token)
        print(f"  {built} walk(s) uploaded")


# ------------------------------------------------------------ descriptions

def facts_of(route: Dict) -> Dict:
    """The walk's own data, assessed for each way of going, as plain facts."""
    from core.walking.catalogue import assess_route, route_from_dict
    from core.walking.profiles import CarrierSetup, PramSetup
    r = route_from_dict(route)
    judged = {
        "pram": assess_route(r, "pram", PramSetup(wheels="standard", width_cm=None, double=False)),
        "carrier": assess_route(r, "carrier", CarrierSetup(kind="soft", child_kg=None, carrier_kg=None,
                                                          luggage_kg=None, luggage_with="carrier_adult")),
        "on foot": assess_route(r, "walker", None),
    }
    walker = judged["on foot"]
    surfaces: Dict[str, float] = {}
    for s in r.sections:
        surfaces[s.surface.value] = surfaces.get(s.surface.value, 0) + (s.to_m - s.from_m)
    total = sum(surfaces.values()) or 1
    return {
        "name": route["name"],
        "area": route.get("area") or None,
        "summary": route.get("summary"),
        "shape": "circular" if route.get("shape") == "loop" else "there and back",
        "length_km": round(walker["distance_m"] / 1000, 1),
        "climb_m": walker["ascent_m"],
        "surfaces_percent": {k: round(100 * v / total) for k, v in sorted(surfaces.items(), key=lambda kv: -kv[1])},
        "start": route["start"].get("label"),
        "verdicts": {k: v["verdict"] for k, v in judged.items()},
        "things_to_know": sorted({f["reason"] for v in judged.values()
                                  for f in v["blocking"] + v["difficult"] + v["notes"]})[:12],
        "notes": route.get("notes", [])[:4],
    }


def check(text: str, facts: Dict) -> Optional[str]:
    """Why this description can't go to review, or None."""
    if not 40 <= len(text) <= DESCRIPTION_MAX + 50:
        return f"length {len(text)}"
    if re.search(r"[<>#*`]|\bhttps?://", text):
        return "markup or a link"
    known = json.dumps(facts)
    for num in re.findall(r"\d+(?:\.\d+)?", text):
        if num not in known:
            return f"the number {num} isn't in the walk's data"
    return None


# ------------------------------------------------- Anthropic access

class AnthropicAccess:
    """Headers for the Claude API: a short-lived token from Workload Identity
    Federation (GitHub's OIDC token exchanged at /v1/oauth/token), refreshed
    before it expires; or the API key, if that is what is configured."""

    AUDIENCE = "https://api.anthropic.com"

    def __init__(self) -> None:
        self.key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        self.fed = {k: (os.getenv(f"ANTHROPIC_{k.upper()}") or "").strip()
                    for k in ("federation_rule_id", "organization_id",
                              "service_account_id", "workspace_id")}
        self.token, self.expires = "", 0.0

    @property
    def federated(self) -> bool:
        return all(self.fed[k] for k in ("federation_rule_id", "organization_id",
                                         "service_account_id"))

    @property
    def available(self) -> bool:
        return bool(self.key) or self.federated

    def _github_jwt(self) -> str:
        url = os.getenv("ACTIONS_ID_TOKEN_REQUEST_URL")
        bearer = os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
        if not url or not bearer:
            raise RuntimeError("no GitHub identity token: the workflow needs "
                               "permissions: id-token: write")
        req = urllib.request.Request(url + "&audience=" + urllib.parse.quote(self.AUDIENCE, safe=""),
                                     headers={"Authorization": f"Bearer {bearer}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["value"]

    def _exchange(self) -> None:
        body = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": self._github_jwt(), **{k: v for k, v in self.fed.items() if v}}
        req = urllib.request.Request("https://api.anthropic.com/v1/oauth/token", method="POST",
                                     data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                out = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Anthropic refused the federated sign-in ({e.code}); its reason "
                               "is on the Console's Workload identity history page") from None
        self.token = out["access_token"]
        self.expires = time.monotonic() + float(out.get("expires_in", 600))

    def headers(self) -> Dict[str, str]:
        if self.key:
            return {"x-api-key": self.key}
        if time.monotonic() > self.expires - 120:      # refresh two minutes early
            self._exchange()
        return {"authorization": f"Bearer {self.token}"}


def describe(facts: Dict, access: "AnthropicAccess") -> str:
    body = {"model": MODEL, "max_tokens": 300, "system": SYSTEM,
            "messages": [{"role": "user", "content":
                          "Facts about the walk, as JSON:\n" + json.dumps(facts, ensure_ascii=False)
                          + "\n\nWrite the description."}]}
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", method="POST", data=json.dumps(body).encode(),
        headers={**access.headers(), "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        out = json.loads(resp.read())
    return "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text").strip()


def process_descriptions(token: str, access: "AnthropicAccess") -> None:
    walks = _call("GET", f"/api/admin/curated-walks?description_status=none&limit={MAX_DESCRIPTIONS}",
                  token=token)
    print(f"\n{len(walks)} walk(s) without a description")
    for w in walks:
        facts = facts_of(w["route"])
        try:
            text = describe(facts, access)
        except urllib.error.HTTPError as e:
            print(f"  {w['id']}: Anthropic said {e.code}; stopping descriptions for this run")
            return
        problem = check(text, facts)
        if problem:
            print(f"  {w['id']}: not uploaded ({problem})")
            continue
        try:
            _call("POST", f"/api/admin/curated-walks/{w['id']}/description",
                  {"text": text, "model": MODEL}, token)
        except ApiRefused as e:
            print(f"::warning title=Walk descriptions::{w['id']}: {e}")
            continue
        print(f"  {w['id']}: description awaiting approval")


def main() -> None:
    token = (os.getenv("WALKS_JOB_TOKEN") or "").strip()
    if not token:
        raise SystemExit("WALKS_JOB_TOKEN is not set.")
    access = AnthropicAccess()
    if access.federated and not access.key:
        # Sign in once at the start: shows at once whether federation works
        # (and passes the Console's connection test even with nothing to
        # describe), before any long build.
        try:
            access.headers()
            print("Anthropic: signed in with workload identity federation")
        except Exception as e:  # noqa: BLE001
            print(f"::warning title=Walk descriptions::{e}")
            access = None
    try:
        process_areas(token)
    except ApiRefused as e:
        # An annotation, so it shows on the run's summary page, not only in
        # the step's log (first run, 12 Oct 2026: just "exit code 1").
        print(f"::error title=Walk areas::{e}")
        raise SystemExit(1)
    if access is not None and access.available:
        process_descriptions(token, access)
    else:
        print("\nNo Anthropic access configured: no descriptions this run.")


if __name__ == "__main__":
    main()
