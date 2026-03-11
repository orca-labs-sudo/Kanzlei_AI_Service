import pytest
from unittest.mock import AsyncMock, patch
from app.services.query_service import query_service

@pytest.mark.asyncio
async def test_handle_query_erstanschreiben(mock_gemini_client, mock_rag_store):
    """Testet, dass bei Intent 'erstelle_brief_aus_kontext' ein dict mit result_type='brief_aus_kontext' kommt."""
    with patch.object(query_service, "_get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {
            "aktenzeichen": "01.26.XYZ",
            "mandant": "Max Mustermann", 
            "gegner": "Allianz",
        }
        
        with patch.object(query_service, "_classify_with_gemini", new_callable=AsyncMock) as mock_tools:
            mock_tools.return_value = {"name": "erstelle_brief_aus_kontext", "args": {"user_kontext": "Bitte schreibe", "schreiben_typ": "Allgemein"}}
            
            result = await query_service.handle_query(query="Schreibe einen Brief", user_id=1, akte_id=42)
            
            assert result["status"] == "ok"
            assert result["result_type"] == "brief_aus_kontext"
            assert result["data"] == "Mocked Gemini Response"

@pytest.mark.asyncio
async def test_handle_query_unbekannt():
    """Testet, dass bei einem unbekannten Intent ein Text-Ergebnis zurückkommt (Fallback)."""
    with patch.object(query_service, "_classify_with_gemini", new_callable=AsyncMock) as mock_tools:
        mock_tools.return_value = None
        with patch.object(query_service, "_handle_rag_fallback", new_callable=AsyncMock) as mock_fallback:
            mock_fallback.return_value = {"status": "ok", "result_type": "text", "data": "Fallback Response"}
            result = await query_service.handle_query(query="Mache etwas Unbekanntes", user_id=1)
            assert result["result_type"] == "text"
            assert result["data"] == "Fallback Response"

@pytest.mark.asyncio
async def test_handle_query_ohne_akte_id(mock_gemini_client):
    """Testet dass akte_id=None keinen Fehler wirft und graceful gehandhabt wird."""
    with patch.object(query_service, "_classify_with_gemini", new_callable=AsyncMock) as mock_tools:
        mock_tools.return_value = {"name": "erstelle_brief_aus_kontext", "args": {"user_kontext": "Bitte schreibe"}}
        
        result = await query_service.handle_query(query="Schreibe einen Brief", user_id=1, akte_id=None)
        assert result["status"] == "ok"
        assert result["result_type"] == "brief_aus_kontext"

@pytest.mark.asyncio
async def test_build_briefkopf_context(mock_gemini_client, mock_rag_store):
    """Testet, falls es eine Funktion gibt die Kontext baut, dass Mandant, Gegner, Aktenzeichen enthalten sind."""
    with patch.object(query_service, "_get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {
            "aktenzeichen": "01.26.XYZ",
            "mandant": "Max Mustermann", 
            "gegner": "Allianz"
        }
        
        await query_service._erstelle_brief_aus_kontext(
            user_kontext="Bitte machen", akte_id=42
        )
        
        call_args = mock_gemini_client.return_value.generate.call_args[0][0]
        assert "01.26.XYZ" in call_args
        assert "Max Mustermann" in call_args
        assert "Allianz" in call_args


# TEIL 2 - Unit Tests RAGStore
@pytest.mark.asyncio
async def test_search_similar_returns_list():
    """Testet, dass RAGStore search_similar das richtige Format (Liste) zurückgibt."""
    from app.services.rag_store import rag_store
    with patch.object(rag_store, "_collection") as mock_collection:
        mock_collection.query.return_value = {
            "documents": [["Doc 1", "Doc 2"]],
            "metadatas": [[{"m": 1}, {"m": 2}]],
            "distances": [[0.1, 0.2]]
        }
        with patch.object(rag_store, "_get_vertex_embeddings", new_callable=AsyncMock) as mock_emb:
            mock_emb.return_value = [[0.0] * 768]
            results = await rag_store.search_similar("Test Query", n_results=2)
            assert isinstance(results, list)
            assert len(results) == 2
            assert results[0]["text"] == "Doc 1"

@pytest.mark.asyncio
async def test_search_similar_empty_collection():
    """Testet, dass leere Ergebnisse als leere Liste zurückgegeben werden."""
    from app.services.rag_store import rag_store
    with patch.object(rag_store, "_collection") as mock_collection:
        mock_collection.query.return_value = {"documents": [], "metadatas": [], "distances": []}
        with patch.object(rag_store, "_get_vertex_embeddings", new_callable=AsyncMock) as mock_emb:
            mock_emb.return_value = [[0.0] * 768]
            results = await rag_store.search_similar("Test Query")
            assert results == []

