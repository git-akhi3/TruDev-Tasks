from __future__ import annotations

from importlib import import_module

import pytest
from sqlalchemy import select


def _resolve(module_name: str, fallback: str):
    try:
        return import_module(module_name)
    except ModuleNotFoundError:
        return import_module(fallback)


payment_service_mod = _resolve("pulsepay.payments.service", "payments.service")
payment_models_mod = _resolve("pulsepay.payments.models", "payments.models")
ledger_models_mod = _resolve("pulsepay.ledger.models", "ledger.models")

PaymentService = payment_service_mod.PaymentService
Payment = payment_models_mod.Payment
LedgerEntry = ledger_models_mod.LedgerEntry

pytestmark = [pytest.mark.grader, pytest.mark.task("bug_005")]


@pytest.mark.anyio
async def test_failed_payment_has_ledger_entry(db_session, make_payment, patch_processor):
    """Hard-failed payments should produce exactly one payment.failed ledger entry."""
    payment = await make_payment(status="pending")
    patch_processor("hard_fail")

    service = PaymentService(db_session)
    await service.confirm_payment(payment.id)

    stmt = select(LedgerEntry).where(
        LedgerEntry.payment_id == payment.id,
        LedgerEntry.entry_type == "payment.failed",
    )
    entries = (await db_session.execute(stmt)).scalars().all()
    assert len(entries) == 1


@pytest.mark.anyio
async def test_soft_failure_path_writes_ledger_entry(db_session, make_payment, patch_processor):
    """Soft-failure terminal transitions should still create a payment.failed ledger entry."""
    payment = await make_payment(status="pending")
    patch_processor("soft_fail")

    service = PaymentService(db_session)
    max_attempts = 3
    for _ in range(max_attempts):
        try:
            await service.confirm_payment(payment.id)
        except Exception:
            continue

    stmt = select(Payment).where(Payment.id == payment.id)
    refreshed = (await db_session.execute(stmt)).scalar_one()
    if refreshed.status != "failed":
        refreshed = await service.mark_payment_failed_max_retries(payment.id)

    ledger_stmt = select(LedgerEntry).where(
        LedgerEntry.payment_id == payment.id,
        LedgerEntry.entry_type == "payment.failed",
    )
    entries = (await db_session.execute(ledger_stmt)).scalars().all()
    assert len(entries) >= 1


@pytest.mark.anyio
async def test_success_path_ledger_unaffected(db_session, make_payment, patch_processor):
    """Successful payment confirmation should continue writing a success ledger entry."""
    payment = await make_payment(status="pending")
    patch_processor("success")

    service = PaymentService(db_session)
    await service.confirm_payment(payment.id)

    stmt = select(LedgerEntry).where(
        LedgerEntry.payment_id == payment.id,
        LedgerEntry.entry_type == "payment.success",
    )
    entry = (await db_session.execute(stmt)).scalars().first()
    assert entry is not None
