from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from pulsepay.core.database import Base

PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_PROCESSING = "processing"
PAYMENT_STATUS_SUCCESS = "success"
PAYMENT_STATUS_FAILED = "failed"

FAILURE_CLASS_SOFT = "soft"
FAILURE_CLASS_HARD = "hard"


class Payment(Base):
	__tablename__ = "payments"
	__table_args__ = (
		UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
		UniqueConstraint("customer_id", "idempotency_key", name="uq_payments_customer_idempotency_key"),
		CheckConstraint(
			"status IN ('pending', 'processing', 'success', 'failed')",
			name="ck_payments_status",
		),
		CheckConstraint(
			"failure_class IS NULL OR failure_class IN ('soft', 'hard')",
			name="ck_payments_failure_class",
		),
		Index("ix_payments_customer_id", "customer_id"),
		Index("ix_payments_status", "status"),
	)

	customer_id: Mapped[str] = mapped_column(String(128), nullable=False)
	amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
	currency: Mapped[str] = mapped_column(String(3), nullable=False)
	status: Mapped[str] = mapped_column(String(32), nullable=False, default=PAYMENT_STATUS_PENDING)
	failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
	failure_class: Mapped[str | None] = mapped_column(String(16), nullable=True)
	retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
	idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
	payment_metadata: Mapped[dict[str, object] | None] = mapped_column("metadata", JSONB, nullable=True)
	state_history: Mapped[list[dict[str, str | None]]] = mapped_column(
		MutableList.as_mutable(JSONB),
		nullable=False,
		default=list,
		server_default=text("'[]'::jsonb"),
	)
	confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IdempotencyRecord(Base):
	__tablename__ = "idempotency_records"
	__table_args__ = (
		UniqueConstraint("key", name="uq_idempotency_records_key"),
		Index("ix_idempotency_records_key", "key"),
	)

	key: Mapped[str] = mapped_column(String(255), nullable=False)
	response_body: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
	status_code: Mapped[int] = mapped_column(Integer, nullable=False)
	expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
