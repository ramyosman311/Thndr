from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db_session
from app.models import User
from app.schemas.alert import AlertEvaluationOut, AlertRuleOut, AlertRuleUpdateRequest
from app.services import alert_service
from app.services.alert_service import AlertRuleNotFoundError, InvalidAlertRuleConfigurationError

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.patch("/{alert_rule_id}", response_model=AlertRuleOut)
async def update_alert_rule(
    alert_rule_id: UUID,
    request: AlertRuleUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> AlertRuleOut:
    updates = request.model_dump(exclude_unset=True)
    try:
        return await alert_service.update_alert_rule(session, user.id, alert_rule_id, updates)
    except AlertRuleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidAlertRuleConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{alert_rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(
    alert_rule_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> None:
    try:
        await alert_service.delete_alert_rule(session, user.id, alert_rule_id)
    except AlertRuleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/evaluate", response_model=AlertEvaluationOut)
async def evaluate_alerts(
    session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)
) -> AlertEvaluationOut:
    """Evaluates every enabled alert rule against current portfolio/asset
    data. Read-only with respect to holdings, transactions, snapshots,
    allocation_targets, and portfolio_configs — the only write is to
    `alert_rules.last_triggered_at` (dedup state). Never creates or
    executes a trade."""
    return await alert_service.evaluate_alerts(session, user.id)
