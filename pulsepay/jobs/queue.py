from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pulsepay.observability.logging import get_logger

from .models import JOB_STATUS_DEAD, JOB_STATUS_QUEUED, Job

logger = get_logger(__name__)


class StormQueue:
	def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
		self._session_factory = session_factory
		self._dispatch_queue: asyncio.Queue[UUID] = asyncio.Queue()

	@property
	def dispatch_queue(self) -> asyncio.Queue[UUID]:
		return self._dispatch_queue

	@property
	def session_factory(self) -> async_sessionmaker[AsyncSession]:
		return self._session_factory

	async def enqueue(
		self,
		job_type: str,
		payload: dict[str, object],
		run_at: datetime | None = None,
		max_attempts: int = 3,
	) -> Job:
		effective_run_at = run_at if run_at is not None else datetime.now(timezone.utc)
		async with self._session_factory() as session:
			job = Job(
				job_type=job_type,
				payload=payload,
				status=JOB_STATUS_QUEUED,
				attempt_count=0,
				max_attempts=max_attempts,
				run_at=effective_run_at,
			)
			session.add(job)
			await session.commit()
			await session.refresh(job)

		if effective_run_at <= datetime.now(timezone.utc):
			await self._dispatch_queue.put(job.id)

		logger.info(
			"job_enqueued",
			extra={
				"job_type": job_type,
				"job_id": str(job.id),
				"run_at": effective_run_at.isoformat(),
			},
		)
		return job

	async def get_dead_jobs(self, page: int, limit: int) -> tuple[list[Job], int]:
		effective_limit = min(max(limit, 1), 100)
		offset = (max(page, 1) - 1) * effective_limit

		async with self._session_factory() as session:
			jobs_stmt: Select[tuple[Job]] = (
				select(Job)
				.where(Job.status == JOB_STATUS_DEAD)
				.order_by(Job.updated_at.desc())
				.offset(offset)
				.limit(effective_limit)
			)
			count_stmt = select(func.count(Job.id)).where(Job.status == JOB_STATUS_DEAD)

			jobs_result = await session.execute(jobs_stmt)
			count_result = await session.execute(count_stmt)

			jobs = list(jobs_result.scalars().all())
			total = int(count_result.scalar_one())
			return jobs, total

	async def retry_dead_job(self, job_id: UUID) -> Job:
		async with self._session_factory() as session:
			job = await session.get(Job, job_id)
			if job is None:
				raise ValueError(f"Job {job_id} was not found.")

			job.status = JOB_STATUS_QUEUED
			job.last_error = None
			job.attempt_count = 0
			job.run_at = datetime.now(timezone.utc)
			await session.commit()
			await session.refresh(job)

		await self._dispatch_queue.put(job.id)
		return job


_storm_queue: StormQueue | None = None


def set_storm_queue(storm_queue: StormQueue) -> None:
	global _storm_queue
	_storm_queue = storm_queue


def get_storm_queue() -> StormQueue:
	if _storm_queue is None:
		raise RuntimeError("StormQueue is not initialized.")
	return _storm_queue


async def enqueue_job(
	job_type: str,
	payload: dict[str, object],
	run_at: datetime | None = None,
	max_attempts: int = 3,
) -> Job:
	return await get_storm_queue().enqueue(
		job_type=job_type,
		payload=payload,
		run_at=run_at,
		max_attempts=max_attempts,
	)
