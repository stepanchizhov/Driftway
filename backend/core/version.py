"""
Which Driftway this is.

APP_VERSION is the release number testers see, the same one the app shows in
Settings. Its history, in words a parent would use, lives with the app in
frontend/src/version.ts; a test fails if the two numbers differ, so a release
bumps both. BUILD names the exact commit running, so "which one am I using?"
has an answer even between releases.

Render sets RENDER_GIT_COMMIT on every deploy. Elsewhere the build is "dev".
"""

import os

APP_VERSION = "0.7.0"


def build() -> str:
    commit = (os.getenv("RENDER_GIT_COMMIT") or "").strip()
    return commit[:7] if commit else "dev"
