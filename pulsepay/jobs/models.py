from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pulsepay.core.database import Base

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_DEAD = "dead"


class Job(Base):
	__tablename__ = "jobs"
	__table_args__ = (
		CheckConstraint(
			"status IN ('queued', 'running', 'completed', 'failed', 'dead')",
			name="ck_jobs_status",
		),
		Index("ix_jobs_job_type", "job_type"),
		Index("ix_jobs_status", "status"),
		Index("ix_jobs_run_at", "run_at"),
	)

	job_type: Mapped[str] = mapped_column(String(128), nullable=False)
	payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
	status: Mapped[str] = mapped_column(String(32), nullable=False, default=JOB_STATUS_QUEUED)
	attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
	max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default=text("3"))
	run_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		nullable=False,
		server_default=text("timezone('utc', now())"),
	)
	last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
