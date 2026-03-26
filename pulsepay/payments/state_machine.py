from __future__ import annotations

from datetime import datetime, timezone

from pulsepay.core.exceptions import InvalidStateTransition

from .models import Payment


class PaymentStateMachine:
	_valid_transitions: dict[str, set[str]] = {
		"pending": {"processing"},
		"processing": {"success", "failed"},
	}

	def transition(self, payment: Payment, target_state: str, reason: str | None = None) -> Payment:
		current_state = payment.status
		allowed = self._valid_transitions.get(current_state, set())
		if target_state not in allowed:
			raise InvalidStateTransition(
				f"Invalid payment state transition: {current_state} -> {target_state}",
			)

		history = list(payment.state_history)
		history.append(
			{
				"state": target_state,
				"timestamp": datetime.now(timezone.utc).isoformat(),
				"reason": reason,
			}
		)

		payment.status = target_state
		payment.state_history = history
		return payment
