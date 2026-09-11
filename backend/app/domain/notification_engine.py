"""Pure Notification classification/composition layer (Phase 19).

No I/O, no database session — this module never persists anything and
never decides *whether* to notify on its own; it only turns an
already-computed `domain.alert_engine.AlertCheckResult` or an
already-computed Phase 18 recommendation into presentation content (a
`NotificationCategory`, `NotificationSeverity`, Arabic `title`/`message`,
a deterministic `source_id`, and an optional contextual
`NotificationAction`). Every underlying number/condition — allocation
percent, price, threshold, BUY/REDUCE amount, target/maximum status — is
read verbatim from the caller-supplied result; nothing here recomputes a
financial value (see FINANCIAL_RULES.md, "Alert Engine Rules" and
"Smart Recommendations Engine Rules").

Two independent sources feed this module, deliberately without either
one recalculating the other's work:

- `domain.alert_engine.AlertCheckResult` (Phase 8) — ALLOCATION_BREACH/
  REBALANCE_SUGGESTED map to `NotificationCategory.ALLOCATION_ALERT`;
  PRICE_TARGET/DIP_BUY map to `NotificationCategory.PRICE_ALERT`. These
  checks have no existing Arabic text (their own `reason` is English
  prose, matching the same established precedent as
  `rebalancing_engine.py`'s `reason` field) — the `title`/`message`
  composed here are new, additive Arabic copy built strictly from the
  check's own `current_value`/`threshold_value`/`reason` inputs.
- A Phase 18 `PortfolioRecommendationOut`-shaped recommendation (or the
  raw domain `PortfolioRecommendation` — both expose the same field
  names, so either can be passed in, matching the interchangeable-input
  idiom `alert_engine.check_rebalance_suggestion` already established)
  maps to `NotificationCategory.RECOMMENDATION_ALERT`. Its `title`/
  `message` are reused VERBATIM from the recommendation — never
  reworded — since Phase 18 already composed natural Arabic copy for
  exactly this content; recomposing it here would be a duplicate
  vocabulary, not a second opinion.

`NotificationCategory.PORTFOLIO_HEALTH_ALERT` is reserved but never
produced by this module — see DECISIONS.md, "Phase 19 — Alerts &
Notifications" for why no existing signal distinctly warrants a fourth,
separate category without fabricating one.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.domain.alert_engine import AlertCheckResult, AlertType
from app.models.enums import NotificationAction, NotificationCategory, NotificationSeverity

# Only these Phase 18 recommendation types are notification-worthy —
# CASH_DEPLOYMENT/REBALANCING_OPPORTUNITY (INFO) and PORTFOLIO_HEALTHY
# (SUCCESS) are already visible on the Dashboard's Recommendations card
# and are not urgent enough to also occupy the Notification Center (see
# "without creating noise", Phase 19 objective). Only genuinely
# attention-worthy severities surface here.
_NOTIFY_WORTHY_RECOMMENDATION_TYPES = frozenset({"BREACH_RESOLUTION", "RESTRICTED_ACTION"})

_ALLOCATION_ALERT_TYPES = frozenset({AlertType.ALLOCATION_BREACH, AlertType.REBALANCE_SUGGESTED})
_PRICE_ALERT_TYPES = frozenset({AlertType.PRICE_TARGET, AlertType.DIP_BUY})


@dataclass(frozen=True)
class NotificationContent:
    source_id: str
    category: NotificationCategory
    severity: NotificationSeverity
    title: str
    message: str
    target_category: str | None
    target_asset: str | None
    action: NotificationAction | None


def build_alert_notification_content(
    check: AlertCheckResult, *, alert_rule_id: str, asset_symbol: str, bucket_name: str | None = None
) -> NotificationContent | None:
    """Builds the notification content for one newly-triggered
    `AlertCheckResult`. Returns `None` for `INCOME_MATURITY` (not yet
    wired to a persisted alert rule — see alert_engine.py's own
    docstring) since there is nothing configured to notify from.

    `source_id` is `f"ALERT:{alert_rule_id}:{alert_type}"` — stable per
    (rule, check type) pair, deliberately excluding any timestamp so the
    caller's own active/resolved lookup (see notification_service.py)
    is the sole source of "is this already notified" truth."""
    source_id = f"ALERT:{alert_rule_id}:{check.alert_type.value}"

    if check.alert_type in _ALLOCATION_ALERT_TYPES:
        category = NotificationCategory.ALLOCATION_ALERT
        action = NotificationAction.REVIEW_DISTRIBUTION
        if check.alert_type == AlertType.ALLOCATION_BREACH:
            severity = NotificationSeverity.WARNING
            title = f"{bucket_name or asset_symbol}: تجاوز نسبة التنبيه المحددة"
            message = (
                f"نسبة {bucket_name or asset_symbol} الحالية {_fmt(check.current_value)}% "
                f"تجاوزت الحد الذي حددته للتنبيه ({_fmt(check.threshold_value)}%). "
                f"راجع توزيع المحفظة لتقييم الموقف."
            )
        else:  # REBALANCE_SUGGESTED
            severity = NotificationSeverity.INFO
            title = f"{bucket_name or asset_symbol}: فرصة لمراجعة التوازن"
            message = (
                f"{bucket_name or asset_symbol} خارج نطاق الهدف أو الحد الأقصى المحدد لها — "
                f"يُنصح بمراجعة توزيع المحفظة."
            )
        return NotificationContent(
            source_id=source_id,
            category=category,
            severity=severity,
            title=title,
            message=message,
            target_category=bucket_name,
            target_asset=None,
            action=action,
        )

    if check.alert_type in _PRICE_ALERT_TYPES:
        category = NotificationCategory.PRICE_ALERT
        severity = NotificationSeverity.INFO
        if check.alert_type == AlertType.PRICE_TARGET:
            title = f"{asset_symbol}: تم الوصول للسعر المستهدف"
            message = f"تم الوصول إلى السعر المحدد لسهم {asset_symbol} ({_fmt(check.current_value)})."
        else:  # DIP_BUY
            title = f"{asset_symbol}: فرصة شراء عند انخفاض السعر"
            message = f"انخفض سعر {asset_symbol} إلى مستوى فرصة الشراء الذي حددته ({_fmt(check.current_value)})."
        return NotificationContent(
            source_id=source_id,
            category=category,
            severity=severity,
            title=title,
            message=message,
            target_category=None,
            target_asset=asset_symbol,
            action=NotificationAction.OPEN_ASSET,
        )

    return None


def is_recommendation_notify_worthy(recommendation_type: str) -> bool:
    return recommendation_type in _NOTIFY_WORTHY_RECOMMENDATION_TYPES


def build_recommendation_notification_content(
    *,
    recommendation_id: str,
    recommendation_type: str,
    severity: str,
    title: str,
    message: str,
    target_category: str | None,
) -> NotificationContent | None:
    """Builds notification content for one Phase 18 recommendation —
    `title`/`message` are reused VERBATIM, never recomposed (see module
    docstring). Returns `None` when the recommendation type is not
    notification-worthy (see `is_recommendation_notify_worthy`)."""
    if not is_recommendation_notify_worthy(recommendation_type):
        return None
    return NotificationContent(
        source_id=f"RECOMMENDATION:{recommendation_id}",
        category=NotificationCategory.RECOMMENDATION_ALERT,
        severity=NotificationSeverity(severity),
        title=title,
        message=message,
        target_category=target_category,
        target_asset=None,
        action=NotificationAction.REVIEW_RECOMMENDATIONS,
    )


def _fmt(value: Decimal | None) -> str:
    return "—" if value is None else f"{value:.2f}"
