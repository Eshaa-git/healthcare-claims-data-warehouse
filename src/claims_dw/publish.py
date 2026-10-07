"""Atomically promote the tested build schema to the published `marts` schema."""

from __future__ import annotations

import json

from psycopg import sql

from .config import (
    BUILD_MARTS_SCHEMA,
    DASHBOARD_ROLE,
    PREVIOUS_SCHEMA,
    PUBLISHED_SCHEMA,
    Settings,
)
from .db import connect


class PublishRefused(RuntimeError):
    pass


def publish(settings: Settings, run_id: str) -> dict:
    """Swap dw_build_marts -> marts in one transaction; keep the prior marts as marts_previous.

    Refuses unless this run recorded reconciliation results and all of them passed, so a failed
    or skipped reconciliation can never replace the last good marts.
    """
    with connect(settings, "transformer") as conn, conn.transaction():
        conn.execute("select pg_advisory_xact_lock(hashtext('claims-dw-publish'))")
        total, passed = conn.execute(
            "select count(*), count(*) filter (where passed) from ops.reconciliation_results "
            "where run_id = %s",
            (run_id,),
        ).fetchone()
        if total == 0 or passed != total:
            raise PublishRefused(
                f"run {run_id}: reconciliation has {passed}/{total} passing checks; not publishing"
            )
        schemas = {
            r[0]
            for r in conn.execute(
                "select nspname from pg_namespace where nspname = any(%s)",
                ([BUILD_MARTS_SCHEMA, PUBLISHED_SCHEMA, PREVIOUS_SCHEMA],),
            ).fetchall()
        }
        if BUILD_MARTS_SCHEMA not in schemas:
            raise PublishRefused(f"{BUILD_MARTS_SCHEMA} does not exist; run dbt first")
        previous = None
        conn.execute(f"drop schema if exists {PREVIOUS_SCHEMA} cascade")
        if PUBLISHED_SCHEMA in schemas:
            conn.execute(f"alter schema {PUBLISHED_SCHEMA} rename to {PREVIOUS_SCHEMA}")
            previous = PREVIOUS_SCHEMA
        conn.execute(f"alter schema {BUILD_MARTS_SCHEMA} rename to {PUBLISHED_SCHEMA}")
        conn.execute(f"grant usage on schema {PUBLISHED_SCHEMA} to {DASHBOARD_ROLE}")
        conn.execute(f"grant select on all tables in schema {PUBLISHED_SCHEMA} to {DASHBOARD_ROLE}")
        tables = [
            r[0]
            for r in conn.execute(
                "select tablename from pg_tables where schemaname = %s order by 1",
                (PUBLISHED_SCHEMA,),
            ).fetchall()
        ]
        conn.execute(
            sql.SQL(
                "create table {}.publication_info as select {}::text as run_id, "
                "now() as published_at, {}::integer as reconciliation_checks"
            ).format(sql.Identifier(PUBLISHED_SCHEMA), sql.Literal(run_id), sql.Literal(total))
        )
        conn.execute(f"grant select on {PUBLISHED_SCHEMA}.publication_info to {DASHBOARD_ROLE}")
        detail = {"tables": tables, "reconciliation_checks": total}
        conn.execute(
            "insert into ops.publications (run_id, published_schema, previous_schema, detail) "
            "values (%s, %s, %s, %s)",
            (run_id, PUBLISHED_SCHEMA, previous, json.dumps(detail)),
        )
    return detail
