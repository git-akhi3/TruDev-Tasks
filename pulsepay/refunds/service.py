from __future__ import annotations

import random
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pulsepay.core.exceptions import (
	InsufficientRefundableAmount,
	InvalidStateTransition,
	PaymentNotFound,
)
from pulsepay.jobs.queue import enqueue_job
from pulsepay.observability.logging import get_logger
from pulsepay.payments.models import PAYMENT_STATUS_SUCCESS, Payment
from pulsepay.webhooks.dispatcher import WebhookDispatcher

from .models import (
	REFUND_STATUS_COMPLETED,
	REFUND_STATUS_FAILED,
	REFUND_STATUS_PENDING,
	REFUND_STATUS_PROCESSING,
	Refund,
)


class RefundService:
	def __init__(self, session: AsyncSession) -> None:
		self._session = session
		self._logger = get_logger(__name__)

	async def initiate_refund(
		self,
		payment_id: UUID,
		amount: Decimal | None,
		idempotency_key: str,
		reason: str | None,
	) -> Refund:
		existing = await self._get_refund_by_idempotency_key(idempotency_key)
		if existing is not None:
			return existing

		payment = await self._session.get(Payment, payment_id)
		if payment is None:
			raise PaymentNotFound(f"Payment {payment_id} was not found.")

		if payment.status != PAYMENT_STATUS_SUCCESS:
			raise InvalidStateTransition(
				f"Invalid payment state transition for refund: payment {payment_id} is in state {payment.status}.",
			)

		existing_refunded_amount = await self._sum_non_failed_refunds(payment_id)
		remaining_refundable = payment.amount - existing_refunded_amount
		if remaining_refundable <= Decimal("0"):
			raise InsufficientRefundableAmount(
				f"No refundable amount remaining for payment {payment_id}. Remaining refundable amount: {remaining_refundable}.",
			)

		requested_amount = remaining_refundable if amount is None else amount
		if requested_amount + existing_refunded_amount > payment.amount:
			raise InsufficientRefundableAmount(
				f"Requested refund exceeds refundable amount for payment {payment_id}. Remaining refundable amount: {remaining_refundable}.",
			)

		refund = Refund(
			payment_id=payment.id,
			customer_id=payment.customer_id,
			amount=requested_amount,
			currency=payment.currency,
			status=REFUND_STATUS_PENDING,
			reason=reason,
			idempotency_key=idempotency_key,
		)
		self._session.add(refund)
		await self._session.flush()

		await self._write_ledger_entry(refund, event_type="refund.initiated")
		await enqueue_job("process_refund", {"refund_id": str(refund.id)})

		await self._session.commit()
		await self._session.refresh(refund)
		return refund

	async def process_refund(self, refund_id: UUID) -> Refund:
		refund = await self._session.get(Refund, refund_id)
		if refund is None:
			raise PaymentNotFound(f"Refund {refund_id} was not found.")

		if refund.status in {REFUND_STATUS_COMPLETED, REFUND_STATUS_FAILED}:
			return refund

		self._transition(refund, REFUND_STATUS_PROCESSING)
		await self._session.flush()

		if random.random() < 0.95:
			self._transition(refund, REFUND_STATUS_COMPLETED)
			await self._write_ledger_entry(refund, event_type="refund.completed")

			payment = await self._session.get(Payment, refund.payment_id)
			if payment is not None:
				dispatcher = WebhookDispatcher(self._session)
				await dispatcher.dispatch(
					event_type="refund.completed",
					payload={
						"refund_id": str(refund.id),
						"payment_id": str(refund.payment_id),
						"customer_id": refund.customer_id,
						"amount": str(refund.amount),
						"currency": refund.currency,
						"status": refund.status,
					},
					customer_id=payment.customer_id,
				)
			else:
				await self._session.commit()

			await self._session.refresh(refund)
			return refund

		self._transition(refund, REFUND_STATUS_FAILED)
		await self._session.commit()
		await self._session.refresh(refund)
		return refund

	async def list_refunds(self, payment_id: UUID) -> list[Refund]:
		stmt: Select[tuple[Refund]] = (
			select(Refund)
			.where(Refund.payment_id == payment_id)
			.order_by(Refund.created_at.desc())
		)
		result = await self._session.execute(stmt)
		return list(result.scalars().all())

	async def _sum_non_failed_refunds(self, payment_id: UUID) -> Decimal:
		stmt = select(func.coalesce(func.sum(Refund.amount), Decimal("0.00"))).where(
			Refund.payment_id == payment_id,
			Refund.status != REFUND_STATUS_FAILED,
		)
		result = await self._session.execute(stmt)
		total = result.scalar_one()
		return Decimal(total)

	async def _get_refund_by_idempotency_key(self, idempotency_key: str) -> Refund | None:
		stmt = select(Refund).where(Refund.idempotency_key == idempotency_key)
		result = await self._session.execute(stmt)
		return result.scalar_one_or_none()

	def _transition(self, refund: Refund, target_status: str) -> Refund:
		allowed: dict[str, set[str]] = {
			REFUND_STATUS_PENDING: {REFUND_STATUS_PROCESSING},
			REFUND_STATUS_PROCESSING: {REFUND_STATUS_COMPLETED, REFUND_STATUS_FAILED},
		}
		current_status = refund.status
		next_allowed = allowed.get(current_status, set())
		if target_status not in next_allowed:
			raise InvalidStateTransition(
				f"Invalid refund state transition: {current_status} -> {target_status}",
			)
		refund.status = target_status
		return refund

	async def _write_ledger_entry(self, refund: Refund, event_type: str) -> None:
		self._logger.info(
			"ledger_entry_written",
			extra={
				"event_type": event_type,
				"refund_id": str(refund.id),
				"payment_id": str(refund.payment_id),
				"amount": str(refund.amount),
				"currency": refund.currency,
			},
		)
