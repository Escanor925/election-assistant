import os
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_get_root_serves_html():
    """Verify the GET / endpoint correctly serves the HTML page (returns 200)."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Voter Education Assistant" in response.text
    # Check for accessibility enhancements
    assert "aria-label" in response.text
    assert "role=\"banner\"" in response.text

def test_post_chat_returns_mock_data(monkeypatch):
    """Verify the POST /chat endpoint returns a 200 status code with mock data."""
    # Create a mock structure for the Gemini client
    class MockResponse:
        text = "Mocked Voter Education Response: To register, fill out Form 6."
    
    class MockModels:
        def generate_content(self, **kwargs):
            return MockResponse()
            
    class MockClient:
        models = MockModels()

    # Apply the mock to the 'client' in 'main.py'
    import main
    monkeypatch.setattr(main, "client", MockClient())

    response = client.post("/chat", json={"message": "How do I register to vote?"})
    
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert data["response"] == "Mocked Voter Education Response: To register, fill out Form 6."

def test_post_chat_handles_empty_message(monkeypatch):
    """Verify empty and whitespace-only messages are rejected before reaching Gemini.

    Two layers of defense:
      - Empty string ('') is caught by Pydantic Field(min_length=1) → 422
      - Whitespace-only ('   ') passes Pydantic (length > 0) but is caught by
        the explicit .strip() check in the endpoint → 400
    """
    class MockModels:
        def generate_content(self, **kwargs):
            raise AssertionError("Gemini must not be called for invalid input")

    class MockClient:
        models = MockModels()

    import main
    monkeypatch.setattr(main, "client", MockClient())

    # Empty string → Pydantic validation error
    response = client.post("/chat", json={"message": ""})
    assert response.status_code == 422

    # Whitespace-only → manual validation error
    response_ws = client.post("/chat", json={"message": "   "})
    assert response_ws.status_code == 400
    assert "Message cannot be empty" in response_ws.json()["detail"]


def test_post_chat_rejects_oversized_message(monkeypatch):
    """Verify Pydantic Field(max_length=2000) rejects a 2001-char message with 422."""
    class MockModels:
        def generate_content(self, **kwargs):
            class MockResponse:
                text = "should-not-be-called"
            return MockResponse()

    class MockClient:
        models = MockModels()

    import main
    monkeypatch.setattr(main, "client", MockClient())

    oversized = "a" * (main.MAX_MESSAGE_LENGTH + 1)
    response = client.post("/chat", json={"message": oversized})
    # Pydantic validation failures surface as 422 in FastAPI.
    assert response.status_code == 422


def test_post_chat_handles_gemini_failure(monkeypatch, caplog):
    """When the Gemini SDK raises:
       - the endpoint returns 502 (upstream failure)
       - the public response does NOT leak the internal exception message
       - the full traceback IS written to logs so Cloud Logging captures it
    """
    secret_internal_error = "upstream-failure-with-sensitive-token-abc123"

    class FailingModels:
        def generate_content(self, **kwargs):
            raise RuntimeError(secret_internal_error)

    class FailingClient:
        models = FailingModels()

    import main
    import logging
    monkeypatch.setattr(main, "client", FailingClient())

    with caplog.at_level(logging.ERROR, logger="voter-education-assistant"):
        response = client.post("/chat", json={"message": "How do I register?"})

    assert response.status_code == 502
    body = response.json()
    # Public message is generic — no leak of internal exception text.
    assert "Error communicating with Gemini" in body["detail"]
    assert secret_internal_error not in body["detail"]
    # But the traceback IS in the logs (with the secret), so ops can debug.
    assert any(secret_internal_error in rec.message or secret_internal_error in str(rec.exc_info)
               for rec in caplog.records), "Gemini exception was not logged to stderr"


# NOTE: Removed test_post_chat_returns_503_when_client_unconfigured.
# main.py now uses fail-fast startup (raises RuntimeError if GEMINI_API_KEY is
# missing), so a running app with client=None is no longer reachable. The
# fail-fast behavior itself is verified by the import succeeding in conftest.py
# with the dummy key set. To explicitly test the fail-fast path, see
# test_fail_fast_on_missing_api_key below.



def test_fail_fast_on_missing_api_key(monkeypatch):
    """Importing main.py without GEMINI_API_KEY must raise RuntimeError at module load."""
    import importlib
    import sys

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # Force a fresh import so the top-level fail-fast check re-runs.
    sys.modules.pop("main", None)
    try:
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY is missing"):
            importlib.import_module("main")
    finally:
        # Re-import main with the key restored so subsequent tests still work.
        sys.modules.pop("main", None)
        os.environ["GEMINI_API_KEY"] = "test-key-not-real-do-not-send-to-google"
        importlib.import_module("main")
