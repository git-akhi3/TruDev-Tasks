from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pulsepay.core.config import settings
from pulsepay.core.exceptions import (
	IdempotencyConflict,
	PaymentAlreadyProcessed,
	PaymentNotFound,
	PulsePayException,
)
from pulsepay.jobs.queue import enqueue_job
from pulsepay.observability.logging import get_logger

from .models import (
	FAILURE_CLASS_HARD,
	FAILURE_CLASS_SOFT,
	PAYMENT_STATUS_FAILED,
	PAYMENT_STATUS_PENDING,
	PAYMENT_STATUS_PROCESSING,
	PAYMENT_STATUS_SUCCESS,
	IdempotencyRecord,
	Payment,
)
from .schemas import CreatePaymentRequest, PaymentResponse
from .state_machine import PaymentStateMachine


class SoftPaymentProcessingFailure(PulsePayException):
	error_code = "SOFT_PAYMENT_PROCESSING_FAILURE"
	status_code = HTTPStatus.SERVICE_UNAVAILABLE

	def __init__(self, detail: str, attempt_number: int, max_attempts: int) -> None:
		super().__init__(detail)
		self.attempt_number = attempt_number
		self.max_attempts = max_attempts


class PaymentService:
	def __init__(self, session: AsyncSession) -> None:
		self._session = session
		self._state_machine = PaymentStateMachine()
		self._logger = get_logger(__name__)

	async def create_payment(
		self,
		request: CreatePaymentRequest,
		idempotency_key: str,
	) -> tuple[PaymentResponse, int]:
		now = datetime.now(timezone.utc)
		existing_record = await self._get_idempotency_record(idempotency_key)
		if existing_record is not None:
			if existing_record.expires_at > now:
				if "payment" not in existing_record.response_body:
					raise IdempotencyConflict("Stored idempotent response payload is invalid.")
				payment_payload = existing_record.response_body["payment"]
				return PaymentResponse.model_validate(payment_payload), int(existing_record.status_code)
			await self._session.delete(existing_record)
			await self._session.flush()

		payment = Payment(
			customer_id=request.customer_id,
			amount=request.amount,
			currency=request.currency,
			status=PAYMENT_STATUS_PENDING,
			idempotency_key=idempotency_key,
			payment_metadata=request.metadata,
			state_history=[
				{
					"state": PAYMENT_STATUS_PENDING,
					"timestamp": now.isoformat(),
					"reason": "payment_created",
				}
			],
		)
		self._session.add(payment)
		await self._session.flush()
		await self._session.refresh(payment)

		response_model = PaymentResponse.model_validate(payment)
		response_payload = {"payment": response_model.model_dump(mode="json")}
		record = IdempotencyRecord(
			key=idempotency_key,
			response_body=response_payload,
			status_code=int(HTTPStatus.CREATED),
			expires_at=now + timedelta(hours=24),
		)
		self._session.add(record)

		await self._enqueue_process_job(payment.id)
		await self._session.commit()
		return response_model, int(HTTPStatus.CREATED)

	async def confirm_payment(self, payment_id: UUID, metadata: dict[str, object] | None = None) -> Payment:
		payment = await self._get_payment_by_id(payment_id)
		if payment.status in {PAYMENT_STATUS_SUCCESS, PAYMENT_STATUS_FAILED}:
			raise PaymentAlreadyProcessed(f"Payment {payment_id} is already terminal.")

		if payment.status == PAYMENT_STATUS_PENDING:
			self._state_machine.transition(payment, PAYMENT_STATUS_PROCESSING, reason="processor_started")
		if metadata is not None:
			payment.payment_metadata = metadata
		payment.retry_count += 1
		await self._session.flush()

		outcome = random.random()
		if outcome < 0.85:
			self._state_machine.transition(payment, PAYMENT_STATUS_SUCCESS, reason="processor_authorized")
			payment.failure_reason = None
			payment.failure_class = None
			payment.confirmed_at = datetime.now(timezone.utc)
			await self._write_ledger_entry(payment)
			await self._emit_webhook_event(payment)
			await self._session.commit()
			await self._session.refresh(payment)
			return payment

		if outcome < 0.95:
			payment.failure_class = FAILURE_CLASS_SOFT
			payment.failure_reason = "Temporary upstream processor failure"
			await self._session.commit()
			max_retry_attempts = settings().MAX_PAYMENT_RETRY_ATTEMPTS
			if payment.retry_count >= max_retry_attempts:
				return await self.mark_payment_failed_max_retries(payment_id)
			raise SoftPaymentProcessingFailure(
				f"Payment {payment_id} failed with a retriable processor error (attempt {payment.retry_count}/{max_retry_attempts}).",
				attempt_number=payment.retry_count,
				max_attempts=max_retry_attempts,
			)

		self._state_machine.transition(payment, PAYMENT_STATUS_FAILED, reason="processor_hard_failure")
		payment.failure_class = FAILURE_CLASS_HARD
		payment.failure_reason = "Processor declined the payment"
		await self._session.commit()
		await self._session.refresh(payment)
		return payment

	async def mark_payment_failed_max_retries(self, payment_id: UUID) -> Payment:
		payment = await self._get_payment_by_id(payment_id)
		if payment.status == PAYMENT_STATUS_FAILED:
			return payment
		if payment.status == PAYMENT_STATUS_SUCCESS:
			raise PaymentAlreadyProcessed(f"Payment {payment_id} is already terminal.")

		if payment.status == PAYMENT_STATUS_PENDING:
			self._state_machine.transition(payment, PAYMENT_STATUS_PROCESSING, reason="processor_started")

		self._state_machine.transition(payment, PAYMENT_STATUS_FAILED, reason="max_retries_exceeded")
		payment.failure_class = FAILURE_CLASS_HARD
		payment.failure_reason = "max_retries_exceeded"
		await self._emit_webhook_event(payment, event_type="payment.failed")
		await self._session.commit()
		await self._session.refresh(payment)
		return payment

	async def get_payment(self, payment_id: UUID) -> Payment:
		return await self._get_payment_by_id(payment_id)

	async def list_payments(
		self,
		page: int,
		limit: int,
		customer_id: str | None = None,
		status: str | None = None,
	) -> tuple[list[Payment], int]:
		effective_limit = min(limit, 100)
		offset = (page - 1) * effective_limit

		filters = []
		if customer_id is not None:
			filters.append(Payment.customer_id == customer_id)
		if status is not None:
			filters.append(Payment.status == status)

		payments_query: Select[tuple[Payment]] = (
			select(Payment)
			.where(*filters)
			.order_by(Payment.created_at.desc())
			.offset(offset)
			.limit(effective_limit)
		)
		count_query = select(func.count(Payment.id)).where(*filters)

		payments_result = await self._session.execute(payments_query)
		count_result = await self._session.execute(count_query)

		payments = list(payments_result.scalars().all())
		total = int(count_result.scalar_one())
		return payments, total

	async def _get_payment_by_id(self, payment_id: UUID) -> Payment:
		payment = await self._session.get(Payment, payment_id)
		if payment is None:
			raise PaymentNotFound(f"Payment {payment_id} was not found.")
		return payment

	async def _get_idempotency_record(self, key: str) -> IdempotencyRecord | None:
		stmt = select(IdempotencyRecord).where(IdempotencyRecord.key == key)
		result = await self._session.execute(stmt)
		return result.scalar_one_or_none()

	async def _enqueue_process_job(self, payment_id: UUID) -> None:
		await enqueue_job(
			"process_payment",
			{"payment_id": str(payment_id)},
		)

	async def _write_ledger_entry(self, payment: Payment) -> None:
		self._logger.info(
			"ledger_entry_written",
			extra={
				"payment_id": str(payment.id),
				"amount": str(payment.amount),
				"currency": payment.currency,
			},
		)

	async def _emit_webhook_event(self, payment: Payment, event_type: str = "payment.succeeded") -> None:
		self._logger.info(
			"webhook_emitted",
			extra={
				"event_type": event_type,
				"payment_id": str(payment.id),
			},
		)
