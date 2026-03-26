from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pulsepay.observability.tracing import get_request_id

from .store import rate_limit_store


class RateLimitMiddleware(BaseHTTPMiddleware):
	async def dispatch(
		self,
		request: Request,
		call_next: RequestResponseEndpoint,
	) -> Response:
		if request.url.path in {"/health", "/v1/metrics"}:
			return await call_next(request)

		api_key = request.headers.get("X-API-Key")
		if api_key is None or not api_key.strip():
			return JSONResponse(
				status_code=401,
				content={
					"error": {
						"code": "MISSING_API_KEY",
						"message": "X-API-Key header is required.",
						"request_id": self._request_id_from(request),
					}
				},
			)

		allowed, retry_after_seconds = rate_limit_store.consume(api_key=api_key)
		if not allowed:
			return JSONResponse(
				status_code=429,
				content={
					"error": {
						"code": "RATE_LIMIT_EXCEEDED",
						"message": "Rate limit exceeded. Please retry later.",
						"request_id": self._request_id_from(request),
					}
				},
				headers={"Retry-After": f"{retry_after_seconds:.3f}"},
			)

		return await call_next(request)

	@staticmethod
	def _request_id_from(request: Request) -> str:
		state_request_id = getattr(request.state, "request_id", None)
		if isinstance(state_request_id, str) and state_request_id:
			return state_request_id
		return get_request_id() or ""
