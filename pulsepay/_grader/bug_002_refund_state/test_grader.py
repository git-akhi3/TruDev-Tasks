from __future__ import annotations

import uuid
from decimal import Decimal
from importlib import import_module

import pytest
from sqlalchemy import func, select


def _resolve(module_name: str, fallback: str):
    try:
        return import_module(module_name)
    except ModuleNotFoundError:
        return import_module(fallback)


refund_models_mod = _resolve("pulsepay.refunds.models", "refunds.models")
Refund = refund_models_mod.Refund

pytestmark = [pytest.mark.grader, pytest.mark.task("bug_002")]


async def _create_refund(app_client, api_key: str, payment_id: str, amount: str = "10.00"):
    return await app_client.post(
        f"/v1/payments/{payment_id}/refunds",
        headers={
            "X-API-Key": api_key,
            "Idempotency-Key": f"refund-{uuid.uuid4()}",
        },
        json={"amount": amount, "reason": "grader_refund"},
    )


@pytest.mark.anyio
async def test_refund_on_processing_payment_returns_409(app_client, db_session, make_payment, make_api_key):
    """Refund initiation must reject payments currently in processing state."""
    payment = await make_payment(status="processing", amount=Decimal("80.00"))
    response = await _create_refund(app_client, make_api_key, str(payment.id), amount="10.00")

    assert response.status_code == 409
    assert response.json().get("error", {}).get("code") == "INVALID_STATE_TRANSITION"

    count = int((await db_session.execute(select(func.count(Refund.id)).where(Refund.payment_id == payment.id))).scalar_one())
    assert count == 0


@pytest.mark.anyio
async def test_refund_on_failed_payment_returns_409(app_client, db_session, make_payment, make_api_key):
    """Refund initiation must reject payments currently in failed state."""
    payment = await make_payment(status="failed", amount=Decimal("80.00"))
    response = await _create_refund(app_client, make_api_key, str(payment.id), amount="10.00")

    assert response.status_code == 409
    assert response.json().get("error", {}).get("code") == "INVALID_STATE_TRANSITION"

    count = int((await db_session.execute(select(func.count(Refund.id)).where(Refund.payment_id == payment.id))).scalar_one())
    assert count == 0


@pytest.mark.anyio
async def test_refund_on_success_payment_proceeds(app_client, db_session, make_payment, make_api_key):
    """Refund initiation must proceed for payments in success state."""
    payment = await make_payment(status="success", amount=Decimal("80.00"))
    response = await _create_refund(app_client, make_api_key, str(payment.id), amount="10.00")

    assert response.status_code == 201

    stmt = select(Refund).where(Refund.payment_id == payment.id)
    refund = (await db_session.execute(stmt)).scalars().first()
    assert refund is not None
    assert refund.status == "pending"
