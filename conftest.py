"""Pytest config: ensure main.py can be imported in test environments.

main.py uses fail-fast startup — it raises RuntimeError if GEMINI_API_KEY
is unset. Tests run in CI where the real key isn't (and shouldn't be)
present, so we set a dummy value before any test module imports `main`.

The dummy key is never actually sent to Google because every test
monkeypatches `main.client` with a MockClient before hitting /chat.
"""

import os

# Must be set BEFORE pytest collects test_main.py (which imports main at
# module load). conftest.py is executed by pytest before test collection,
# so this is the right hook.
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real-do-not-send-to-google")