@pytest.mark.asyncio
async def test_search_similar_n_results():
    """Testet, dass der n_results Parameter korrekt an ChromaDB weitergereicht wird."""
    from app.services.rag_store import rag_store
    with patch.object(rag_store, "_collection") as mock_collection:
        mock_collection.query.return_value = {"documents": [["D1"]], "metadatas": [[{}]], "distances": [[0.1]]}
        with patch.object(rag_store, "_get_vertex_embeddings", new_callable=AsyncMock) as mock_emb:
            mock_emb.return_value = [[0.0] * 768]
            await rag_store.search_similar("Test", n_results=5)
            mock_collection.query.assert_called_once()
            assert mock_collection.query.call_args[1]["n_results"] == 5


# TEIL 3 - Unit Tests GeminiClient
def test_generate_returns_string():
    """Testet, dass GeminiClient.generate einen String zurückgibt."""
    from app.services.gemini_client import GeminiClient
    with patch("app.services.gemini_client.genai") as mock_genai:
        with patch("app.services.gemini_client.settings") as mock_settings:
            mock_settings.gemini_api_key = "test_key"
            client = GeminiClient()
            client.model.generate_content.return_value.text = "Antwort String"
            res = client.generate("Prompt")
            assert isinstance(res, str)
            assert res == "Antwort String"

def test_generate_fallback_on_error():
    """Testet, dass bei einem API-Fehler in generate eine Exception fliegt oder gracefully returned wird."""
    from app.services.gemini_client import GeminiClient
    with patch("app.services.gemini_client.genai") as mock_genai:
        with patch("app.services.gemini_client.settings") as mock_settings:
            mock_settings.gemini_api_key = "test_key"
            client = GeminiClient()
            client.model.generate_content.side_effect = Exception("API Fehler")
            with pytest.raises(Exception) as exc_info:
                client.generate("Prompt")
            assert "API Fehler" in str(exc_info.value)

# TEIL 4 - Integration Tests FastAPI /api/query/
import httpx

@pytest.mark.asyncio
async def test_query_endpoint_without_auth():
    """Testet, dass Request ohne X-KI-Signature einen 403 Fehler wirft."""
    from app.main import app
    kwargs = {"app": app, "base_url": "http://test"}
    if hasattr(httpx, "ASGITransport"):
        kwargs = {"transport": httpx.ASGITransport(app=app), "base_url": "http://test"}
    async with httpx.AsyncClient(**kwargs) as client:
        response = await client.post("/api/query/", json={"query": "Hallo"})
        assert response.status_code == 403

@pytest.mark.asyncio
async def test_query_endpoint_with_valid_payload():
    """Testet, dass eine gültige Signatur+Payload akzeptiert wird (200)."""
    with patch("app.main.query_service.handle_query", new_callable=AsyncMock) as mock_handle:
        mock_handle.return_value = {"status": "ok", "result_type": "text", "data": "Success"}
        
        import json
        from app.services.hmac_auth import generate_ki_signature
        from app.main import app
        
        payload = {"query": "Test", "user_id": 1}
        signature = generate_ki_signature()
        
        kwargs = {"app": app, "base_url": "http://test"}
        if hasattr(httpx, "ASGITransport"):
            kwargs = {"transport": httpx.ASGITransport(app=app), "base_url": "http://test"}
            
        async with httpx.AsyncClient(**kwargs) as client:
            response = await client.post("/api/query/", json=payload, headers={"X-KI-Signature": signature})
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "result_type": "text", "data": "Success"}

@pytest.mark.asyncio
async def test_query_endpoint_missing_query():
    """Testet, dass bei fehlender Query im Body ein 422 Fehler (Validation Error) kommt."""
    import json
    from app.services.hmac_auth import generate_ki_signature
    from app.main import app
    
    payload = {"user_id": 1} # query missing
    signature = generate_ki_signature()
    
    kwargs = {"app": app, "base_url": "http://test"}
    if hasattr(httpx, "ASGITransport"):
        kwargs = {"transport": httpx.ASGITransport(app=app), "base_url": "http://test"}
            
    async with httpx.AsyncClient(**kwargs) as client:
        response = await client.post("/api/query/", json=payload, headers={"X-KI-Signature": signature})
        assert response.status_code == 422
