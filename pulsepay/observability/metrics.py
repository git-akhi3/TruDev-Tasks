from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pulsepay.jobs.models import JOB_STATUS_DEAD, JOB_STATUS_QUEUED, JOB_STATUS_RUNNING, Job
from pulsepay.payments.models import PAYMENT_STATUS_FAILED, PAYMENT_STATUS_SUCCESS, Payment


class MetricsService:
	def __init__(self, session: AsyncSession) -> None:
		self._session = session

	async def compute_metrics(self) -> dict[str, int | float]:
		total_payments_stmt = select(func.count(Payment.id))
		successful_payments_stmt = select(func.count(Payment.id)).where(Payment.status == PAYMENT_STATUS_SUCCESS)
		failed_payments_stmt = select(func.count(Payment.id)).where(Payment.status == PAYMENT_STATUS_FAILED)
		avg_processing_time_stmt = select(
			func.coalesce(
				func.avg(func.extract("epoch", Payment.confirmed_at - Payment.created_at) * 1000.0),
				0.0,
			)
		).where(
			Payment.status == PAYMENT_STATUS_SUCCESS,
			Payment.confirmed_at.is_not(None),
		)
		active_jobs_stmt = select(func.count(Job.id)).where(Job.status.in_([JOB_STATUS_QUEUED, JOB_STATUS_RUNNING]))
		dead_jobs_stmt = select(func.count(Job.id)).where(Job.status == JOB_STATUS_DEAD)

		total_payments_result = await self._session.execute(total_payments_stmt)
		successful_payments_result = await self._session.execute(successful_payments_stmt)
		failed_payments_result = await self._session.execute(failed_payments_stmt)
		avg_processing_time_result = await self._session.execute(avg_processing_time_stmt)
		active_jobs_result = await self._session.execute(active_jobs_stmt)
		dead_jobs_result = await self._session.execute(dead_jobs_stmt)

		total_payments = int(total_payments_result.scalar_one())
		successful_payments = int(successful_payments_result.scalar_one())
		failed_payments = int(failed_payments_result.scalar_one())
		avg_processing_time_ms = float(avg_processing_time_result.scalar_one())
		active_jobs = int(active_jobs_result.scalar_one())
		dead_jobs = int(dead_jobs_result.scalar_one())

		success_rate_pct = (float(successful_payments) / float(total_payments) * 100.0) if total_payments > 0 else 0.0
		failure_rate_pct = (float(failed_payments) / float(total_payments) * 100.0) if total_payments > 0 else 0.0

		return {
			"total_payments": total_payments,
			"successful_payments": successful_payments,
			"failed_payments": failed_payments,
			"success_rate_pct": success_rate_pct,
			"failure_rate_pct": failure_rate_pct,
			"avg_processing_time_ms": avg_processing_time_ms,
			"active_jobs": active_jobs,
			"dead_jobs": dead_jobs,
		}
