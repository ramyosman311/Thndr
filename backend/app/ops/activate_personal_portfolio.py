"""Ownership activation for the Personal Beta (P0-3D). Operator-run, never by the app.

Maps the ONE existing, previously-unowned production portfolio to the
operator's Supabase Auth user, so the P0-3C ownership scoping (which makes
unowned rows invisible to every request) starts showing them to that user.

This is an ownership activation, NOT a data migration. It writes only
ownership columns:

  * ``portfolio_configs.user_id``                     (NULL -> the verified user)
  * ``<child>.portfolio_config_id`` where it is NULL  (-> that same portfolio)
    for holdings, transactions, watchlist, alert_rules, notifications --
    the P0-3C child tables are scoped by their own ``portfolio_config_id``,
    so without this the portfolio would be owned but appear empty.
  * ``users``: the local row for the Supabase user (``id`` only), if missing.

It never deletes or recreates a row and never touches a financial value. Every
table's content (excluding only the ownership column it is allowed to change)
is fingerprinted before and after inside the same transaction; any difference,
or any row-count change, aborts and rolls back.

Nothing is guessed:
  * the user is looked up in ``auth.users`` by the e-mail the operator passes,
    and must match exactly one account;
  * the portfolio must be the ONLY ``portfolio_configs`` row. 0 rows or 2+ rows
    stop the run (exit 3 / 4) -- candidates are printed, nothing is written;
  * a portfolio already owned by a different user is never reassigned (exit 5).

Default is a dry run: the same writes are executed and fingerprint-verified,
then rolled back. ``--apply`` commits.

    python -m app.ops.activate_personal_portfolio --email you@example.com [--apply]

Connects with DATABASE_URL (asyncpg URL), like the app and Alembic.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

EXIT_OK = 0
EXIT_USER = 2  # auth user not found / ambiguous
EXIT_NO_PORTFOLIO = 3
EXIT_MANY_PORTFOLIOS = 4
EXIT_OWNED_BY_OTHER = 5
EXIT_UNSAFE = 6  # schema not ready, foreign-owned child rows, or fingerprint drift

# Child tables scoped by their own portfolio_config_id (P0-3C).
OWNED_CHILD_TABLES = ("holdings", "transactions", "watchlist", "alert_rules", "notifications")

# Every table whose content must be byte-identical after activation, mapped to
# the single ownership key (if any) the activation is allowed to change in it.
FINGERPRINT_TABLES: dict[str, str | None] = {
    "portfolio_configs": "user_id",
    "holdings": "portfolio_config_id",
    "transactions": "portfolio_config_id",
    "watchlist": "portfolio_config_id",
    "alert_rules": "portfolio_config_id",
    "notifications": "portfolio_config_id",
    "portfolio_snapshots": None,
    "portfolio_snapshot_items": None,
    "strategy_buckets": None,
    "allocation_targets": None,
    "assets": None,
    "asset_price_configs": None,
    "asset_prices": None,
    "fx_rates": None,
}

# Counted per portfolio for the operator's "is this really my portfolio" check.
COUNT_TABLES = (
    "holdings",
    "transactions",
    "watchlist",
    "alert_rules",
    "notifications",
    "portfolio_snapshots",
    "strategy_buckets",
    "allocation_targets",
)

REQUIRED_OWNERSHIP_COLUMNS = (("portfolio_configs", "user_id"),) + tuple(
    (table, "portfolio_config_id") for table in OWNED_CHILD_TABLES
)


class ActivationError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    user_id: uuid.UUID | None = None
    portfolio_id: uuid.UUID | None = None
    committed_changes: dict[str, int] = field(default_factory=dict)

    def add(self, line: str = "") -> None:
        self.lines.append(line)


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


async def _scalar(conn: AsyncConnection, sql: str, **params):
    return (await conn.execute(text(sql), params)).scalar_one()


async def _fingerprint(conn: AsyncConnection) -> dict[str, tuple[int, str]]:
    """(row count, md5 of every row's content minus the one allowed ownership key) per table."""
    result: dict[str, tuple[int, str]] = {}
    for table, owner_key in FINGERPRINT_TABLES.items():
        row_json = f"to_jsonb(t) - '{owner_key}'" if owner_key else "to_jsonb(t)"
        row = (
            await conn.execute(
                text(
                    f"SELECT count(*), coalesce(md5(string_agg(({row_json})::text, '|' ORDER BY t.id)), '') "
                    f"FROM {table} t"
                )
            )
        ).one()
        result[table] = (int(row[0]), str(row[1]))
    return result


async def _check_schema(conn: AsyncConnection, report: Report) -> None:
    try:
        version = await _scalar(conn, "SELECT version_num FROM alembic_version")
    except Exception as exc:  # table missing -> database was never migrated
        raise ActivationError(EXIT_UNSAFE, f"alembic_version unreadable ({exc.__class__.__name__}): database not migrated") from exc
    report.add(f"alembic revision: {version}")
    present = {
        (r[0], r[1])
        for r in (
            await conn.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name IN ('user_id', 'portfolio_config_id')"
                )
            )
        ).all()
    }
    missing = [f"{t}.{c}" for t, c in REQUIRED_OWNERSHIP_COLUMNS if (t, c) not in present]
    if missing:
        raise ActivationError(
            EXIT_UNSAFE,
            f"ownership columns missing ({', '.join(missing)}): run the production migration (alembic upgrade head) first",
        )


