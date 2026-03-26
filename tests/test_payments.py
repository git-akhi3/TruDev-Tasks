from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pulsepay.payments.models import Payment


@pytest.mark.anyio
async def test_create_payment_success(test_client: AsyncClient) -> None:
	response = await test_client.post(
		"/v1/payments/",
		headers={
			"X-API-Key": "client-test-key",
			"Idempotency-Key": "create-payment-success-key",
		},
		json={
			"customer_id": "cust_create_1",
			"amount": "42.50",
			"currency": "usd",
			"metadata": {"source": "test"},
		},
	)

	assert response.status_code == 201
	payload = response.json()
	assert payload["data"]["status"] == "pending"
	assert payload["data"]["currency"] == "USD"


@pytest.mark.anyio
async def test_idempotency_returns_same_response(test_client: AsyncClient, db_session: AsyncSession) -> None:
	headers = {
		"X-API-Key": "client-test-key",
		"Idempotency-Key": "idempotent-payment-key",
	}
	request_payload = {
		"customer_id": "cust_idempotent_1",
		"amount": "10.00",
		"currency": "USD",
		"metadata": {"source": "test"},
	}

	first_response = await test_client.post("/v1/payments/", headers=headers, json=request_payload)
	second_response = await test_client.post("/v1/payments/", headers=headers, json=request_payload)

	assert first_response.status_code == 201
	assert second_response.status_code == 201
	assert first_response.json()["data"] == second_response.json()["data"]

	count_stmt = select(func.count(Payment.id)).where(Payment.idempotency_key == "idempotent-payment-key")
	count_result = await db_session.execute(count_stmt)
	assert int(count_result.scalar_one()) == 1


@pytest.mark.anyio
async def test_invalid_state_transition(test_client: AsyncClient, sample_payment: Payment) -> None:
	response = await test_client.post(
		f"/v1/payments/{sample_payment.id}/confirm",
		headers={"X-API-Key": "client-test-key"},
		json={},
	)

	assert response.status_code == 409
	assert response.json()["error"]["code"] == "PAYMENT_ALREADY_PROCESSED"


@pytest.mark.anyio
async def test_payment_not_found(test_client: AsyncClient) -> None:
	nonexistent_id = uuid4()
	response = await test_client.get(
		f"/v1/payments/{nonexistent_id}",
		headers={"X-API-Key": "client-test-key"},
	)

	assert response.status_code == 404
	assert response.json()["error"]["code"] == "PAYMENT_NOT_FOUND"
