from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

PAYMENT_NOT_FOUND = "PAYMENT_NOT_FOUND"
PAYMENT_ALREADY_PROCESSED = "PAYMENT_ALREADY_PROCESSED"
INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
INSUFFICIENT_REFUNDABLE_AMOUNT = "INSUFFICIENT_REFUNDABLE_AMOUNT"
REFUND_EXCEEDS_ORIGINAL = "REFUND_EXCEEDS_ORIGINAL"
WEBHOOK_DELIVERY_FAILED = "WEBHOOK_DELIVERY_FAILED"
RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
JOB_QUEUE_FULL = "JOB_QUEUE_FULL"


class PulsePayException(Exception):
	error_code: str = "PULSEPAY_ERROR"
	status_code: int = HTTPStatus.BAD_REQUEST

	def __init__(self, detail: str) -> None:
		super().__init__(detail)
		self.detail = detail


class PaymentNotFound(PulsePayException):
	error_code = PAYMENT_NOT_FOUND
	status_code = HTTPStatus.NOT_FOUND


class PaymentAlreadyProcessed(PulsePayException):
	error_code = PAYMENT_ALREADY_PROCESSED
	status_code = HTTPStatus.CONFLICT


class InvalidStateTransition(PulsePayException):
	error_code = INVALID_STATE_TRANSITION
	status_code = HTTPStatus.CONFLICT


class IdempotencyConflict(PulsePayException):
	error_code = IDEMPOTENCY_CONFLICT
	status_code = HTTPStatus.CONFLICT


class InsufficientRefundableAmount(PulsePayException):
	error_code = INSUFFICIENT_REFUNDABLE_AMOUNT
	status_code = HTTPStatus.CONFLICT


class RefundExceedsOriginal(PulsePayException):
	error_code = REFUND_EXCEEDS_ORIGINAL
	status_code = HTTPStatus.BAD_REQUEST


class WebhookDeliveryFailed(PulsePayException):
	error_code = WEBHOOK_DELIVERY_FAILED
	status_code = HTTPStatus.BAD_GATEWAY


class RateLimitExceeded(PulsePayException):
	error_code = RATE_LIMIT_EXCEEDED
	status_code = HTTPStatus.TOO_MANY_REQUESTS


class JobQueueFull(PulsePayException):
	error_code = JOB_QUEUE_FULL
	status_code = HTTPStatus.SERVICE_UNAVAILABLE


def _request_id_from(request: Request) -> str:
	state_request_id = getattr(request.state, "request_id", None)
	if isinstance(state_request_id, str) and state_request_id:
		return state_request_id

	header_request_id = request.headers.get("x-request-id")
	if isinstance(header_request_id, str) and header_request_id:
		return header_request_id

	return ""


def register_exception_handlers(app: FastAPI) -> None:
	@app.exception_handler(PulsePayException)
	async def pulsepay_exception_handler(
		request: Request,
		exc: PulsePayException,
	) -> JSONResponse:
		return JSONResponse(
			status_code=int(exc.status_code),
			content={
				"error": {
					"code": exc.error_code,
					"message": exc.detail,
					"request_id": _request_id_from(request),
				}
			},
		)
