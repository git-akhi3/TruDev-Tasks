from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from importlib import import_module

import pytest
from sqlalchemy import select


def _resolve(module_name: str, fallback: str):
    try:
        return import_module(module_name)
    except ModuleNotFoundError:
        return import_module(fallback)


payment_models_mod = _resolve("pulsepay.payments.models", "payments.models")

Payment = payment_models_mod.Payment
IdempotencyRecord = payment_models_mod.IdempotencyRecord

pytestmark = [pytest.mark.grader, pytest.mark.task("feature_002")]


def _load_api_client_model():
    try:
        clients_models = import_module("pulsepay.clients.models")
    except ModuleNotFoundError:
        try:
            clients_models = import_module("clients.models")
        except ModuleNotFoundError:
            pytest.fail("API client model is missing for idempotency TTL feature.")
    model = getattr(clients_models, "APIClient", None)
    if model is None:
        pytest.fail("APIClient model is missing for idempotency TTL feature.")
    return model


@pytest.mark.anyio
async def test_client_ttl_respected_in_idempotency_check(app_client, db_session, make_api_key):
    """Client-specific idempotency TTL should control whether an old key can create a new payment."""
    APIClient = _load_api_client_model()

    client = APIClient(client_id=f"client-{uuid.uuid4()}", idempotency_ttl_hours=1)
    db_session.add(client)
    await db_session.commit()

    idem_key = f"fx2-idem-{uuid.uuid4()}"
    headers = {"X-API-Key": make_api_key, "Idempotency-Key": idem_key}
    payload = {"customer_id": client.client_id, "amount": "40.00", "currency": "USD"}

    first = await app_client.post("/v1/payments/", headers=headers, json=payload)
    assert first.status_code == 201

    record = (await db_session.execute(select(IdempotencyRecord).where(IdempotencyRecord.key == idem_key))).scalar_one()
    record.expires_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await db_session.commit()

    second = await app_client.post("/v1/payments/", headers=headers, json=payload)
    assert second.status_code == 201

    first_id = first.json().get("data", {}).get("id")
    second_id = second.json().get("data", {}).get("id")
    assert second_id != first_id


@pytest.mark.anyio
async def test_key_expired_under_short_ttl_is_rejected(app_client, db_session, make_api_key):
    """A key still valid under client TTL should return original response instead of creating a second payment."""
    APIClient = _load_api_client_model()

    client = APIClient(client_id=f"client-{uuid.uuid4()}", idempotency_ttl_hours=24)
    db_session.add(client)
    await db_session.commit()

    idem_key = f"fx2-idem-{uuid.uuid4()}"
    headers = {"X-API-Key": make_api_key, "Idempotency-Key": idem_key}
    payload = {"customer_id": client.client_id, "amount": "40.00", "currency": "USD"}

    first = await app_client.post("/v1/payments/", headers=headers, json=payload)
    assert first.status_code == 201

    record = (await db_session.execute(select(IdempotencyRecord).where(IdempotencyRecord.key == idem_key))).scalar_one()
    record.expires_at = datetime.now(timezone.utc) + timedelta(hours=22)
    await db_session.commit()

    second = await app_client.post("/v1/payments/", headers=headers, json=payload)
    assert second.status_code == 201

    first_id = first.json().get("data", {}).get("id")
    second_id = second.json().get("data", {}).get("id")
    assert second_id == first_id


@pytest.mark.anyio
async def test_patch_endpoint_updates_client_ttl(app_client, db_session):
    """Client TTL patch endpoint should update valid values and reject invalid bounds."""
    APIClient = _load_api_client_model()

    client = APIClient(client_id=f"client-{uuid.uuid4()}", idempotency_ttl_hours=24)
    db_session.add(client)
    await db_session.commit()
    await db_session.refresh(client)

    ok = await app_client.patch(
        f"/v1/clients/{client.id}",
        headers={"X-API-Key": "grader-fx2-admin"},
        json={"idempotency_ttl_hours": 48},
    )
    assert ok.status_code == 200

    refreshed = await db_session.get(APIClient, client.id)
    assert refreshed.idempotency_ttl_hours == 48

    low = await app_client.patch(
        f"/v1/clients/{client.id}",
        headers={"X-API-Key": "grader-fx2-admin"},
        json={"idempotency_ttl_hours": 0},
    )
    assert low.status_code == 422

    high = await app_client.patch(
        f"/v1/clients/{client.id}",
        headers={"X-API-Key": "grader-fx2-admin"},
        json={"idempotency_ttl_hours": 200},
    )
    assert high.status_code == 422
