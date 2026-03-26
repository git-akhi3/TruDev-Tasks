from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pulsepay.payments.models import PAYMENT_STATUS_PENDING, Payment


@pytest.mark.anyio
async def test_partial_refund_success(test_client: AsyncClient, sample_payment: Payment) -> None:
	response = await test_client.post(
		f"/v1/payments/{sample_payment.id}/refunds",
		headers={
			"X-API-Key": "client-test-key",
			"Idempotency-Key": f"refund-key-{uuid4()}",
		},
		json={"amount": "25.00", "reason": "partial"},
	)

	assert response.status_code == 201
	payload = response.json()
	assert payload["data"]["payment_id"] == str(sample_payment.id)
	assert payload["data"]["amount"] == "25.00"
	assert payload["data"]["status"] == "pending"


@pytest.mark.anyio
async def test_refund_exceeds_original_raises_409(test_client: AsyncClient, sample_payment: Payment) -> None:
	response = await test_client.post(
		f"/v1/payments/{sample_payment.id}/refunds",
		headers={
			"X-API-Key": "client-test-key",
			"Idempotency-Key": f"refund-exceeds-{uuid4()}",
		},
		json={"amount": "9999.99", "reason": "too-much"},
	)

	assert response.status_code == 409
	assert response.json()["error"]["code"] == "INSUFFICIENT_REFUNDABLE_AMOUNT"


@pytest.mark.anyio
async def test_refund_on_non_success_payment_raises_409(test_client: AsyncClient, db_session: AsyncSession) -> None:
	created_at = datetime.now(timezone.utc)
	pending_payment = Payment(
		customer_id="cust_pending_1",
		amount="30.00",
		currency="USD",
		status=PAYMENT_STATUS_PENDING,
		failure_reason=None,
		failure_class=None,
		retry_count=0,
		idempotency_key=f"pending-payment-{uuid4()}",
		payment_metadata={"source": "test"},
		state_history=[{"state": "pending", "timestamp": created_at.isoformat(), "reason": "created"}],
		confirmed_at=None,
		created_at=created_at,
		updated_at=created_at,
	)
	db_session.add(pending_payment)
	await db_session.commit()
	await db_session.refresh(pending_payment)

	response = await test_client.post(
		f"/v1/payments/{pending_payment.id}/refunds",
		headers={
			"X-API-Key": "client-test-key",
			"Idempotency-Key": f"refund-pending-{uuid4()}",
		},
		json={"amount": "5.00", "reason": "invalid"},
	)

	assert response.status_code == 409
	assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
