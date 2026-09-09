from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.transaction import TransactionCreateRequest, TransactionOut, TransactionResultOut
from app.services import transaction_service
from app.services.transaction_service import AssetNotFoundError, OversellError

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("", response_model=TransactionResultOut, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    request: TransactionCreateRequest, session: AsyncSession = Depends(get_db_session)
) -> TransactionResultOut:
    """Records an executed BUY/SELL transaction and atomically updates the
    resulting holding (average-cost accounting — see FINANCIAL_RULES.md,
    "Transaction Accounting"). Both writes succeed or fail together.

    This is NOT a recommendation: it records a real, immutable historical
    event and changes the current holding, unlike
    `POST /api/cash-flow/allocate` (Smart Inflow, recommendation-only)."""
    try:
        return await transaction_service.create_transaction(
            session,
            asset_id=request.asset_id,
            transaction_type=request.transaction_type,
            quantity=request.quantity,
            price=request.price,
            fees=request.fees,
            transaction_date=request.transaction_date,
            notes=request.notes,
        )
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OversellError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=list[TransactionOut])
async def list_transactions(session: AsyncSession = Depends(get_db_session)) -> list[TransactionOut]:
    """Read-only transaction history, most recent first."""
    return await transaction_service.list_transactions(session)
