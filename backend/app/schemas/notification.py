"""API response schemas for the Notification Center (Phase 19).

See app/domain/notification_engine.py for the semantics this mirrors.
`GET`/list is read-only w.r.t. financial state (see FINANCIAL_RULES.md,
"Notification Layer Rules"); the read-state endpoints mutate only
notification metadata (`read_at`), never anything financial.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: UUID
    category: str
    severity: str
    title: str
    message: str
    target_category: str | None
    target_asset: str | None
    action: str | None
    read: bool
    created_at: datetime


class NotificationsOut(BaseModel):
    unread_count: int
    notifications: list[NotificationOut]
