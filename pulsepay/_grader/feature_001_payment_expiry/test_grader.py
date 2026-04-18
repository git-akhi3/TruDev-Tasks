from __future__ import annotations

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
jobs_handlers_mod = _resolve("pulsepay.jobs.handlers", "jobs.handlers")
webhook_models_mod = _resolve("pulsepay.webhooks.models", "webhooks.models")
config_mod = _resolve("pulsepay.core.config", "core.config")

Payment = payment_models_mod.Payment
WebhookEvent = webhook_models_mod.WebhookEvent
settings = config_mod.settings

pytestmark = [pytest.mark.grader, pytest.mark.task("feature_001")]


@pytest.mark.anyio
async def test_expires_at_set_on_payment_creation(app_client, db_session, make_api_key):
    """Payment creation should set expires_at based on configured payment expiry minutes."""
    response = await app_client.post(
        "/v1/payments/",
        headers={"X-API-Key": make_api_key, "Idempotency-Key": "fx1-expiry-create"},
        json={"customer_id": "cust-fx001", "amount": "50.00", "currency": "USD"},
    )
    assert response.status_code == 201
    payment_id = response.json().get("data", {}).get("id")

    payment = (await db_session.execute(select(Payment).where(Payment.id == payment_id))).scalar_one()
    assert hasattr(payment, "expires_at"), "Payment model must include expires_at."
    assert payment.expires_at is not None

    expected = datetime.now(timezone.utc) + timedelta(minutes=settings().PAYMENT_EXPIRY_MINUTES)
    delta = abs((payment.expires_at - expected).total_seconds())
    assert delta <= 5


@pytest.mark.anyio
async def test_expired_pending_payment_transitions_to_failed(db_session, make_payment):
    """Expired pending payments should transition to failed when expiry job runs."""
    payment = await make_payment(status="pending")
    assert hasattr(payment, "expires_at"), "Payment model must include expires_at."

    payment.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    handler = getattr(jobs_handlers_mod, "expire_payments", None)
    assert handler is not None, "expire_payments job handler must exist."
    await handler({})

    refreshed = (await db_session.execute(select(Payment).where(Payment.id == payment.id))).scalar_one()
    assert refreshed.status == "failed"


@pytest.mark.anyio
async def test_failure_reason_is_expired(db_session, make_payment):
    """Expired payment transitions should set failure_reason to expired."""
    payment = await make_payment(status="pending")
    assert hasattr(payment, "expires_at"), "Payment model must include expires_at."

    payment.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    handler = getattr(jobs_handlers_mod, "expire_payments", None)
    assert handler is not None, "expire_payments job handler must exist."
    await handler({})

    refreshed = (await db_session.execute(select(Payment).where(Payment.id == payment.id))).scalar_one()
    assert refreshed.failure_reason == "expired"


@pytest.mark.anyio
async def test_payment_expired_webhook_emitted(db_session, make_payment):
    """Expiry processing should emit a payment.expired webhook event for affected payments."""
    payment = await make_payment(status="pending")
    assert hasattr(payment, "expires_at"), "Payment model must include expires_at."

    payment.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    handler = getattr(jobs_handlers_mod, "expire_payments", None)
    assert handler is not None, "expire_payments job handler must exist."
    await handler({})

    event_stmt = select(WebhookEvent).where(
        WebhookEvent.event_type == "payment.expired",
    )
    event = (await db_session.execute(event_stmt)).scalars().first()
    assert event is not None
    assert event.status in {"queued", "delivered"}
