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

Usage:
    python -m app.workers.snapshot_eod

Exit code is always 0 if the run completed, including the no-op case (an
EOD snapshot already exists for today); a non-zero exit means the run
itself could not complete (e.g. no database connection, or no portfolio
configuration exists yet).
"""

import asyncio
import logging

from app.core.database import async_session_factory
from app.repositories.portfolio_repository import get_portfolio_config
from app.services.snapshot_service import create_eod_snapshot_if_missing

logger = logging.getLogger(__name__)


class PortfolioNotConfiguredError(Exception):
    """Raised when no portfolio_configs row exists yet (mirrors the same-
    named exception independently defined in the services this worker
    calls, per this codebase's established convention)."""


async def run_snapshot_eod() -> None:
    async with async_session_factory() as session:
        config = await get_portfolio_config(session)
        if config is None:
            raise PortfolioNotConfiguredError("No portfolio configuration exists yet.")
        snapshot = await create_eod_snapshot_if_missing(session, config=config)

    if snapshot is None:
        logger.info("EOD snapshot run complete: already exists for today (UTC) -- no-op.")
    else:
        logger.info("EOD snapshot run complete: created snapshot %s at %s.", snapshot.id, snapshot.snapshot_at)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_snapshot_eod())


if __name__ == "__main__":
    main()
