from __future__ import annotations

import hashlib
import hmac
import json
import random
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pulsepay.jobs.queue import enqueue_job
from pulsepay.observability.logging import get_logger

from .models import (
	WEBHOOK_STATUS_DEAD,
	WEBHOOK_STATUS_DELIVERED,
	WEBHOOK_STATUS_FAILED,
	WEBHOOK_STATUS_QUEUED,
	WebhookEndpoint,
	WebhookEvent,
)

logger = get_logger(__name__)


class WebhookDispatcher:
	def __init__(self, session: AsyncSession) -> None:
		self._session = session

	async def dispatch(self, event_type: str, payload: dict[str, object], customer_id: str) -> list[WebhookEvent]:
		stmt = select(WebhookEndpoint).where(
			WebhookEndpoint.client_id == customer_id,
			WebhookEndpoint.is_active.is_(True),
		)
		result = await self._session.execute(stmt)
		endpoints = list(result.scalars().all())

		created_events: list[WebhookEvent] = []
		for endpoint in endpoints:
			event = WebhookEvent(
				endpoint_id=endpoint.id,
				event_type=event_type,
				payload=payload,
				status=WEBHOOK_STATUS_QUEUED,
			)
			self._session.add(event)
			await self._session.flush()
			await enqueue_job("deliver_webhook", {"event_id": str(event.id)})
			created_events.append(event)

		await self._session.commit()
		return created_events

	async def deliver(self, event_id: UUID) -> WebhookEvent | None:
		event = await self._session.get(WebhookEvent, event_id)
		if event is None:
			return None

		endpoint = await self._session.get(WebhookEndpoint, event.endpoint_id)
		if endpoint is None or not endpoint.is_active:
			event.status = WEBHOOK_STATUS_DEAD
			event.last_attempt_at = datetime.now(timezone.utc)
			event.next_retry_at = None
			await self._session.commit()
			return event

		now = datetime.now(timezone.utc)
		payload_json = json.dumps(event.payload, separators=(",", ":"), sort_keys=True)
		signature = hmac.new(
			endpoint.signing_secret.encode("utf-8"),
			payload_json.encode("utf-8"),
			hashlib.sha256,
		).hexdigest()

		headers = {
			"X-PulsePay-Signature": signature,
			"X-PulsePay-Timestamp": str(int(now.timestamp())),
			"Content-Type": "application/json",
		}

		delivery_success = False
		try:
			async with httpx.AsyncClient(timeout=2.0) as client:
				response = await client.post(endpoint.url, content=payload_json, headers=headers)
				delivery_success = response.is_success
		except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
			delivery_success = False

		event.last_attempt_at = now
		event.attempt_count += 1

		if delivery_success:
			event.status = WEBHOOK_STATUS_DELIVERED
			event.next_retry_at = None
			await self._session.commit()
			logger.info(
				"webhook_delivered",
				extra={
					"event_id": str(event.id),
					"attempt_count": event.attempt_count,
				},
			)
			return event

		if event.attempt_count >= 5:
			event.status = WEBHOOK_STATUS_DEAD
			event.next_retry_at = None
			await self._session.commit()
			logger.info(
				"webhook_dead_lettered",
				extra={
					"event_id": str(event.id),
					"attempt_count": event.attempt_count,
				},
			)
			return event

		base_delay = float(2 ** event.attempt_count)
		jitter = random.random()
		delay_seconds = base_delay + jitter
		next_retry_at = now + timedelta(seconds=delay_seconds)

		event.status = WEBHOOK_STATUS_FAILED
		event.next_retry_at = next_retry_at
		await enqueue_job(
			"deliver_webhook",
			{"event_id": str(event.id), "attempt": event.attempt_count, "next_run_at": next_retry_at.isoformat()},
			run_at=next_retry_at,
		)
		await self._session.commit()
		logger.info(
			"webhook_retry_scheduled",
			extra={
				"event_id": str(event.id),
				"attempt_count": event.attempt_count,
				"next_retry_delay_seconds": round(delay_seconds, 3),
			},
		)
		return event
