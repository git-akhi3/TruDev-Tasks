from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from pulsepay.core.database import Base


class LedgerEntry(Base):
	__tablename__ = "ledger_entries"
	__table_args__ = (
		Index("ix_ledger_entries_payment_id", "payment_id"),
		Index("ix_ledger_entries_entry_type", "entry_type"),
	)

	payment_id: Mapped[UUID] = mapped_column(
		PGUUID(as_uuid=True),
		ForeignKey("payments.id", ondelete="CASCADE"),
		nullable=False,
	)
	entry_type: Mapped[str] = mapped_column(String(64), nullable=False)
	amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
	currency: Mapped[str] = mapped_column(String(3), nullable=False)
	entry_metadata: Mapped[dict[str, object] | None] = mapped_column("metadata", JSONB, nullable=True)
