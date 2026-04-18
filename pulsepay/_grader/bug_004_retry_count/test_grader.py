from __future__ import annotations

from importlib import import_module

import pytest
from sqlalchemy import select


def _resolve(module_name: str, fallback: str):
    try:
        return import_module(module_name)
    except ModuleNotFoundError:
        return import_module(fallback)


jobs_handlers_mod = _resolve("pulsepay.jobs.handlers", "jobs.handlers")
config_mod = _resolve("pulsepay.core.config", "core.config")
payment_models_mod = _resolve("pulsepay.payments.models", "payments.models")

retry_payment = jobs_handlers_mod.retry_payment
settings = config_mod.settings
Payment = payment_models_mod.Payment

pytestmark = [pytest.mark.grader, pytest.mark.task("bug_004")]


@pytest.mark.anyio
async def test_retry_count_persists_after_each_attempt(db_session, make_payment, patch_processor):
    """Each retry attempt should persist retry_count to the database."""
    payment = await make_payment(status="pending")
    patch_processor("soft_fail")

    await retry_payment({"payment_id": str(payment.id)})

    refreshed = (await db_session.execute(select(Payment).where(Payment.id == payment.id))).scalar_one()
    assert refreshed.retry_count == 1


@pytest.mark.anyio
async def test_payment_transitions_to_failed_after_max_retries(db_session, make_payment, patch_processor):
    """Payments should transition to failed after reaching max retry attempts."""
    payment = await make_payment(status="pending")
    patch_processor("soft_fail")

    for _ in range(settings().MAX_PAYMENT_RETRY_ATTEMPTS):
        await retry_payment({"payment_id": str(payment.id)})

    refreshed = (await db_session.execute(select(Payment).where(Payment.id == payment.id))).scalar_one()
    assert refreshed.status == "failed"
    assert refreshed.failure_reason == "max_retries_exceeded"


@pytest.mark.anyio
async def test_retry_count_in_db_matches_attempt_log(db_session, make_payment, patch_processor):
    """The persisted retry_count should match the exact number of executed retry attempts."""
    payment = await make_payment(status="pending")
    patch_processor("soft_fail")

    await retry_payment({"payment_id": str(payment.id)})
    await retry_payment({"payment_id": str(payment.id)})

    refreshed = (await db_session.execute(select(Payment).where(Payment.id == payment.id))).scalar_one()
    assert refreshed.retry_count == 2
