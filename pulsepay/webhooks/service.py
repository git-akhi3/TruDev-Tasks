from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pulsepay.core.exceptions import PulsePayException

from .models import WebhookEndpoint, WebhookEvent
from .schemas import RegisterWebhookEndpointRequest


class WebhookEventNotFound(PulsePayException):
	error_code = "WEBHOOK_EVENT_NOT_FOUND"
	status_code = HTTPStatus.NOT_FOUND


class WebhookEndpointNotFound(PulsePayException):
	error_code = "WEBHOOK_ENDPOINT_NOT_FOUND"
	status_code = HTTPStatus.NOT_FOUND


class WebhookService:
	def __init__(self, session: AsyncSession) -> None:
		self._session = session

	async def list_events(
		self,
		page: int,
		limit: int,
		status: str | None = None,
	) -> tuple[list[WebhookEvent], int]:
		effective_limit = min(limit, 100)
		offset = (page - 1) * effective_limit

		filters = []
		if status is not None:
			filters.append(WebhookEvent.status == status)

		events_stmt: Select[tuple[WebhookEvent]] = (
			select(WebhookEvent)
			.where(*filters)
			.order_by(WebhookEvent.created_at.desc())
			.offset(offset)
			.limit(effective_limit)
		)
		total_stmt = select(func.count(WebhookEvent.id)).where(*filters)

		events_result = await self._session.execute(events_stmt)
		total_result = await self._session.execute(total_stmt)

		events = list(events_result.scalars().all())
		total = int(total_result.scalar_one())
		return events, total

	async def get_event(self, event_id: UUID) -> WebhookEvent:
		event = await self._session.get(WebhookEvent, event_id)
		if event is None:
			raise WebhookEventNotFound(f"Webhook event {event_id} was not found.")
		return event

	async def register_endpoint(self, request: RegisterWebhookEndpointRequest) -> WebhookEndpoint:
		endpoint = WebhookEndpoint(
			client_id=request.client_id,
			url=str(request.url),
			signing_secret=request.signing_secret,
			is_active=True,
		)
		self._session.add(endpoint)
		await self._session.commit()
		await self._session.refresh(endpoint)
		return endpoint

	async def deactivate_endpoint(self, endpoint_id: UUID) -> WebhookEndpoint:
		endpoint = await self._session.get(WebhookEndpoint, endpoint_id)
		if endpoint is None:
			raise WebhookEndpointNotFound(f"Webhook endpoint {endpoint_id} was not found.")

		endpoint.is_active = False
		await self._session.commit()
		await self._session.refresh(endpoint)
		return endpoint
