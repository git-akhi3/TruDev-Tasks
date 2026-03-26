from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InitiateRefundRequest(BaseModel):
	amount: Decimal | None = Field(default=None, gt=0)
	reason: str | None = Field(default=None, max_length=512)


class RefundResponse(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: UUID
	payment_id: UUID
	customer_id: str
	amount: Decimal
	currency: str
	status: str
	reason: str | None
	idempotency_key: str
	created_at: datetime
	updated_at: datetime


class RefundListResponse(BaseModel):
	items: list[RefundResponse]
