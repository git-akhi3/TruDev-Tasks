from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pulsepay.core.database import Base

WEBHOOK_STATUS_QUEUED = "queued"
WEBHOOK_STATUS_DELIVERED = "delivered"
WEBHOOK_STATUS_FAILED = "failed"
WEBHOOK_STATUS_DEAD = "dead"


class WebhookEndpoint(Base):
	__tablename__ = "webhook_endpoints"
	__table_args__ = (Index("ix_webhook_endpoints_client_id", "client_id"),)

	client_id: Mapped[str] = mapped_column(String(128), nullable=False)
	url: Mapped[str] = mapped_column(String(2048), nullable=False)
	signing_secret: Mapped[str] = mapped_column(String(255), nullable=False)
	is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

	events: Mapped[list[WebhookEvent]] = relationship(
		"WebhookEvent",
		back_populates="endpoint",
		cascade="all, delete-orphan",
	)


class WebhookEvent(Base):
	__tablename__ = "webhook_events"
	__table_args__ = (
		CheckConstraint(
			"status IN ('queued', 'delivered', 'failed', 'dead')",
			name="ck_webhook_events_status",
		),
		Index("ix_webhook_events_status", "status"),
		Index("ix_webhook_events_endpoint_id", "endpoint_id"),
	)

	endpoint_id: Mapped[UUID] = mapped_column(
		PGUUID(as_uuid=True),
		ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
		nullable=False,
	)
	event_type: Mapped[str] = mapped_column(String(128), nullable=False)
	payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
	status: Mapped[str] = mapped_column(String(32), nullable=False, default=WEBHOOK_STATUS_QUEUED)
	attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
	last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
	next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

	endpoint: Mapped[WebhookEndpoint] = relationship("WebhookEndpoint", back_populates="events")
