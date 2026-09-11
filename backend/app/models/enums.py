import enum


class AssetType(str, enum.Enum):
    STOCK = "STOCK"
    FUND = "FUND"
    GOLD = "GOLD"
    CASH = "CASH"
    SAVINGS = "SAVINGS"
    ETF = "ETF"
    OTHER = "OTHER"


class TransactionType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"


class NotificationCategory(str, enum.Enum):
    """Phase 19: the top-level grouping shown in the Notification Center —
    deliberately separate from the underlying `AlertType`
    (domain/alert_engine.py) / `RecommendationType`
    (domain/recommendation_engine.py) a notification was sourced from, so
    the UI can group by "what kind of thing needs attention" without the
    two existing, unrelated enums needing to share one vocabulary.
    `PORTFOLIO_HEALTH_ALERT` is reserved but currently never emitted — see
    DECISIONS.md, "Phase 19 — Alerts & Notifications" for why no existing
    signal distinctly warrants a fourth, separate category yet."""

    PRICE_ALERT = "PRICE_ALERT"
    ALLOCATION_ALERT = "ALLOCATION_ALERT"
    RECOMMENDATION_ALERT = "RECOMMENDATION_ALERT"
    PORTFOLIO_HEALTH_ALERT = "PORTFOLIO_HEALTH_ALERT"


class NotificationSeverity(str, enum.Enum):
    """Phase 19. Values intentionally match
    `domain.recommendation_engine.RecommendationSeverity` (minus
    `SUCCESS`, which is never notification-worthy) so a Phase 18
    recommendation's own severity is reused verbatim, never re-graded."""

    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class NotificationAction(str, enum.Enum):
    """Phase 19: navigation-only hints for "where should the user go to
    look into this" — never an execution action. No automatic trade is
    ever implied or triggered by any of these values."""

    REVIEW_DISTRIBUTION = "REVIEW_DISTRIBUTION"
    REVIEW_RECOMMENDATIONS = "REVIEW_RECOMMENDATIONS"
    OPEN_ASSET = "OPEN_ASSET"
