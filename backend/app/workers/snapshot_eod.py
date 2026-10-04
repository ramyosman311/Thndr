"""Background end-of-day snapshot entrypoint (Phase 15).

Run out-of-band from the FastAPI process -- by an external scheduler
(cron, a platform's scheduled-job feature), never as an in-app asyncio
loop inside the API server. Follows the exact same execution model already
established by `app/workers/price_refresh.py` (Phase 11) and
`app/workers/alert_notify.py` (Phase 14) -- this project has no in-repo
scheduling infrastructure, and none is introduced here.

"End of day" currently means UTC calendar day -- NOT Egypt-local EGX
market close (see DECISIONS.md, "Phase 15 EOD Convention"). Running this
worker more than once on the same UTC calendar day is safe: the second
(and any subsequent) run that day is a no-op, both at the application
level (services/snapshot_service.py checks first) and at the database
level (the `uq_portfolio_snapshot_eod_per_day` partial unique index is the
concurrency backstop for two overlapping runs).

P0-3C: iterates EXPLICITLY over every owned portfolio (never "the first
portfolio"), creating each one's own snapshot from that portfolio's own
holdings and transactions. Unowned (legacy, pre-ownership) portfolios are
skipped: their holdings/transactions carry no owner link, so a snapshot
computed for one would silently be empty and corrupt its history. One
portfolio failing never prevents the others from being snapshotted; the run
still exits non-zero afterward so a scheduler notices.

Usage:
    python -m app.workers.snapshot_eod

Exit code is always 0 if the run completed, including the no-op case (an
EOD snapshot already exists for today); a non-zero exit means the run
itself could not complete (e.g. no database connection, no owned portfolio
exists yet, or any portfolio's snapshot failed).
"""

import asyncio
import logging

from app.core.database import async_session_factory
from app.core.logging_config import configure_logging
from app.models import PortfolioConfig
from app.repositories.portfolio_repository import list_owned_portfolio_configs
from app.services.snapshot_service import create_eod_snapshot_if_missing

logger = logging.getLogger(__name__)


class PortfolioNotConfiguredError(Exception):
    """Raised when no owned portfolio_configs row exists yet (mirrors the
    same-named exception independently defined in the services this worker
    calls, per this codebase's established convention)."""


async def run_snapshot_eod() -> None:
    created = 0
    already_present = 0
    failed = 0

    async with async_session_factory() as session:
        config_ids = [config.id for config in await list_owned_portfolio_configs(session)]
        if not config_ids:
            raise PortfolioNotConfiguredError("No owned portfolio configuration exists yet.")

        for config_id in config_ids:
            try:
                # Re-fetched per portfolio: a rollback after one portfolio's
                # failure expires every loaded object in the session.
                config = await session.get(PortfolioConfig, config_id)
                snapshot = await create_eod_snapshot_if_missing(session, config=config)
            except Exception:
                await session.rollback()
                logger.exception("EOD snapshot failed for portfolio %s; continuing with the rest.", config_id)
                failed += 1
                continue
            if snapshot is None:
                already_present += 1
            else:
                created += 1
                logger.info("Created EOD snapshot %s for portfolio %s.", snapshot.id, config_id)

    logger.info(
        "EOD snapshot run complete: %d created, %d already existed for today (UTC), %d failed.",
        created,
        already_present,
        failed,
    )
    if failed:
        raise RuntimeError(f"EOD snapshot failed for {failed} portfolio(s); see log.")


def main() -> None:
    configure_logging()
    asyncio.run(run_snapshot_eod())


if __name__ == "__main__":
    main()
