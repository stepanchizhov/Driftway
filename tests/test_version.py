"""
One version number for the release, shown by both halves of the app.

Founder request, 10 Oct 2026: testers must be able to tell which version they
are using. The app's number is the newest entry of its release history
(frontend/src/version.ts); the server's is backend/core/version.py. This
fails the moment a release bumps one and not the other.
"""

import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


class VersionTests(unittest.TestCase):
    def test_app_and_server_carry_the_same_version(self):
        from core.version import APP_VERSION
        text = (ROOT / "frontend" / "src" / "version.ts").read_text(encoding="utf-8")
        newest = re.search(r'version:\s*"([^"]+)"', text).group(1)
        self.assertEqual(newest, APP_VERSION)

    def test_the_build_is_the_deployed_commit_or_dev(self):
        from core import version
        with mock.patch.dict(os.environ, {"RENDER_GIT_COMMIT": "39dbfdc0123456789"}):
            self.assertEqual(version.build(), "39dbfdc")
        with mock.patch.dict(os.environ, {"RENDER_GIT_COMMIT": ""}):
            self.assertEqual(version.build(), "dev")

    def test_health_reports_version_and_build(self):
        from test_identity_auth0 import _fresh
        from core.version import APP_VERSION
        client, _ = _fresh()
        try:
            body = client.get("/api/health").json()
        finally:
            client.close()
        self.assertEqual(body["version"]["app"], APP_VERSION)
        self.assertIn("build", body["version"])


if __name__ == "__main__":
    unittest.main()
