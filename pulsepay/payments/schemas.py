from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreatePaymentRequest(BaseModel):
	customer_id: str = Field(min_length=1, max_length=128)
	amount: Decimal = Field(gt=0)
	currency: str = Field(min_length=3, max_length=3)
	metadata: dict[str, object] | None = None

	@field_validator("currency")
	@classmethod
	def validate_currency(cls, value: str) -> str:
		return value.upper()


class ConfirmPaymentRequest(BaseModel):
	metadata: dict[str, object] | None = None


class PaymentStateHistoryEntry(BaseModel):
	state: str
	timestamp: str
	reason: str | None = None


class PaymentResponse(BaseModel):
	model_config = ConfigDict(from_attributes=True, populate_by_name=True)

	id: UUID
	customer_id: str
	amount: Decimal
	currency: str
	status: str
	failure_reason: str | None
	failure_class: str | None
	retry_count: int
	idempotency_key: str
	metadata: dict[str, object] | None = Field(default=None, alias="payment_metadata")
	state_history: list[PaymentStateHistoryEntry]
	confirmed_at: datetime | None
	created_at: datetime
	updated_at: datetime


class PaginatedPaymentsResponse(BaseModel):
	items: list[PaymentResponse]
	page: int
	limit: int
	total: int
