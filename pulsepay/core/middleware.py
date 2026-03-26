from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from pulsepay.observability.logging import get_logger
from pulsepay.observability.tracing import (
	get_request_id,
	new_request_context,
	set_request_id,
)


class RequestTracingMiddleware(BaseHTTPMiddleware):
	async def dispatch(
		self,
		request: Request,
		call_next: RequestResponseEndpoint,
	) -> Response:
		with new_request_context() as request_id:
			set_request_id(request_id)
			request.state.request_id = request_id
			response = await call_next(request)
			response.headers["X-Request-ID"] = request_id
			return response


class LoggingMiddleware(BaseHTTPMiddleware):
	def __init__(self, app: ASGIApp) -> None:
		super().__init__(app)
		self._logger = get_logger(__name__)

	async def dispatch(
		self,
		request: Request,
		call_next: RequestResponseEndpoint,
	) -> Response:
		start = perf_counter()
		try:
			response = await call_next(request)
		except Exception:
			duration_ms = (perf_counter() - start) * 1000
			self._logger.info(
				"request_completed",
				extra={
					"method": request.method,
					"path": request.url.path,
					"status_code": 500,
					"duration_ms": round(duration_ms, 2),
					"request_id": get_request_id(),
				},
			)
			raise

		duration_ms = (perf_counter() - start) * 1000
		self._logger.info(
			"request_completed",
			extra={
				"method": request.method,
				"path": request.url.path,
				"status_code": response.status_code,
				"duration_ms": round(duration_ms, 2),
				"request_id": get_request_id(),
			},
		)
		return response
