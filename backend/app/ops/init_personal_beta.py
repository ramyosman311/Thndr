"""Fresh Personal Beta initialization (operator-run, never by the app).

Creates ONE empty portfolio owned by the operator's verified Supabase user,
plus the reference data and strategy configuration it needs -- and nothing
financial. Reuses the existing seed functions (so values come from
app/seed/data.py) but deliberately skips the demo snapshots.

Creates (only):
  * the local ``users`` row for the verified Supabase user
  * reference assets (instruments) and the EGX price-provider configs
  * one ``portfolio_configs`` row owned by that user (emergency asset wired
    by foreign key, ``emergency_excluded``)
  * strategy buckets, their asset assignments, and the allocation targets

Never creates holdings, transactions, snapshots, prices, balances, watchlist
entries, alert rules or notifications, and never alters the targets
(the explicit targets total 80% on purpose and are not normalised).

Never guesses and never bypasses ownership:
  * the user is looked up in ``auth.users`` by the e-mail passed in and must
    match exactly one account (its UUID becomes the owner);
  * it refuses to run unless the database is a clean start: zero
    ``portfolio_configs`` rows and zero holdings/transactions/snapshots/
    watchlist/alert/notification rows (exit 3 otherwise);
  * default is a dry run (same writes, verified, then rolled back);
    ``--apply`` commits.

    python -m app.ops.init_personal_beta --email you@example.com [--apply]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.seed.data import EMERGENCY_ASSET_SYMBOL
from app.seed.seed import (
    seed_allocation_targets,
    seed_asset_price_configs,
    seed_assets,
    seed_portfolio_config,
    seed_strategy_buckets,
)

EXIT_OK = 0
EXIT_USER = 2
EXIT_NOT_CLEAN = 3
EXIT_UNSAFE = 6

# Tables that must be empty before, and stay empty after, initialization.
FINANCIAL_TABLES = (
    "holdings",
    "transactions",
    "portfolio_snapshots",
    "portfolio_snapshot_items",
    "asset_prices",
    "fx_rates",
    "watchlist",
    "alert_rules",
    "notifications",
)
REPORT_TABLES = (
    "users",
    "assets",
    "asset_price_configs",
    "portfolio_configs",
    "strategy_buckets",
    "allocation_targets",
) + FINANCIAL_TABLES


class InitError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    user_id: uuid.UUID | None = None
    portfolio_id: uuid.UUID | None = None

    def add(self, line: str = "") -> None:
        self.lines.append(line)


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


async def _count(session: AsyncSession, table: str) -> int:
    return int((await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())


async def run(session: AsyncSession, email: str, *, report: Report | None = None) -> Report:
    """Does the initialization inside the caller's transaction (never commits)."""
    report = report or Report()

    try:
        version = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    except Exception as exc:
        raise InitError(EXIT_UNSAFE, f"alembic_version unreadable ({exc.__class__.__name__})") from exc
    report.add(f"alembic revision: {version}")

    user_rows = (
        await session.execute(
            text("SELECT id FROM auth.users WHERE lower(email) = lower(:e)"), {"e": email.strip()}
        )
    ).all()
    if len(user_rows) != 1:
        raise InitError(
            EXIT_USER,
            f"expected exactly one Supabase auth user for {mask_email(email)}, found {len(user_rows)} "
            "(create it in Supabase Dashboard -> Authentication -> Users first)",
        )
    user_id = user_rows[0][0]
    report.user_id = user_id
    report.add(f"auth user: {mask_email(email)} -> {user_id}")

    existing = await _count(session, "portfolio_configs")
    report.add(f"existing portfolio_configs rows: {existing}")
    if existing:
        raise InitError(EXIT_NOT_CLEAN, "portfolio_configs is not empty: not a clean start, refusing")
    for table in FINANCIAL_TABLES:
        n = await _count(session, table)
        if n:
            raise InitError(EXIT_NOT_CLEAN, f"{table} already has {n} row(s): not a clean start, refusing")

    before = {t: await _count(session, t) for t in REPORT_TABLES}

    assets = await seed_assets(session)
    config = await seed_portfolio_config(session, assets[EMERGENCY_ASSET_SYMBOL], user_id)
    buckets = await seed_strategy_buckets(session, config, assets)
    targets = await seed_allocation_targets(session, config, buckets)
    await seed_asset_price_configs(session, assets)
    await session.flush()
    report.portfolio_id = config.id

    after = {t: await _count(session, t) for t in REPORT_TABLES}
    for table in FINANCIAL_TABLES:
        if after[table] != 0:
            raise InitError(EXIT_UNSAFE, f"{table} gained rows: initialization must create no financial data")
    owner = (
        await session.execute(text("SELECT user_id FROM portfolio_configs WHERE id = :p"), {"p": config.id})
    ).scalar_one()
    if owner != user_id:
        raise InitError(EXIT_UNSAFE, "portfolio owner is not the verified user")

    report.add("would create / created (ownership: the verified user only):")
    for table in REPORT_TABLES[:6]:
        report.add(f"  {table}: {before[table]} -> {after[table]}")
    report.add("  financial tables (holdings, transactions, snapshots, prices, watchlist, alerts, notifications): all 0")
    report.add(f"portfolio: {config.name!r} {config.base_currency}, emergency_excluded={config.emergency_excluded}")
    report.add("allocation targets (explicit targets total is NOT normalised):")
    name_by_id = {b.id: n for n, b in buckets.items()}
    for t in sorted(targets, key=lambda x: x.priority):
        report.add(
            f"  {name_by_id[t.strategy_bucket_id]}: target={t.target_percent} max={t.maximum_percent} "
            f"allow_new_buy={t.allow_new_buy}"
        )
    return report


async def _main(email: str, apply: bool, database_url: str) -> int:
    engine = create_async_engine(database_url, connect_args={"statement_cache_size": 0})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    report = Report()
    try:
        async with factory() as session:
            try:
                await run(session, email, report=report)
            except InitError as exc:
                await session.rollback()
                print("\n".join(report.lines))
                print(f"STOP (exit {exc.code}): {exc}")
                return exc.code
            print("\n".join(report.lines))
            if apply:
                await session.commit()
                print("APPLIED: personal beta initialized (empty portfolio, no financial data).")
            else:
                await session.rollback()
                print("DRY RUN: all checks passed; nothing was written. Re-run with --apply to commit.")
    finally:
        await engine.dispose()
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    import os

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return EXIT_UNSAFE
    return asyncio.run(_main(args.email, args.apply, database_url))


if __name__ == "__main__":
    raise SystemExit(main())
