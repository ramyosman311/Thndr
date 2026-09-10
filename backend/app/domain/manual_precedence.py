"""Manual-vs-automated price precedence (Phase 11).

NON-NEGOTIABLE BUSINESS RULE (see FINANCIAL_RULES.md, "Manual vs.
Automated Price Precedence"): a manual price override remains
authoritative until a strictly newer automated observation is
successfully fetched — unless `lock_manual` is set, in which case no
automated observation may ever supersede it while the lock holds.

This function only decides whether one specific automated observation
may be *accepted* as superseding the current manual price. It never
mutates or deletes the manual observation itself — price observations
are immutable historical facts (see models/asset_price.py); "losing"
here just means the automated observation is still stored (for history)
but is not treated as the current authoritative price.
"""

from datetime import datetime


def may_automated_observation_supersede_manual(
    *,
    lock_manual: bool,
    manual_recorded_at: datetime | None,
    automated_timestamp: datetime,
) -> bool:
    if lock_manual:
        return False
    if manual_recorded_at is None:
        return True  # no manual observation exists at all -- nothing to protect
    # Strictly greater: an automated timestamp equal to the manual one
    # must NOT supersede it (see FINANCIAL_RULES.md — "timestamp <=
    # manual_updated_at MUST NOT supersede").
    return automated_timestamp > manual_recorded_at
