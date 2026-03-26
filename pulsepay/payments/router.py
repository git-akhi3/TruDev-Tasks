from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from pulsepay.core.database import get_db
from pulsepay.observability.tracing import get_request_id

from .models import (
	PAYMENT_STATUS_FAILED,
	PAYMENT_STATUS_PENDING,
	PAYMENT_STATUS_PROCESSING,
	PAYMENT_STATUS_SUCCESS,
)
from .schemas import (
	ConfirmPaymentRequest,
	CreatePaymentRequest,
	PaginatedPaymentsResponse,
	PaymentResponse,
)
from .service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


def _envelope(data: object) -> dict[str, object]:
	return {
		"data": data,
		"meta": {
			"request_id": get_request_id() or "",
			"timestamp": datetime.now(timezone.utc).isoformat(),
		},
	}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_payment(
	payload: CreatePaymentRequest,
	response: Response,
	idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
	db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
	service = PaymentService(db)
	payment_response, status_code = await service.create_payment(payload, idempotency_key=idempotency_key)
	response.status_code = status_code
	return _envelope(payment_response.model_dump(mode="json"))


@router.post("/{payment_id}/confirm")
async def confirm_payment(
	payment_id: UUID,
	payload: ConfirmPaymentRequest,
	db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
	service = PaymentService(db)
	payment = await service.confirm_payment(payment_id, metadata=payload.metadata)
	payment_response = PaymentResponse.model_validate(payment)
	return _envelope(payment_response.model_dump(mode="json"))


@router.get("/{payment_id}")
async def get_payment(payment_id: UUID, db: AsyncSession = Depends(get_db)) -> dict[str, object]:
	service = PaymentService(db)
	payment = await service.get_payment(payment_id)
	payment_response = PaymentResponse.model_validate(payment)
	return _envelope(payment_response.model_dump(mode="json"))


@router.get("/")
async def list_payments(
	page: int = Query(default=1, ge=1),
	limit: int = Query(default=20, ge=1, le=100),
	customer_id: str | None = Query(default=None),
	status_filter: str | None = Query(
		default=None,
		alias="status",
		pattern=f"^({PAYMENT_STATUS_PENDING}|{PAYMENT_STATUS_PROCESSING}|{PAYMENT_STATUS_SUCCESS}|{PAYMENT_STATUS_FAILED})$",
	),
	db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
	service = PaymentService(db)
	payments, total = await service.list_payments(
		page=page,
		limit=limit,
		customer_id=customer_id,
		status=status_filter,
	)
	paginated = PaginatedPaymentsResponse(
		items=[PaymentResponse.model_validate(payment) for payment in payments],
		page=page,
		limit=limit,
		total=total,
	)
	return _envelope(paginated.model_dump(mode="json"))
