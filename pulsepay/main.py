from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import cast

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from pulsepay.core.config import settings
from pulsepay.core.database import SessionLocal, get_db
from pulsepay.core.exceptions import register_exception_handlers
from pulsepay.core.middleware import LoggingMiddleware, RequestTracingMiddleware
from pulsepay.jobs.queue import StormQueue, set_storm_queue
from pulsepay.jobs.worker import JobWorker
from pulsepay.observability.logging import get_logger
from pulsepay.observability.metrics import MetricsService
from pulsepay.payments.router import router as payments_router
from pulsepay.ratelimit.middleware import RateLimitMiddleware
from pulsepay.refunds.router import router as refunds_router
from pulsepay.webhooks.router import router as webhooks_router

logger = get_logger(__name__)


def _run_migrations() -> None:
	config = Config(str(Path(__file__).resolve().with_name("alembic.ini")))
	command.upgrade(config, "head")


async def _seed_on_startup() -> None:
	try:
		module: ModuleType = import_module("pulsepay.seed")
	except ModuleNotFoundError:
		logger.info("seed_module_not_found")
		return

	seed_fn = getattr(module, "seed_data", None)
	if seed_fn is None:
		logger.info("seed_function_not_found")
		return

	async_seed = cast(Callable[[object], Awaitable[None]], seed_fn)
	await async_seed(SessionLocal)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
	if settings().ENVIRONMENT == "development":
		_run_migrations()

	storm_queue = StormQueue(SessionLocal)
	set_storm_queue(storm_queue)
	worker = JobWorker(storm_queue)
	app.state.storm_queue = storm_queue
	app.state.job_worker = worker

	if settings().SEED_ON_STARTUP:
		await _seed_on_startup()

	await worker.start()
	try:
		yield
	finally:
		await worker.stop()


app = FastAPI(
	title="PulsePay",
	version="1.0.0",
	docs_url="/docs" if settings().ENVIRONMENT == "development" else None,
	lifespan=lifespan,
)

register_exception_handlers(app)

app.add_middleware(RequestTracingMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

app.include_router(payments_router, prefix="/v1")
app.include_router(refunds_router, prefix="/v1")
app.include_router(webhooks_router, prefix="/v1")


@app.get("/health")
async def health() -> dict[str, str]:
	return {"status": "ok", "environment": settings().ENVIRONMENT}


@app.get("/v1/metrics")
async def metrics(db: AsyncSession = Depends(get_db)) -> dict[str, int | float]:
	service = MetricsService(db)
	return await service.compute_metrics()
