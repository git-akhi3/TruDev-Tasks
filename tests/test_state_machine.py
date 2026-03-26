from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pulsepay.core.exceptions import InvalidStateTransition
from pulsepay.payments.models import PAYMENT_STATUS_PENDING, Payment
from pulsepay.payments.state_machine import PaymentStateMachine


@pytest.mark.anyio
async def test_valid_transitions() -> None:
	created_at = datetime.now(timezone.utc)
	payment = Payment(
		customer_id="cust_state_1",
		amount="12.00",
		currency="USD",
		status=PAYMENT_STATUS_PENDING,
		idempotency_key="state-machine-valid",
		state_history=[{"state": "pending", "timestamp": created_at.isoformat(), "reason": "created"}],
	)
	machine = PaymentStateMachine()

	machine.transition(payment, "processing", reason="processor_started")
	machine.transition(payment, "success", reason="processor_authorized")

	assert payment.status == "success"


@pytest.mark.anyio
async def test_invalid_transition_raises() -> None:
	created_at = datetime.now(timezone.utc)
	payment = Payment(
		customer_id="cust_state_2",
		amount="20.00",
		currency="USD",
		status=PAYMENT_STATUS_PENDING,
		idempotency_key="state-machine-invalid",
		state_history=[{"state": "pending", "timestamp": created_at.isoformat(), "reason": "created"}],
	)
	machine = PaymentStateMachine()

	with pytest.raises(InvalidStateTransition):
		machine.transition(payment, "success", reason="invalid")


@pytest.mark.anyio
async def test_state_history_appended() -> None:
	created_at = datetime.now(timezone.utc)
	payment = Payment(
		customer_id="cust_state_3",
		amount="33.00",
		currency="USD",
		status=PAYMENT_STATUS_PENDING,
		idempotency_key="state-machine-history",
		state_history=[{"state": "pending", "timestamp": created_at.isoformat(), "reason": "created"}],
	)
	machine = PaymentStateMachine()

	initial_len = len(payment.state_history)
	machine.transition(payment, "processing", reason="step-1")
	machine.transition(payment, "failed", reason="step-2")

	assert len(payment.state_history) == initial_len + 2
	assert payment.state_history[-2]["state"] == "processing"
	assert payment.state_history[-1]["state"] == "failed"
