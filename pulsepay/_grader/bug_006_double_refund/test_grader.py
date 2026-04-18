from __future__ import annotations

import asyncio
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

pytestmark = [pytest.mark.grader, pytest.mark.task("bug_006")]


async def _post_refund(app_client, api_key: str, payment_id: str, amount: str, idem_suffix: str):
    return await app_client.post(
        f"/v1/payments/{payment_id}/refunds",
        headers={
            "X-API-Key": api_key,
            "Idempotency-Key": f"refund-{idem_suffix}-{uuid.uuid4()}",
        },
        json={"amount": amount, "reason": "grader_concurrent_refund"},
    )


@pytest.mark.anyio
async def test_concurrent_partial_refunds_never_exceed_original(app_client, db_session, make_payment, make_api_key):
    """Concurrent partial refunds should never produce a refundable total above the original payment amount."""
    payment = await make_payment(status="success", amount=Decimal("500.00"))
    api_key = make_api_key

    r1, r2 = await asyncio.gather(
        _post_refund(app_client, api_key, str(payment.id), "300.00", "a"),
        _post_refund(app_client, api_key, str(payment.id), "300.00", "b"),
    )

    assert r1.status_code in {201, 409}
    assert r2.status_code in {201, 409}

    total_stmt = select(func.coalesce(func.sum(Refund.amount), Decimal("0.00"))).where(
        Refund.payment_id == payment.id,
        Refund.status != "failed",
    )
    total = Decimal((await db_session.execute(total_stmt)).scalar_one())
    assert total <= Decimal("500.00")


@pytest.mark.anyio
async def test_second_concurrent_refund_returns_conflict(app_client, db_session, make_payment, make_api_key):
    """One of two concurrent over-refunds should be rejected with insufficient refundable amount."""
    payment = await make_payment(status="success", amount=Decimal("500.00"))
    api_key = make_api_key

    r1, r2 = await asyncio.gather(
        _post_refund(app_client, api_key, str(payment.id), "300.00", "x"),
        _post_refund(app_client, api_key, str(payment.id), "300.00", "y"),
    )

    statuses = {r1.status_code, r2.status_code}
    assert 201 in statuses
    assert 409 in statuses

    conflict_response = r1 if r1.status_code == 409 else r2
    assert conflict_response.json().get("error", {}).get("code") == "INSUFFICIENT_REFUNDABLE_AMOUNT"

    successful_refund_stmt = select(Refund).where(
        Refund.payment_id == payment.id,
        Refund.status == "pending",
    )
    successful_refund = (await db_session.execute(successful_refund_stmt)).scalars().first()
    assert successful_refund is not None
    assert Decimal(successful_refund.amount) == Decimal("300.00")
