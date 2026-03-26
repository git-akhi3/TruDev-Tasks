"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-26 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.create_table(
		"payments",
		sa.Column("customer_id", sa.String(length=128), nullable=False),
		sa.Column("amount", sa.Numeric(12, 2), nullable=False),
		sa.Column("currency", sa.String(length=3), nullable=False),
		sa.Column("status", sa.String(length=32), nullable=False),
		sa.Column("failure_reason", sa.String(length=512), nullable=True),
		sa.Column("failure_class", sa.String(length=16), nullable=True),
		sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
		sa.Column("idempotency_key", sa.String(length=255), nullable=False),
		sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
		sa.Column("state_history", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
		sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.CheckConstraint("status IN ('pending', 'processing', 'success', 'failed')", name="ck_payments_status"),
		sa.CheckConstraint("failure_class IS NULL OR failure_class IN ('soft', 'hard')", name="ck_payments_failure_class"),
		sa.PrimaryKeyConstraint("id"),
		sa.UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
		sa.UniqueConstraint("customer_id", "idempotency_key", name="uq_payments_customer_idempotency_key"),
	)
	op.create_index("ix_payments_customer_id", "payments", ["customer_id"], unique=False)
	op.create_index("ix_payments_status", "payments", ["status"], unique=False)

	op.create_table(
		"idempotency_records",
		sa.Column("key", sa.String(length=255), nullable=False),
		sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
		sa.Column("status_code", sa.Integer(), nullable=False),
		sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.PrimaryKeyConstraint("id"),
		sa.UniqueConstraint("key", name="uq_idempotency_records_key"),
	)
	op.create_index("ix_idempotency_records_key", "idempotency_records", ["key"], unique=False)

	op.create_table(
		"ledger_entries",
		sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
		sa.Column("entry_type", sa.String(length=64), nullable=False),
		sa.Column("amount", sa.Numeric(12, 2), nullable=False),
		sa.Column("currency", sa.String(length=3), nullable=False),
		sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
		sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
		sa.PrimaryKeyConstraint("id"),
	)
	op.create_index("ix_ledger_entries_entry_type", "ledger_entries", ["entry_type"], unique=False)
	op.create_index("ix_ledger_entries_payment_id", "ledger_entries", ["payment_id"], unique=False)

	op.create_table(
		"refunds",
		sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
		sa.Column("customer_id", sa.String(length=128), nullable=False),
		sa.Column("amount", sa.Numeric(12, 2), nullable=False),
		sa.Column("currency", sa.String(length=3), nullable=False),
		sa.Column("status", sa.String(length=32), nullable=False),
		sa.Column("reason", sa.String(length=512), nullable=True),
		sa.Column("idempotency_key", sa.String(length=255), nullable=False),
		sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')", name="ck_refunds_status"),
		sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
		sa.PrimaryKeyConstraint("id"),
		sa.UniqueConstraint("idempotency_key", name="uq_refunds_idempotency_key"),
	)
	op.create_index("ix_refunds_customer_id", "refunds", ["customer_id"], unique=False)
	op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"], unique=False)

	op.create_table(
		"webhook_endpoints",
		sa.Column("client_id", sa.String(length=128), nullable=False),
		sa.Column("url", sa.String(length=2048), nullable=False),
		sa.Column("signing_secret", sa.String(length=255), nullable=False),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.PrimaryKeyConstraint("id"),
	)
	op.create_index("ix_webhook_endpoints_client_id", "webhook_endpoints", ["client_id"], unique=False)

	op.create_table(
		"jobs",
		sa.Column("job_type", sa.String(length=128), nullable=False),
		sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
		sa.Column("status", sa.String(length=32), nullable=False),
		sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
		sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
		sa.Column("run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.Column("last_error", sa.String(length=1024), nullable=True),
		sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'dead')", name="ck_jobs_status"),
		sa.PrimaryKeyConstraint("id"),
	)
	op.create_index("ix_jobs_job_type", "jobs", ["job_type"], unique=False)
	op.create_index("ix_jobs_run_at", "jobs", ["run_at"], unique=False)
	op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)

	op.create_table(
		"webhook_events",
		sa.Column("endpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
		sa.Column("event_type", sa.String(length=128), nullable=False),
		sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
		sa.Column("status", sa.String(length=32), nullable=False),
		sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
		sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
		sa.CheckConstraint("status IN ('queued', 'delivered', 'failed', 'dead')", name="ck_webhook_events_status"),
		sa.ForeignKeyConstraint(["endpoint_id"], ["webhook_endpoints.id"], ondelete="CASCADE"),
		sa.PrimaryKeyConstraint("id"),
	)
	op.create_index("ix_webhook_events_endpoint_id", "webhook_events", ["endpoint_id"], unique=False)
	op.create_index("ix_webhook_events_status", "webhook_events", ["status"], unique=False)


def downgrade() -> None:
	op.drop_index("ix_webhook_events_status", table_name="webhook_events")
	op.drop_index("ix_webhook_events_endpoint_id", table_name="webhook_events")
	op.drop_table("webhook_events")

	op.drop_index("ix_jobs_status", table_name="jobs")
	op.drop_index("ix_jobs_run_at", table_name="jobs")
	op.drop_index("ix_jobs_job_type", table_name="jobs")
	op.drop_table("jobs")

	op.drop_index("ix_webhook_endpoints_client_id", table_name="webhook_endpoints")
	op.drop_table("webhook_endpoints")

	op.drop_index("ix_refunds_payment_id", table_name="refunds")
	op.drop_index("ix_refunds_customer_id", table_name="refunds")
	op.drop_table("refunds")

	op.drop_index("ix_ledger_entries_payment_id", table_name="ledger_entries")
	op.drop_index("ix_ledger_entries_entry_type", table_name="ledger_entries")
	op.drop_table("ledger_entries")

	op.drop_index("ix_idempotency_records_key", table_name="idempotency_records")
	op.drop_table("idempotency_records")

	op.drop_index("ix_payments_status", table_name="payments")
	op.drop_index("ix_payments_customer_id", table_name="payments")
	op.drop_table("payments")