async def _find_user(conn: AsyncConnection, email: str, report: Report) -> uuid.UUID:
    rows = (
        await conn.execute(
            text("SELECT id FROM auth.users WHERE lower(email) = lower(:email)"), {"email": email.strip()}
        )
    ).all()
    total = await _scalar(conn, "SELECT count(*) FROM auth.users")
    report.add(f"auth.users accounts in this project: {total}")
    if len(rows) != 1:
        raise ActivationError(
            EXIT_USER,
            f"expected exactly one Supabase auth user for {mask_email(email)}, found {len(rows)} "
            "(create the user in Supabase Dashboard -> Authentication -> Users first)",
        )
    user_id = rows[0][0]
    report.add(f"auth user: {mask_email(email)} -> {user_id}")
    return user_id


async def _describe_portfolios(conn: AsyncConnection, report: Report) -> list[tuple[uuid.UUID, uuid.UUID | None]]:
    portfolios = (
        await conn.execute(text("SELECT id, user_id, name, base_currency FROM portfolio_configs ORDER BY created_at, id"))
    ).all()
    report.add(f"portfolio_configs rows: {len(portfolios)}")
    for pid, owner, name, currency in portfolios:
        counts = {}
        for table in COUNT_TABLES:
            if table in ("portfolio_snapshots", "strategy_buckets", "allocation_targets"):
                counts[table] = await _scalar(
                    conn, f"SELECT count(*) FROM {table} WHERE portfolio_config_id = :p", p=pid
                )
            else:
                counts[table] = await _scalar(conn, f"SELECT count(*) FROM {table}")
        owner_label = str(owner) if owner else "UNOWNED"
        report.add(f"  - {pid} name={name!r} currency={currency} owner={owner_label}")
        report.add("    " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return [(p[0], p[1]) for p in portfolios]


async def run(conn: AsyncConnection, email: str, *, report: Report | None = None) -> Report:
    """Performs the activation inside the caller's transaction (never commits).

    The caller commits for ``--apply`` and rolls back for a dry run. Raises
    ``ActivationError`` (exit code attached) on every stop condition.
    """
    report = report or Report()
    await _check_schema(conn, report)
    portfolios = await _describe_portfolios(conn, report)
    if not portfolios:
        raise ActivationError(EXIT_NO_PORTFOLIO, "no portfolio_configs row exists: nothing to activate (stop and report)")
    if len(portfolios) > 1:
        raise ActivationError(
            EXIT_MANY_PORTFOLIOS,
            f"{len(portfolios)} candidate portfolios (listed above): refusing to guess which one is yours",
        )
    user_id = await _find_user(conn, email, report)
    report.user_id = user_id
    portfolio_id, current_owner = portfolios[0]
    report.portfolio_id = portfolio_id
    if current_owner is not None and current_owner != user_id:
        raise ActivationError(EXIT_OWNED_BY_OTHER, f"portfolio is already owned by {current_owner}: never reassigned")

    for table in OWNED_CHILD_TABLES:
        foreign = await _scalar(
            conn,
            f"SELECT count(*) FROM {table} WHERE portfolio_config_id IS NOT NULL AND portfolio_config_id <> :p",
            p=portfolio_id,
        )
        if foreign:
            raise ActivationError(EXIT_UNSAFE, f"{table} has {foreign} row(s) owned by another portfolio: unexpected, stopping")

    before = await _fingerprint(conn)

    changes: dict[str, int] = {}
    inserted = await conn.execute(
        text("INSERT INTO users (id) VALUES (:u) ON CONFLICT (id) DO NOTHING"), {"u": user_id}
    )
    changes["users (local row created)"] = inserted.rowcount
    updated = await conn.execute(
        text("UPDATE portfolio_configs SET user_id = :u WHERE id = :p AND user_id IS NULL"),
        {"u": user_id, "p": portfolio_id},
    )
    changes["portfolio_configs.user_id set"] = updated.rowcount
    for table in OWNED_CHILD_TABLES:
        result = await conn.execute(
            text(f"UPDATE {table} SET portfolio_config_id = :p WHERE portfolio_config_id IS NULL"),
            {"p": portfolio_id},
        )
        changes[f"{table}.portfolio_config_id set"] = result.rowcount
    report.committed_changes = changes

    after = await _fingerprint(conn)
    drift = [t for t in before if before[t] != after[t]]
    if drift:
        raise ActivationError(EXIT_UNSAFE, f"content changed in {drift}: ownership activation must change nothing else -- aborting")

    # Positive verification: the portfolio is reachable by the user, nothing left unowned.
    owner_now = await _scalar(conn, "SELECT user_id FROM portfolio_configs WHERE id = :p", p=portfolio_id)
    if owner_now != user_id:
        raise ActivationError(EXIT_UNSAFE, "portfolio owner is not the verified user after update")
    for table in OWNED_CHILD_TABLES:
        orphans = await _scalar(conn, f"SELECT count(*) FROM {table} WHERE portfolio_config_id IS NULL")
        if orphans:
            raise ActivationError(EXIT_UNSAFE, f"{table} still has {orphans} unowned row(s)")

    report.add("changes (ownership columns only):")
    for label, n in changes.items():
        report.add(f"  {label}: {n}")
    report.add("verified: row counts and content of all financial tables identical before/after")
    report.add("visible to the user after activation:")
    for table in OWNED_CHILD_TABLES:
        n = await _scalar(conn, f"SELECT count(*) FROM {table} WHERE portfolio_config_id = :p", p=portfolio_id)
        report.add(f"  {table}: {n}")
    return report


async def _main(email: str, apply: bool, database_url: str) -> int:
    engine = create_async_engine(database_url, connect_args={"statement_cache_size": 0})
    report = Report()
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                await run(conn, email, report=report)
            except ActivationError as exc:
                await trans.rollback()
                print("\n".join(report.lines))
                print(f"STOP (exit {exc.code}): {exc}")
                return exc.code
            if apply:
                await trans.commit()
                print("\n".join(report.lines))
                print("APPLIED: ownership activation committed.")
            else:
                await trans.rollback()
                print("\n".join(report.lines))
                print("DRY RUN: all checks passed; nothing was written. Re-run with --apply to commit.")
    finally:
        await engine.dispose()
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    import os

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True, help="e-mail of the Supabase Auth user who will own the portfolio")
    parser.add_argument("--apply", action="store_true", help="commit (default is a rolled-back dry run)")
    args = parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return EXIT_UNSAFE
    return asyncio.run(_main(args.email, args.apply, database_url))


if __name__ == "__main__":
    raise SystemExit(main())
