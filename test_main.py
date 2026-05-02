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


def test_post_chat_handles_gemini_failure(monkeypatch):
    """Verify the /chat endpoint returns 500 when the Gemini SDK raises."""
    class FailingModels:
        def generate_content(self, **kwargs):
            raise RuntimeError("upstream-failure")

    class FailingClient:
        models = FailingModels()

    import main
    monkeypatch.setattr(main, "client", FailingClient())

    response = client.post("/chat", json={"message": "How do I register?"})
    assert response.status_code == 500
    assert "Error communicating with Gemini" in response.json()["detail"]


def test_post_chat_returns_503_when_client_unconfigured(monkeypatch):
    """If the API key was missing at boot, the chat endpoint must fail loudly, not silently."""
    import main
    monkeypatch.setattr(main, "client", None)

    response = client.post("/chat", json={"message": "How do I register?"})
    assert response.status_code == 500
    assert "Gemini API Key is not configured" in response.json()["detail"]
