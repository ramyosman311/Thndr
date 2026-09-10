"""Background price refresh entrypoint (Phase 11).

Run out-of-band from the FastAPI process -- by an external scheduler
(cron, a platform's scheduled-job feature, a long-running worker loop
started by the process manager), never as an in-app asyncio loop inside
the API server (see DEPLOYMENT.md, "Workers (alerts, Telegram)", the
same execution model this follows). This is the only code path allowed
to call services/price_orchestrator.py, which is in turn the only code
path allowed to call a live PriceProvider -- see FINANCIAL_RULES.md,
"Non-Blocking Valuation".

Usage:
    python -m app.workers.price_refresh

Exit code is always 0 if the run completed (even if individual assets
failed to refresh -- that is expected, ordinary, per-asset behavior,
not a worker crash); a non-zero exit means the run itself could not
complete (e.g. no database connection).
"""

import asyncio
import logging

from app.core.database import async_session_factory
from app.services.price_orchestrator import refresh_all_automated_assets

logger = logging.getLogger(__name__)


async def run_price_refresh() -> None:
    async with async_session_factory() as session:
        outcomes = await refresh_all_automated_assets(session)
        await session.commit()

    stored = sum(1 for outcome in outcomes if outcome.stored)
    failed = sum(1 for outcome in outcomes if not outcome.succeeded)
    skipped_for_manual_precedence = sum(
        1 for outcome in outcomes if outcome.succeeded and not outcome.stored
    )
    logger.info(
        "Price refresh complete: %d asset(s) processed, %d stored, %d skipped "
        "(manual precedence), %d failed.",
        len(outcomes),
        stored,
        skipped_for_manual_precedence,
        failed,
    )
    for outcome in outcomes:
        if not outcome.succeeded:
            logger.warning("Price refresh failed for asset %s: %s", outcome.asset_id, outcome.reason)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_price_refresh())


if __name__ == "__main__":
    main()
