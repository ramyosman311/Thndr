"""Read-only production diagnostic (recovery investigation). Writes nothing.

Runs inside a READ ONLY transaction: row counts of every public table, the
Postgres per-table insert/update/delete counters (history since stats reset),
auth.users (count and creation dates only -- no e-mails), and backup/PITR
signals visible from SQL. Connects with DATABASE_URL.
"""

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"], connect_args={"statement_cache_size": 0})
    async with engine.connect() as conn:
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        print("server_version:", (await conn.execute(text("SHOW server_version"))).scalar_one())
        print("postmaster_start_time:", (await conn.execute(text("SELECT pg_postmaster_start_time()"))).scalar_one())
        row = (await conn.execute(text(
            "SELECT stats_reset, xact_commit, tup_inserted, tup_updated, tup_deleted "
            "FROM pg_stat_database WHERE datname = current_database()"))).one()
        print("pg_stat_database: stats_reset=%s xact_commit=%s tup_inserted=%s tup_updated=%s tup_deleted=%s" % tuple(row))
        print("alembic_version:", (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one())
        print("--- public tables: live rows (exact) | lifetime inserts/updates/deletes | last_autovacuum")
        names = [r[0] for r in (await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).all()]
        for name in names:
            n = (await conn.execute(text(f'SELECT count(*) FROM public."{name}"'))).scalar_one()
            st = (await conn.execute(text(
                "SELECT n_tup_ins, n_tup_upd, n_tup_del, last_autovacuum FROM pg_stat_user_tables WHERE relname=:t"),
                {"t": name})).first()
            print(f"{name}: rows={n} | ins/upd/del={tuple(st[:3]) if st else None} | last_autovacuum={st[3] if st else None}")
        print("--- auth.users (counts/dates only)")
        try:
            r = (await conn.execute(text("SELECT count(*), min(created_at), max(created_at), max(last_sign_in_at) FROM auth.users"))).one()
            print("auth.users: count=%s first_created=%s last_created=%s last_sign_in=%s" % tuple(r))
        except Exception as exc:
            print("auth.users unreadable:", exc.__class__.__name__)
        print("--- other schemas present")
        print([r[0] for r in (await conn.execute(text(
            "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\\_%' AND nspname <> 'information_schema' ORDER BY 1"))).all()])
        print("--- other databases visible to this role")
        print([r[0] for r in (await conn.execute(text("SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY 1"))).all()])
        await conn.rollback()
    await engine.dispose()


asyncio.run(main())
