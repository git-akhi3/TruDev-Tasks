from __future__ import annotations

from collections.abc import Awaitable, Callable
import random
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pulsepay.core.config import settings
from pulsepay.core.database import SessionLocal
from pulsepay.core.exceptions import PaymentNotFound
from pulsepay.observability.logging import get_logger
from pulsepay.payments.service import PaymentService, SoftPaymentProcessingFailure
from pulsepay.refunds.service import RefundService
from pulsepay.webhooks.dispatcher import WebhookDispatcher

from .queue import enqueue_job

logger = get_logger(__name__)


def _next_retry_schedule(retry_count: int) -> tuple[float, datetime]:
	base_delay_seconds = float(2 ** retry_count)
	jitter_seconds = random.random()
	total_delay = base_delay_seconds + jitter_seconds
	next_run_at = datetime.now(timezone.utc) + timedelta(seconds=total_delay)
	return total_delay, next_run_at


def _parse_payment_id(payload: dict[str, object]) -> UUID:
	raw_payment_id = payload.get("payment_id")
	if not isinstance(raw_payment_id, str):
		raise ValueError("Job payload must include payment_id as a UUID string.")
	return UUID(raw_payment_id)


def _parse_event_id(payload: dict[str, object]) -> UUID:
	raw_event_id = payload.get("event_id")
	if not isinstance(raw_event_id, str):
		raise ValueError("Job payload must include event_id as a UUID string.")
	return UUID(raw_event_id)


def _parse_refund_id(payload: dict[str, object]) -> UUID:
	raw_refund_id = payload.get("refund_id")
	if not isinstance(raw_refund_id, str):
		raise ValueError("Job payload must include refund_id as a UUID string.")
	return UUID(raw_refund_id)


async def process_payment(payload: dict[str, object]) -> None:
	payment_id = _parse_payment_id(payload)

	async with SessionLocal() as session:
		service = PaymentService(session)
		try:
			payment = await service.confirm_payment(payment_id)
			logger.info(
				"payment_processing_completed",
				extra={
					"job_type": "process_payment",
					"payment_id": str(payment_id),
					"attempt_number": payment.retry_count,
					"failure_class": payment.failure_class,
					"next_retry_delay_seconds": 0.0,
				},
			)
		except SoftPaymentProcessingFailure as exc:
			payment = await service.get_payment(payment_id)
			next_retry_delay, next_run_at = _next_retry_schedule(payment.retry_count)
			retry_payload: dict[str, object] = {
				"payment_id": str(payment_id),
				"attempt_number": payment.retry_count,
				"next_run_at": next_run_at.isoformat(),
			}
			await enqueue_job("retry_payment", retry_payload, run_at=next_run_at)
			logger.info(
				"payment_processing_soft_failure",
				extra={
					"job_type": "process_payment",
					"payment_id": str(payment_id),
					"attempt_number": exc.attempt_number,
					"failure_class": "soft",
					"next_retry_delay_seconds": round(next_retry_delay, 3),
				},
			)
		except PaymentNotFound:
			logger.info(
				"payment_processing_skipped",
				extra={
					"job_type": "process_payment",
					"payment_id": str(payment_id),
					"attempt_number": 0,
					"failure_class": "hard",
					"next_retry_delay_seconds": 0.0,
				},
			)


async def retry_payment(payload: dict[str, object]) -> None:
	payment_id = _parse_payment_id(payload)
	max_attempts = settings().MAX_PAYMENT_RETRY_ATTEMPTS

	async with SessionLocal() as session:
		service = PaymentService(session)
		payment = await service.get_payment(payment_id)

		if payment.retry_count >= max_attempts:
			failed_payment = await service.mark_payment_failed_max_retries(payment_id)
			logger.info(
				"payment_processing_max_retries_exceeded",
				extra={
					"job_type": "retry_payment",
					"payment_id": str(payment_id),
					"attempt_number": failed_payment.retry_count,
					"failure_class": "hard",
					"next_retry_delay_seconds": 0.0,
				},
			)
			return

		try:
			confirmed_payment = await service.confirm_payment(payment_id)
			logger.info(
				"payment_retry_completed",
				extra={
					"job_type": "retry_payment",
					"payment_id": str(payment_id),
					"attempt_number": confirmed_payment.retry_count,
					"failure_class": confirmed_payment.failure_class,
					"next_retry_delay_seconds": 0.0,
				},
			)
		except SoftPaymentProcessingFailure as exc:
			updated_payment = await service.get_payment(payment_id)
			if updated_payment.retry_count >= max_attempts:
				failed_payment = await service.mark_payment_failed_max_retries(payment_id)
				logger.info(
					"payment_retry_terminal_failure",
					extra={
						"job_type": "retry_payment",
						"payment_id": str(payment_id),
						"attempt_number": failed_payment.retry_count,
						"failure_class": "hard",
						"next_retry_delay_seconds": 0.0,
					},
				)
				return

			next_retry_delay, next_run_at = _next_retry_schedule(updated_payment.retry_count)
			retry_payload: dict[str, object] = {
				"payment_id": str(payment_id),
				"attempt_number": updated_payment.retry_count,
				"next_run_at": next_run_at.isoformat(),
			}
			await enqueue_job("retry_payment", retry_payload, run_at=next_run_at)
			logger.info(
				"payment_retry_soft_failure",
				extra={
					"job_type": "retry_payment",
					"payment_id": str(payment_id),
					"attempt_number": exc.attempt_number,
					"failure_class": "soft",
					"next_retry_delay_seconds": round(next_retry_delay, 3),
				},
			)


async def deliver_webhook(payload: dict[str, object]) -> None:
	event_id = _parse_event_id(payload)
	async with SessionLocal() as session:
		dispatcher = WebhookDispatcher(session)
		event = await dispatcher.deliver(event_id)
		if event is None:
			logger.info(
				"webhook_delivery_skipped",
				extra={
					"job_type": "deliver_webhook",
					"event_id": str(event_id),
					"attempt_number": 0,
					"failure_class": "hard",
					"next_retry_delay_seconds": 0.0,
				},
			)


async def process_refund(payload: dict[str, object]) -> None:
	refund_id = _parse_refund_id(payload)
	async with SessionLocal() as session:
		service = RefundService(session)
		await service.process_refund(refund_id)


JobHandler = Callable[[dict[str, object]], Awaitable[None]]


_job_handlers: dict[str, JobHandler] = {}


def register_handler(job_type: str, fn: JobHandler) -> None:
	_job_handlers[job_type] = fn


def get_handler(job_type: str) -> JobHandler | None:
	return _job_handlers.get(job_type)


register_handler("process_payment", process_payment)
register_handler("retry_payment", retry_payment)
register_handler("deliver_webhook", deliver_webhook)
register_handler("process_refund", process_refund)
