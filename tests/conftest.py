import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.fixture
def mock_gemini_client():
    with patch("app.main.get_gemini_client") as mock:
        client_instance = MagicMock()
        client_instance.generate.return_value = "Mocked Gemini Response"
        mock.return_value = client_instance
        yield mock

@pytest.fixture
def mock_rag_store():
    with patch("app.services.rag_store.rag_store") as mock:
        mock.search_similar = AsyncMock(return_value=[
            {"text": "Mocked RAG similarity result", "metadata": {}, "distance": 0.1}
        ])
        yield mock
