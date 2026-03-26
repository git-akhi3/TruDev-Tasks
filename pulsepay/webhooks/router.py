from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from pulsepay.core.database import get_db
from pulsepay.observability.tracing import get_request_id

from .models import (
	WEBHOOK_STATUS_DEAD,
	WEBHOOK_STATUS_DELIVERED,
	WEBHOOK_STATUS_FAILED,
	WEBHOOK_STATUS_QUEUED,
)
from .schemas import (
	PaginatedWebhookEventsResponse,
	RegisterWebhookEndpointRequest,
	WebhookEndpointResponse,
	WebhookEventResponse,
)
from .service import WebhookService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _envelope(data: object) -> dict[str, object]:
	return {
		"data": data,
		"meta": {
			"request_id": get_request_id() or "",
			"timestamp": datetime.now(timezone.utc).isoformat(),
		},
	}


@router.get("/events")
async def list_webhook_events(
	page: int = Query(default=1, ge=1),
	limit: int = Query(default=20, ge=1, le=100),
	status_filter: str | None = Query(
		default=None,
		alias="status",
		pattern=f"^({WEBHOOK_STATUS_QUEUED}|{WEBHOOK_STATUS_DELIVERED}|{WEBHOOK_STATUS_FAILED}|{WEBHOOK_STATUS_DEAD})$",
	),
	db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
	service = WebhookService(db)
	events, total = await service.list_events(page=page, limit=limit, status=status_filter)
	response = PaginatedWebhookEventsResponse(
		items=[WebhookEventResponse.model_validate(event) for event in events],
		page=page,
		limit=limit,
		total=total,
	)
	return _envelope(response.model_dump(mode="json"))


@router.get("/events/{event_id}")
async def get_webhook_event(event_id: UUID, db: AsyncSession = Depends(get_db)) -> dict[str, object]:
	service = WebhookService(db)
	event = await service.get_event(event_id)
	response = WebhookEventResponse.model_validate(event)
	return _envelope(response.model_dump(mode="json"))


@router.post("/endpoints", status_code=status.HTTP_201_CREATED)
async def register_webhook_endpoint(
	payload: RegisterWebhookEndpointRequest,
	db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
	service = WebhookService(db)
	endpoint = await service.register_endpoint(payload)
	response = WebhookEndpointResponse.model_validate(endpoint)
	return _envelope(response.model_dump(mode="json"))


@router.delete("/endpoints/{endpoint_id}")
async def deactivate_webhook_endpoint(endpoint_id: UUID, db: AsyncSession = Depends(get_db)) -> dict[str, object]:
	service = WebhookService(db)
	endpoint = await service.deactivate_endpoint(endpoint_id)
	response = WebhookEndpointResponse.model_validate(endpoint)
	return _envelope(response.model_dump(mode="json"))
