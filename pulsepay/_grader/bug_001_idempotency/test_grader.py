from __future__ import annotations

import asyncio
import uuid
from importlib import import_module

import pytest
from sqlalchemy import func, select


def _resolve(module_name: str, fallback: str):
    try:
        return import_module(module_name)
    except ModuleNotFoundError:
        return import_module(fallback)


payment_models_mod = _resolve("pulsepay.payments.models", "payments.models")
Payment = payment_models_mod.Payment
IdempotencyRecord = payment_models_mod.IdempotencyRecord

pytestmark = [pytest.mark.grader, pytest.mark.task("bug_001")]


async def _create_payment(app_client, api_key: str, idempotency_key: str, customer_id: str = "cust-bug001"):
    return await app_client.post(
        "/v1/payments/",
        headers={
            "X-API-Key": api_key,
            "Idempotency-Key": idempotency_key,
        },
        json={
            "customer_id": customer_id,
            "amount": "100.00",
            "currency": "USD",
            "metadata": {"scenario": "bug_001"},
        },
    )


@pytest.mark.anyio
async def test_concurrent_same_key_creates_one_payment(app_client, db_session, make_api_key):
    """Concurrent requests sharing an idempotency key should create at most one payment row."""
    key = f"idem-{uuid.uuid4()}"
    api_key = make_api_key

    response_a, response_b = await asyncio.gather(
        _create_payment(app_client, api_key, key),
        _create_payment(app_client, api_key, key),
    )

    assert response_a.status_code in {201, 409}
    assert response_b.status_code in {201, 409}

    count_stmt = select(func.count(Payment.id)).where(Payment.idempotency_key == key)
    count = int((await db_session.execute(count_stmt)).scalar_one())
    assert count == 1


@pytest.mark.anyio
async def test_idempotency_record_written(app_client, db_session, make_api_key):
    """A successful create payment call should persist a matching idempotency record."""
    key = f"idem-{uuid.uuid4()}"
    api_key = make_api_key

    response = await _create_payment(app_client, api_key, key)
    assert response.status_code == 201
    body = response.json()

    stmt = select(IdempotencyRecord).where(IdempotencyRecord.key == key)
    record = (await db_session.execute(stmt)).scalar_one_or_none()
    assert record is not None
    assert record.response_body.get("payment", {}).get("id") == body.get("data", {}).get("id")


@pytest.mark.anyio
async def test_second_request_returns_original_response(app_client, db_session, make_api_key):
    """A repeated request with the same idempotency key should return the original payment response."""
    key = f"idem-{uuid.uuid4()}"
    api_key = make_api_key

    first = await _create_payment(app_client, api_key, key)
    second = await _create_payment(app_client, api_key, key)

    assert first.status_code == 201
    assert second.status_code in {201, 409}

    first_id = first.json().get("data", {}).get("id")
    second_id = second.json().get("data", {}).get("id")
    if second.status_code == 201:
        assert second_id == first_id

    count_stmt = select(func.count(Payment.id)).where(Payment.idempotency_key == key)
    count = int((await db_session.execute(count_stmt)).scalar_one())
    assert count == 1
