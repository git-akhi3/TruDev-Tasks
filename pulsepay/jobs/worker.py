from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Select, select

from pulsepay.observability.logging import get_logger

from .handlers import get_handler
from .models import (
	JOB_STATUS_COMPLETED,
	JOB_STATUS_DEAD,
	JOB_STATUS_FAILED,
	JOB_STATUS_QUEUED,
	JOB_STATUS_RUNNING,
	Job,
)
from .queue import StormQueue


class JobWorker:
	def __init__(self, queue: StormQueue) -> None:
		self._queue = queue
		self._logger = get_logger(__name__)
		self._stop_event = asyncio.Event()
		self._consumer_task: asyncio.Task[None] | None = None
		self._delayed_poll_task: asyncio.Task[None] | None = None

	async def start(self) -> None:
		if self._consumer_task is not None and not self._consumer_task.done():
			return

		self._stop_event.clear()
		self._consumer_task = asyncio.create_task(self._consume_loop())
		self._delayed_poll_task = asyncio.create_task(self._poll_delayed_jobs_loop())

	async def stop(self) -> None:
		self._stop_event.set()
		tasks = [task for task in [self._consumer_task, self._delayed_poll_task] if task is not None]
		for task in tasks:
			task.cancel()
		if tasks:
			await asyncio.gather(*tasks, return_exceptions=True)

		self._consumer_task = None
		self._delayed_poll_task = None

	async def _consume_loop(self) -> None:
		while not self._stop_event.is_set():
			try:
				job_id = await asyncio.wait_for(self._queue.dispatch_queue.get(), timeout=1.0)
			except TimeoutError:
				continue

			try:
				await self._process(job_id)
			finally:
				self._queue.dispatch_queue.task_done()

	async def _poll_delayed_jobs_loop(self) -> None:
		while not self._stop_event.is_set():
			try:
				await self._enqueue_due_jobs()
			except Exception as exc:
				self._logger.warning(
					"job_polling_error",
					extra={
						"error": str(exc),
					},
				)
			await asyncio.sleep(5)

	async def _enqueue_due_jobs(self) -> None:
		now = datetime.now(timezone.utc)
		async with self._queue.session_factory() as session:
			stmt: Select[tuple[UUID]] = select(Job.id).where(
				Job.status == JOB_STATUS_QUEUED,
				Job.run_at <= now,
			)
			result = await session.execute(stmt)
			due_job_ids = list(result.scalars().all())

		for due_job_id in due_job_ids:
			await self._queue.dispatch_queue.put(due_job_id)

	async def _process(self, job_id: UUID) -> None:
		async with self._queue.session_factory() as session:
			job = await session.get(Job, job_id)
			if job is None:
				return

			if job.status in {JOB_STATUS_COMPLETED, JOB_STATUS_DEAD}:
				return

			job.status = JOB_STATUS_RUNNING
			await session.commit()

			try:
				handler = get_handler(job.job_type)
				if handler is None:
					raise RuntimeError(f"No handler registered for job_type '{job.job_type}'.")

				await handler(job.payload)
				job.status = JOB_STATUS_COMPLETED
				job.last_error = None
				await session.commit()
			except Exception as exc:
				job.attempt_count += 1
				job.last_error = str(exc)
				job.status = JOB_STATUS_FAILED
				self._logger.warning(
					"job_processing_failed",
					extra={
						"job_id": str(job.id),
						"job_type": job.job_type,
						"attempt": job.attempt_count,
						"max_attempts": job.max_attempts,
						"error": str(exc),
					},
				)

				if job.attempt_count < job.max_attempts:
					job.status = JOB_STATUS_QUEUED
					job.run_at = datetime.now(timezone.utc)
					await session.commit()
					await self._queue.dispatch_queue.put(job.id)
					return

				job.status = JOB_STATUS_DEAD
				await session.commit()
				self._logger.error(
					"job_marked_dead",
					extra={
						"job_id": str(job.id),
						"job_type": job.job_type,
						"attempt": job.attempt_count,
						"max_attempts": job.max_attempts,
						"error": str(exc),
					},
				)
