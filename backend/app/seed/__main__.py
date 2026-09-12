"""Developer entrypoint: `python -m app.seed` from the backend/ directory.

Safe to run repeatedly — see seed.py docstring for idempotency guarantees.
This is development/demo seed data only (sample assets like "CLOUDZ" that
have no place in a real user's portfolio); it is never invoked by the
application itself and is not run as part of any migration.

Phase 23: refuses to run against APP_ENV=production by default, even
though the seed itself is non-destructive (it only ever creates missing
rows, never deletes) — the risk isn't data loss, it's injecting fake demo
assets/config into a real production portfolio by an operator's mistake
(e.g. a copy-pasted command meant for staging). Set
ALLOW_SEED_IN_PRODUCTION=1 to override for a deliberate case (seeding a
fresh environment that is flagged APP_ENV=production for other reasons,
e.g. a pre-launch demo instance).
"""

import asyncio
import os
import sys

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.seed.seed import run_seed


async def main() -> None:
    settings = get_settings()
    if settings.is_production and os.environ.get("ALLOW_SEED_IN_PRODUCTION") != "1":
        print(
            "Refusing to run development seed data against APP_ENV=production. "
            "Set ALLOW_SEED_IN_PRODUCTION=1 to override if this is deliberate.",
            file=sys.stderr,
        )
        sys.exit(1)

    async with async_session_factory() as session:
        await run_seed(session)
    print("Seed completed.")


if __name__ == "__main__":
    asyncio.run(main())
