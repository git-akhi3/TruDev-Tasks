from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from pulsepay.core.database import get_db
from pulsepay.observability.tracing import get_request_id

from .schemas import InitiateRefundRequest, RefundListResponse, RefundResponse
from .service import RefundService

router = APIRouter(prefix="/payments", tags=["refunds"])


def _envelope(data: object) -> dict[str, object]:
	return {
		"data": data,
		"meta": {
			"request_id": get_request_id() or "",
			"timestamp": datetime.now(timezone.utc).isoformat(),
		},
	}


@router.post("/{payment_id}/refunds", status_code=status.HTTP_201_CREATED)
async def initiate_refund(
	payment_id: UUID,
	payload: InitiateRefundRequest,
	idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
	db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
	service = RefundService(db)
	refund = await service.initiate_refund(
		payment_id=payment_id,
		amount=payload.amount,
		idempotency_key=idempotency_key,
		reason=payload.reason,
	)
	response = RefundResponse.model_validate(refund)
	return _envelope(response.model_dump(mode="json"))


@router.get("/{payment_id}/refunds")
async def list_refunds(payment_id: UUID, db: AsyncSession = Depends(get_db)) -> dict[str, object]:
	service = RefundService(db)
	refunds = await service.list_refunds(payment_id)
	response = RefundListResponse(items=[RefundResponse.model_validate(refund) for refund in refunds])
	return _envelope(response.model_dump(mode="json"))
