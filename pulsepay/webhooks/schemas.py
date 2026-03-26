from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class RegisterWebhookEndpointRequest(BaseModel):
	client_id: str = Field(min_length=1, max_length=128)
	url: HttpUrl
	signing_secret: str = Field(min_length=1, max_length=255)


class WebhookEndpointResponse(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: UUID
	client_id: str
	url: str
	is_active: bool
	created_at: datetime
	updated_at: datetime


class WebhookEventResponse(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: UUID
	endpoint_id: UUID
	event_type: str
	payload: dict[str, object]
	status: str
	attempt_count: int
	last_attempt_at: datetime | None
	next_retry_at: datetime | None
	created_at: datetime
	updated_at: datetime


class PaginatedWebhookEventsResponse(BaseModel):
	items: list[WebhookEventResponse]
	page: int
	limit: int
	total: int
