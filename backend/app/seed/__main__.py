"""Developer entrypoint: `python -m app.seed` from the backend/ directory.

Safe to run repeatedly — see seed.py docstring for idempotency guarantees.
This is development seed data only; it is never invoked by the application
itself and is not run as part of any migration.
"""

import asyncio

from app.core.database import async_session_factory
from app.seed.seed import run_seed


async def main() -> None:
    async with async_session_factory() as session:
        await run_seed(session)
    print("Seed completed.")


if __name__ == "__main__":
    asyncio.run(main())
