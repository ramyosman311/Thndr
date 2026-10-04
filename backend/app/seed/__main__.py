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

P0-3C: set SEED_OWNER_USER_ID to a Supabase Auth user UUID to make the
newly-seeded portfolio owned by that user; otherwise it is unowned and no
authenticated request can see it. Nothing here ever reassigns an existing
portfolio.
"""

import asyncio
import os
import sys
from uuid import UUID

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

    owner_user_id = UUID(os.environ["SEED_OWNER_USER_ID"]) if os.environ.get("SEED_OWNER_USER_ID") else None
    if owner_user_id is None:
        print(
            "SEED_OWNER_USER_ID is not set: the seeded portfolio will be unowned and invisible "
            "to every authenticated request.",
            file=sys.stderr,
        )

    async with async_session_factory() as session:
        await run_seed(session, owner_user_id)
    print("Seed completed.")


if __name__ == "__main__":
    asyncio.run(main())
