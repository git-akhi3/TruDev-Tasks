from __future__ import annotations

import os
import sys
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))


def _resolve(module_name: str, fallback: str):
    try:
        return import_module(module_name)
    except ModuleNotFoundError:
        return import_module(fallback)


main_mod = _resolve("pulsepay.main", "main")
db_mod = _resolve("pulsepay.core.database", "core.database")
config_mod = _resolve("pulsepay.core.config", "core.config")
queue_mod = _resolve("pulsepay.jobs.queue", "jobs.queue")
payment_service_mod = _resolve("pulsepay.payments.service", "payments.service")
payment_models_mod = _resolve("pulsepay.payments.models", "payments.models")
payment_schemas_mod = _resolve("pulsepay.payments.schemas", "payments.schemas")

app = main_mod.app
get_db = db_mod.get_db
engine = db_mod.engine
SessionLocal = db_mod.SessionLocal
settings = config_mod.settings
set_storm_queue = queue_mod.set_storm_queue
StormQueue = queue_mod.StormQueue
PaymentService = payment_service_mod.PaymentService
Payment = payment_models_mod.Payment
CreatePaymentRequest = payment_schemas_mod.CreatePaymentRequest


@pytest.fixture(scope="session", autouse=True)
def _enforce_postgres_and_queue() -> None:
    db_url = os.getenv("DATABASE_URL") or settings().DATABASE_URL
    assert db_url.startswith("postgresql+asyncpg://"), "Grader tests must run against PostgreSQL."
    set_storm_queue(StormQueue(SessionLocal))


@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    connection = await engine.connect()
    transaction = await connection.begin()

    session_factory = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    session = session_factory()
    await session.begin_nested()

    @event.listens_for(session.sync_session, "after_transaction_end")
    def _restart_savepoint(sync_session, nested_transaction):
        parent = getattr(nested_transaction, "_parent", None)
        if nested_transaction.nested and (parent is None or not parent.nested):
            sync_session.begin_nested()

    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture(scope="function")
async def app_client(db_session: AsyncSession) -> AsyncGenerator[httpx.AsyncClient, None]:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def make_api_key() -> str:
    return f"grader-{uuid.uuid4()}"


@pytest.fixture(scope="function")
def patch_processor(monkeypatch):
    """Patch processor outcome to success, soft_fail, or hard_fail for deterministic tests."""
    outcomes = {
        "success": 0.10,
        "soft_fail": 0.90,
        "hard_fail": 0.99,
    }

    def _apply(outcome: str = "success"):
        if outcome not in outcomes:
            raise ValueError(f"Unsupported outcome '{outcome}'.")
        monkeypatch.setattr(payment_service_mod.random, "random", lambda: outcomes[outcome])

    _apply("success")
    return _apply


@pytest.fixture(scope="function")
def make_payment(db_session: AsyncSession):
    async def _make_payment(
        *,
        status: str = "pending",
        amount: Decimal = Decimal("100.00"),
        currency: str = "USD",
        customer_id: str = "grader_customer",
    ) -> Payment:
        service = PaymentService(db_session)
        idempotency_key = f"grader-idem-{uuid.uuid4()}"
        response, _ = await service.create_payment(
            CreatePaymentRequest(
                customer_id=customer_id,
                amount=amount,
                currency=currency,
                metadata={"source": "grader"},
            ),
            idempotency_key=idempotency_key,
        )

        payment = await db_session.get(Payment, response.id)
        if payment is None:
            raise RuntimeError("Payment creation fixture failed.")

        if payment.status != status:
            payment.status = status
            if status == "success":
                payment.confirmed_at = datetime.now(timezone.utc)
                payment.failure_reason = None
                payment.failure_class = None
            elif status == "failed" and not payment.failure_reason:
                payment.failure_reason = "grader_forced_failure"
            await db_session.commit()
            await db_session.refresh(payment)

        return payment

    return _make_payment
