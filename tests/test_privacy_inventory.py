"""
The privacy policy must name every outside service Driftway sends data to.

Founder request, 10 Oct 2026: keep the privacy page current when something
crucial changes, such as a new provider. A note in a document is easy to
forget, so this fails the build instead. Every outside host that the app's
running code mentions must be either:

  * a data recipient - listed in RECIPIENTS with the name the privacy page
    uses for it, and that name must appear in frontend/public/privacy.html;
  * or not a recipient - a documentation link, an attribution link, or a page
    the parent opens themselves - listed in NOT_RECIPIENTS with the reason.

A new host in neither list fails this test. Before adding it to either list,
decide which it is. If Driftway sends it anything, update privacy.html: what
it receives and why, plus the version and date at the top. Update the Data
safety answers in docs/DATA_SAFETY.md too.

Curation-only tools (backend/tools: Overpass, Open Topo Data) run on a
developer's machine, never for a user, and are not scanned.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNED = [ROOT / "backend" / "core", ROOT / "backend" / "routes", ROOT / "backend" / "main.py",
           ROOT / "frontend" / "src", ROOT / "frontend" / "index.html"]
PRIVACY = ROOT / "frontend" / "public" / "privacy.html"

#: Host (or host suffix) -> the name privacy.html uses for it.
RECIPIENTS = {
    "api.tomtom.com": "TomTom",
    "api.heigit.org": "openrouteservice",
    "tile.openstreetmap.org": "OpenStreetMap",
    "fonts.googleapis.com": "Google Fonts",
    "fonts.gstatic.com": "Google Fonts",
    "auth0.com": "Auth0",
    "onrender.com": "Render",
    # Opened by the parent's choice, with the route's points in the link.
    "www.google.com": "Google Maps",
    "waze.com": "Waze",
    "maps.apple.com": "Apple Maps",
}

#: Hosts mentioned only as links or references, never sent user data.
NOT_RECIPIENTS = {
    "www.openstreetmap.org": "attribution link (copyright page)",
    "wiki.openstreetmap.org": "documentation reference in comments",
    "giscience.github.io": "openrouteservice documentation in comments",
    "developers.google.com": "Google Maps URL documentation in comments",
    "developer.apple.com": "Apple Maps URL documentation in comments",
    "github.com": "repository link in a User-Agent string",
    "www.lullabytrust.org.uk": "safety guidance link the parent may open",
}

_HOST = re.compile(r"https?://([a-zA-Z0-9.-]+\.[a-z]{2,})")


def hosts_in_code():
    found = {}
    for base in SCANNED:
        files = [base] if base.is_file() else [p for p in base.rglob("*")
                                               if p.suffix in (".py", ".ts", ".tsx", ".html")]
        for f in files:
            if ".test." in f.name:
                continue
            for host in _HOST.findall(f.read_text(encoding="utf-8")):
                found.setdefault(host.lower(), f.relative_to(ROOT).as_posix())
    return found


def _known(host, table):
    return next((k for k in table if host == k or host.endswith("." + k)), None)


class PrivacyInventoryTests(unittest.TestCase):
    def test_every_outside_host_is_declared(self):
        unknown = {h: where for h, where in hosts_in_code().items()
                   if not _known(h, RECIPIENTS) and not _known(h, NOT_RECIPIENTS)}
        self.assertEqual(unknown, {}, (
            "New outside host(s) in the app's code. If Driftway sends any data "
            "to one, name it in frontend/public/privacy.html (what it receives "
            "and why; bump the version and date) and in docs/DATA_SAFETY.md, "
            "then add it to RECIPIENTS in this test. If it is only a link or a "
            "comment, add it to NOT_RECIPIENTS with the reason."))

    def test_every_recipient_is_named_in_the_privacy_policy(self):
        page = PRIVACY.read_text(encoding="utf-8")
        missing = sorted({name for name in RECIPIENTS.values() if name not in page})
        self.assertEqual(missing, [], "privacy.html does not name: " + ", ".join(missing))

    def test_the_policy_names_who_runs_driftway_and_how_to_reach_them(self):
        page = PRIVACY.read_text(encoding="utf-8")
        self.assertIn("iBookBinding Ltd", page)
        self.assertIn("stepan@ibookbinding.com", page)
        self.assertIn("/delete-account.html", page)


if __name__ == "__main__":
    unittest.main()
