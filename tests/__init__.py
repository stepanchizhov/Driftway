"""Driftway test suite. Run: python -m unittest discover -s tests -t .
"""

import os

# main.py loads backend/.env, which on a developer's machine can hold a real
# openrouteservice key. Set it empty first - load_dotenv never overrides a
# variable that is already set - so no test can reach the live provider by
# accident. Tests that need a key set "test-key" with a mocked transport.
os.environ["ORS_API_KEY"] = ""
