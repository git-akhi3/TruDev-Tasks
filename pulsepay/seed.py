from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pulsepay.ledger.models import LedgerEntry
from pulsepay.payments.models import (
	PAYMENT_STATUS_FAILED,
	PAYMENT_STATUS_PENDING,
	PAYMENT_STATUS_PROCESSING,
	PAYMENT_STATUS_SUCCESS,
	Payment,
)
from pulsepay.refunds.models import REFUND_STATUS_COMPLETED, Refund
from pulsepay.webhooks.models import WebhookEndpoint

SEEDED_API_CLIENTS: dict[str, str] = {}

_CLIENT_IDS: tuple[str, ...] = ("client_alpha", "client_beta", "client_gamma")


def _api_key_for(client_id: str) -> str:
	return f"ppk_{uuid5(NAMESPACE_URL, f'pulsepay:{client_id}').hex}"


def _half_amount(amount: Decimal) -> Decimal:
	return (amount / Decimal("2")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def _get_payment_by_idempotency_key(session: AsyncSession, idempotency_key: str) -> Payment | None:
	stmt: Select[tuple[Payment]] = select(Payment).where(Payment.idempotency_key == idempotency_key)
	result = await session.execute(stmt)
	return result.scalar_one_or_none()


async def _get_refund_by_idempotency_key(session: AsyncSession, idempotency_key: str) -> Refund | None:
	stmt: Select[tuple[Refund]] = select(Refund).where(Refund.idempotency_key == idempotency_key)
	result = await session.execute(stmt)
	return result.scalar_one_or_none()


async def seed_data(session_factory: async_sessionmaker[AsyncSession]) -> None:
	now = datetime.now(timezone.utc)

	for client_id in _CLIENT_IDS:
		SEEDED_API_CLIENTS[client_id] = _api_key_for(client_id)

	async with session_factory() as session:
		await _seed_webhook_endpoints(session)
		payments = await _seed_payments(session, now)
		await session.flush()
		await _seed_ledger_entries(session, payments)
		await _seed_refunds(session, payments)
		await session.commit()


async def _seed_webhook_endpoints(session: AsyncSession) -> None:
	for client_id in _CLIENT_IDS:
		target_url = f"https://webhook.site/test-{client_id}"
		count_stmt = select(func.count(WebhookEndpoint.id)).where(
			WebhookEndpoint.client_id == client_id,
			WebhookEndpoint.url == target_url,
		)
		count_result = await session.execute(count_stmt)
		existing_count = int(count_result.scalar_one())

		for slot in range(existing_count + 1, 3):
			signing_secret = f"seed-signing-secret-{client_id}-{slot}"
			session.add(
				WebhookEndpoint(
					client_id=client_id,
					url=target_url,
					signing_secret=signing_secret,
					is_active=True,
				)
			)


async def _seed_payments(session: AsyncSession, now: datetime) -> list[Payment]:
	seed_specs: list[tuple[str, str, Decimal]] = [
		(PAYMENT_STATUS_SUCCESS, _CLIENT_IDS[0], Decimal("125.00")),
		(PAYMENT_STATUS_SUCCESS, _CLIENT_IDS[1], Decimal("89.50")),
		(PAYMENT_STATUS_SUCCESS, _CLIENT_IDS[2], Decimal("210.75")),
		(PAYMENT_STATUS_SUCCESS, _CLIENT_IDS[0], Decimal("56.25")),
		(PAYMENT_STATUS_FAILED, _CLIENT_IDS[1], Decimal("72.10")),
		(PAYMENT_STATUS_FAILED, _CLIENT_IDS[2], Decimal("41.30")),
		(PAYMENT_STATUS_PENDING, _CLIENT_IDS[0], Decimal("15.00")),
		(PAYMENT_STATUS_PENDING, _CLIENT_IDS[1], Decimal("19.99")),
		(PAYMENT_STATUS_PROCESSING, _CLIENT_IDS[2], Decimal("199.99")),
		(PAYMENT_STATUS_PROCESSING, _CLIENT_IDS[0], Decimal("305.00")),
	]

	payments: list[Payment] = []
	for index, (status, customer_id, amount) in enumerate(seed_specs, start=1):
		idempotency_key = f"seed-payment-{index}"
		existing_payment = await _get_payment_by_idempotency_key(session, idempotency_key)
		if existing_payment is not None:
			payments.append(existing_payment)
			continue

		created_at = now - timedelta(minutes=(30 - index))
		confirmed_at = created_at + timedelta(seconds=(20 + index * 2)) if status == PAYMENT_STATUS_SUCCESS else None
		state_history: list[dict[str, str | None]] = [
			{
				"state": PAYMENT_STATUS_PENDING,
				"timestamp": created_at.isoformat(),
				"reason": "seed_created",
			}
		]
		if status in {PAYMENT_STATUS_PROCESSING, PAYMENT_STATUS_SUCCESS, PAYMENT_STATUS_FAILED}:
			state_history.append(
				{
					"state": PAYMENT_STATUS_PROCESSING,
					"timestamp": (created_at + timedelta(seconds=5)).isoformat(),
					"reason": "seed_processing",
				}
			)
		if status == PAYMENT_STATUS_SUCCESS:
			if confirmed_at is None:
				confirmed_at = created_at + timedelta(seconds=20)
			state_history.append(
				{
					"state": PAYMENT_STATUS_SUCCESS,
					"timestamp": confirmed_at.isoformat(),
					"reason": "seed_success",
				}
			)
		if status == PAYMENT_STATUS_FAILED:
			state_history.append(
				{
					"state": PAYMENT_STATUS_FAILED,
					"timestamp": (created_at + timedelta(seconds=18)).isoformat(),
					"reason": "seed_failure",
				}
			)

		payment = Payment(
			customer_id=customer_id,
			amount=amount,
			currency="USD",
			status=status,
			failure_reason="seed_failure" if status == PAYMENT_STATUS_FAILED else None,
			failure_class="hard" if status == PAYMENT_STATUS_FAILED else None,
			retry_count=1 if status in {PAYMENT_STATUS_SUCCESS, PAYMENT_STATUS_FAILED} else 0,
			idempotency_key=idempotency_key,
			payment_metadata={"seed": True, "index": index},
			state_history=state_history,
			confirmed_at=confirmed_at,
			created_at=created_at,
			updated_at=created_at,
		)
		session.add(payment)
		payments.append(payment)

	return payments


async def _seed_ledger_entries(session: AsyncSession, payments: list[Payment]) -> None:
	for payment in payments:
		if payment.status not in {PAYMENT_STATUS_SUCCESS, PAYMENT_STATUS_FAILED}:
			continue

		entry_type = "payment.succeeded" if payment.status == PAYMENT_STATUS_SUCCESS else "payment.failed"
		existing_stmt: Select[tuple[LedgerEntry]] = select(LedgerEntry).where(
			LedgerEntry.payment_id == payment.id,
			LedgerEntry.entry_type == entry_type,
		)
		existing_result = await session.execute(existing_stmt)
		existing_entry = existing_result.scalar_one_or_none()
		if existing_entry is not None:
			continue

		session.add(
			LedgerEntry(
				payment_id=payment.id,
				entry_type=entry_type,
				amount=payment.amount,
				currency=payment.currency,
				entry_metadata={"seed": True},
			)
		)


async def _seed_refunds(session: AsyncSession, payments: list[Payment]) -> None:
	successful_payments = [payment for payment in payments if payment.status == PAYMENT_STATUS_SUCCESS]
	successful_payments = sorted(successful_payments, key=lambda payment: payment.created_at)

	for index, payment in enumerate(successful_payments[:2], start=1):
		idempotency_key = f"seed-refund-{index}"
		existing_refund = await _get_refund_by_idempotency_key(session, idempotency_key)
		if existing_refund is not None:
			continue

		session.add(
			Refund(
				payment_id=payment.id,
				customer_id=payment.customer_id,
				amount=_half_amount(payment.amount),
				currency=payment.currency,
				status=REFUND_STATUS_COMPLETED,
				reason="seed_refund",
				idempotency_key=idempotency_key,
			)
		)
