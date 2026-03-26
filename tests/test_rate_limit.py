from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_missing_api_key_returns_401(test_client: AsyncClient) -> None:
	response = await test_client.get(f"/v1/payments/{uuid4()}")

	assert response.status_code == 401
	assert response.json()["error"]["code"] == "MISSING_API_KEY"


@pytest.mark.anyio
async def test_rate_limit_exceeded_returns_429_with_retry_after(
	test_client: AsyncClient,
	exhausted_rate_limit_bucket: tuple[str, float],
) -> None:
	api_key, _ = exhausted_rate_limit_bucket
	response = await test_client.get(
		f"/v1/payments/{uuid4()}",
		headers={"X-API-Key": api_key},
	)

	assert response.status_code == 429
	assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
	assert "Retry-After" in response.headers
	assert float(response.headers["Retry-After"]) > 0.0
