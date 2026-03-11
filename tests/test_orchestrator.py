import pytest
import httpx
import hmac
import hashlib
import json
from app.config import settings
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_orchestrator_endpoint_struktur():
    """Prüfe dass /api/query/ die erwarteten Felder zurückgibt (result_type, data, query_used)"""
    with patch("app.main.query_service.handle_query", new_callable=AsyncMock) as mock_handle:
        mock_handle.return_value = {"status": "ok", "result_type": "text", "data": "Hallo", "query_used": "fallback"}
        
        from app.services.hmac_auth import generate_ki_signature
        payload = {"query": "Test", "user_id": 1}
        signature = generate_ki_signature()
        
        from app.main import app
        kwargs = {"app": app, "base_url": "http://test"}
        if hasattr(httpx, "ASGITransport"):
            kwargs = {"transport": httpx.ASGITransport(app=app), "base_url": "http://test"}
            
        async with httpx.AsyncClient(**kwargs) as client:
            response = await client.post("/api/query/", json=payload, headers={"X-KI-Signature": signature})
            assert response.status_code == 200
            data = response.json()
            assert "result_type" in data
            assert "data" in data
            assert "query_used" in data

@pytest.mark.asyncio
async def test_hmac_signature_validation():
    """Gültige vs. ungültige Signatur beim /api/query/ Endpoint testen."""
    from app.services.hmac_auth import generate_ki_signature
    import time
    payload = {"query": "Test", "user_id": 1}
    valid_signature = generate_ki_signature()
    invalid_signature = f"{int(time.time())}.bad_signature_123"
    
    from app.main import app
    kwargs = {"app": app, "base_url": "http://test"}
    if hasattr(httpx, "ASGITransport"):
        kwargs = {"transport": httpx.ASGITransport(app=app), "base_url": "http://test"}
            
    async with httpx.AsyncClient(**kwargs) as client:
        # Valid
        with patch("app.main.query_service.handle_query", new_callable=AsyncMock) as mock_handle:
            mock_handle.return_value = {"status": "ok", "result_type": "text", "data": "Success"}
            response_valid = await client.post("/api/query/", json=payload, headers={"X-KI-Signature": valid_signature})
            assert response_valid.status_code == 200
        
        # Invalid
        response_invalid = await client.post("/api/query/", json=payload, headers={"X-KI-Signature": invalid_signature})
        assert response_invalid.status_code == 403
