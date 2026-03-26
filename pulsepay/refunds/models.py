from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from pulsepay.core.database import Base

REFUND_STATUS_PENDING = "pending"
REFUND_STATUS_PROCESSING = "processing"
REFUND_STATUS_COMPLETED = "completed"
REFUND_STATUS_FAILED = "failed"


class Refund(Base):
	__tablename__ = "refunds"
	__table_args__ = (
		UniqueConstraint("idempotency_key", name="uq_refunds_idempotency_key"),
		CheckConstraint(
			"status IN ('pending', 'processing', 'completed', 'failed')",
			name="ck_refunds_status",
		),
		Index("ix_refunds_payment_id", "payment_id"),
		Index("ix_refunds_customer_id", "customer_id"),
	)

	payment_id: Mapped[UUID] = mapped_column(
		PGUUID(as_uuid=True),
		ForeignKey("payments.id", ondelete="CASCADE"),
		nullable=False,
	)
	customer_id: Mapped[str] = mapped_column(String(128), nullable=False)
	amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
	currency: Mapped[str] = mapped_column(String(3), nullable=False)
	status: Mapped[str] = mapped_column(String(32), nullable=False, default=REFUND_STATUS_PENDING)
	reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
	idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
