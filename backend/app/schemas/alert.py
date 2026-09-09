"""API request/response schemas for Alert Rules and alert evaluation.

See app/domain/alert_engine.py for the semantics this mirrors.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.portfolio import DecimalStr


class AlertRuleCreateRequest(BaseModel):
    enabled: bool = True
    allocation_alert_enabled: bool = False
    allocation_max_percent: DecimalStr | None = None
    price_target_enabled: bool = False
    price_target: DecimalStr | None = None
    dip_buy_enabled: bool = False
    dip_buy_price: DecimalStr | None = None
    telegram_enabled: bool = False


class AlertRuleUpdateRequest(BaseModel):
    enabled: bool | None = None
    allocation_alert_enabled: bool | None = None
    allocation_max_percent: DecimalStr | None = None
    price_target_enabled: bool | None = None
    price_target: DecimalStr | None = None
    dip_buy_enabled: bool | None = None
    dip_buy_price: DecimalStr | None = None
    telegram_enabled: bool | None = None


class AlertRuleOut(BaseModel):
    id: UUID
    watchlist_id: UUID
    enabled: bool
    allocation_alert_enabled: bool
    allocation_max_percent: DecimalStr | None
    price_target_enabled: bool
    price_target: DecimalStr | None
    dip_buy_enabled: bool
    dip_buy_price: DecimalStr | None
    telegram_enabled: bool
    last_triggered_at: datetime | None


class AlertEvaluationEntryOut(BaseModel):
    alert_rule_id: UUID
    watchlist_id: UUID
    asset_symbol: str
    alert_type: str
    condition_met: bool
    is_new_trigger: bool
    should_clear: bool
    reason: str
    current_value: DecimalStr | None
    threshold_value: DecimalStr | None


class AlertEvaluationOut(BaseModel):
    results: list[AlertEvaluationEntryOut]
