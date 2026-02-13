import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from ticktick_mcp.v2_client import TickTickV2Client, V2AuthError


@pytest.mark.asyncio
async def test_v2_client_requires_credentials():
    """V2 client raises ValueError if username/password missing."""
    with pytest.raises(ValueError, match="TICKTICK_USERNAME"):
        TickTickV2Client(username="", password="test")


@pytest.mark.asyncio
async def test_v2_client_signon_sets_token():
    """V2 client signon extracts token from response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "fake-session-token"}
    mock_response.cookies = {"t": "fake-session-token"}

    with patch("ticktick_mcp.v2_client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.post = AsyncMock(return_value=mock_response)
        instance.aclose = AsyncMock()

        client = TickTickV2Client(username="user@test.com", password="pass123")
        await client.authenticate()

        assert client._token == "fake-session-token"
        assert client.is_authenticated


@pytest.mark.asyncio
async def test_v2_client_signon_failure_raises():
    """V2 client raises V2AuthError on 401."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    with patch("ticktick_mcp.v2_client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.post = AsyncMock(return_value=mock_response)
        instance.aclose = AsyncMock()

        client = TickTickV2Client(username="user@test.com", password="wrong")
        with pytest.raises(V2AuthError, match="Authentication failed"):
            await client.authenticate()
