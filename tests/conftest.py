from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from time import monotonic
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.schema import ColumnDefault

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WEBHOOK_SIGNING_SECRET", "test-webhook-secret")
os.environ.setdefault("ENVIRONMENT", "staging")
os.environ.setdefault("SEED_ON_STARTUP", "false")

from pulsepay.core.database import Base, get_db
from pulsepay.main import app
from pulsepay.payments.models import PAYMENT_STATUS_SUCCESS, Payment
from pulsepay.ratelimit.store import _buckets


@compiles(type(Payment.__table__.c.id.type), "sqlite")
def compile_uuid_sqlite(_type: object, _compiler: object, **_kwargs: object) -> str:
	return "CHAR(36)"


@compiles(type(Payment.__table__.c.payment_metadata.type), "sqlite")
def compile_jsonb_sqlite(_type: object, _compiler: object, **_kwargs: object) -> str:
	return "JSON"


def _adapt_metadata_for_sqlite() -> None:
	for table in Base.metadata.tables.values():
		for column in table.columns:
			server_default = column.server_default
			if server_default is not None:
				server_default_text = str(server_default.arg)
				if "gen_random_uuid()" in server_default_text or "timezone('utc', now())" in server_default_text:
					column.server_default = None

			if column.name == "id" and column.default is None:
				column.default = ColumnDefault(uuid4)
			if column.name in {"created_at", "updated_at"} and column.default is None:
				column.default = ColumnDefault(lambda: datetime.now(timezone.utc))
			if column.name == "updated_at":
				column.server_onupdate = None


@pytest.fixture(scope="session")
def anyio_backend() -> str:
	return "asyncio"


@pytest.fixture(scope="session")
def test_engine() -> object:
	_adapt_metadata_for_sqlite()
	return create_async_engine(
		"sqlite+aiosqlite:///:memory:",
		connect_args={"check_same_thread": False},
		poolclass=StaticPool,
	)


@pytest.fixture(scope="session")
def session_factory(test_engine: object) -> async_sessionmaker[AsyncSession]:
	return async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def db_session(session_factory: async_sessionmaker[AsyncSession], test_engine: object) -> AsyncSession:
	async with test_engine.begin() as conn:
		await conn.run_sync(Base.metadata.drop_all)
		await conn.run_sync(Base.metadata.create_all)

	async with session_factory() as session:
		yield session
		await session.rollback()


@pytest.fixture
async def test_client(db_session: AsyncSession) -> AsyncClient:
	_buckets.clear()

	async def override_get_db() -> AsyncSession:
		yield db_session

	app.dependency_overrides[get_db] = override_get_db
	transport = ASGITransport(app=app)
	async with AsyncClient(transport=transport, base_url="http://testserver") as client:
		yield client
	app.dependency_overrides.clear()


@pytest.fixture
async def sample_customer_id() -> str:
	return "cust_test_123"


@pytest.fixture
async def sample_payment(db_session: AsyncSession, sample_customer_id: str) -> Payment:
	created_at = datetime.now(timezone.utc)
	payment = Payment(
		customer_id=sample_customer_id,
		amount=Decimal("100.00"),
		currency="USD",
		status=PAYMENT_STATUS_SUCCESS,
		failure_reason=None,
		failure_class=None,
		retry_count=1,
		idempotency_key=f"sample-payment-{uuid4()}",
		payment_metadata={"seed": "test"},
		state_history=[
			{"state": "pending", "timestamp": created_at.isoformat(), "reason": "test_created"},
			{"state": "processing", "timestamp": created_at.isoformat(), "reason": "test_processing"},
			{"state": "success", "timestamp": created_at.isoformat(), "reason": "test_success"},
		],
		confirmed_at=created_at,
		created_at=created_at,
		updated_at=created_at,
	)
	db_session.add(payment)
	await db_session.commit()
	await db_session.refresh(payment)
	return payment


@pytest.fixture(autouse=True)
def clear_rate_limit_store() -> None:
	_buckets.clear()


@pytest.fixture(autouse=True)
def mock_external_webhook_calls(monkeypatch: pytest.MonkeyPatch) -> None:
	async def fake_post(self: httpx.AsyncClient, url: str, *args: object, **kwargs: object) -> object:
		class _Response:
			is_success = True

		return _Response()

	monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


@pytest.fixture
def exhausted_rate_limit_bucket() -> tuple[str, float]:
	api_key = "rate-limited-key"
	retry_after_seconds = 5.0
	from pulsepay.ratelimit.store import TokenBucket

	_buckets[api_key] = TokenBucket(
		tokens=0.0,
		last_refill=monotonic(),
		capacity=1.0,
		refill_rate=1.0 / retry_after_seconds,
	)
	return api_key, retry_after_seconds
