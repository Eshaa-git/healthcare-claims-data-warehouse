"""Integration fixtures: a fresh test database on the running warehouse server per module.

Tests never touch the main warehouse database; they create and drop `claims_test`.
Skipped when the warehouse is not reachable (start it with `make up`).
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from claims_dw import db, ingest, publish, reconcile
from claims_dw.config import ConfigError, Settings, load_dotenv_if_present, load_settings
from claims_dw.dbt_steps import run_dbt

TEST_DB = os.environ.get("CLAIMS_DW_TEST_DB", "claims_test")


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    load_dotenv_if_present()
    try:
        base = load_settings()
    except ConfigError as exc:
        pytest.skip(f"warehouse credentials not configured: {exc}")
    s = replace(
        base,
        db=replace(base.db, database=TEST_DB),
        data_dir=tmp_path_factory.mktemp("data"),
        source="fixture",
        cohort_size=1000,
        chunk_rows=7,
    )
    try:
        admin = psycopg.connect(
            host=s.db.host,
            port=s.db.port,
            dbname="postgres",
            user=s.db.admin_user,
            password=s.db.admin_password,
            autocommit=True,
            connect_timeout=5,
        )
    except psycopg.OperationalError as exc:
        pytest.skip(f"warehouse not reachable ({exc}); run `make up`")
    with admin:
        admin.execute(f'drop database if exists "{TEST_DB}" with (force)')
        admin.execute(f'create database "{TEST_DB}"')
    db.migrate(s)
    return s


def full_run(settings: Settings, run_id: str) -> list[ingest.LoadResult]:
    """stage -> dbt run -> dbt test -> reconcile -> publish (acquire/cohort done by caller)."""
    results = ingest.stage_all(settings, run_id)
    run_dbt(settings, "run", "--quiet")
    run_dbt(settings, "test", "--quiet")
    reconcile.reconcile(settings, run_id)
    publish.publish(settings, run_id)
    return results


def scalar(settings: Settings, query: str, params: tuple = (), role: str = "admin"):
    with db.connect(settings, role) as conn:
        return conn.execute(query, params).fetchone()[0]


def rows(settings: Settings, query: str, params: tuple = (), role: str = "admin"):
    with db.connect(settings, role) as conn:
        return conn.execute(query, params).fetchall()


def snapshot(settings: Settings, schema: str = "marts") -> dict:
    out = {}
    for table, amount in [
        ("fact_inpatient_claim", "medicare_claim_payment_amt"),
        ("fact_outpatient_claim", "medicare_claim_payment_amt"),
        ("fact_drug_event", "gross_drug_cost_amt"),
        ("dim_beneficiary_year", "year"),
    ]:
        out[table] = rows(settings, f"select count(*), sum({amount}) from {schema}.{table}")[0]
    out["monthly_payments"] = rows(
        settings, f"select * from {schema}.mart_monthly_claim_payments order by 1, 2"
    )
    return out


def write_evidence(name: str, payload: dict) -> None:
    target = os.environ.get("CLAIMS_DW_EVIDENCE_DIR")
    if not target:
        return
    path = Path(target)
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{name}.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")


def money(value) -> Decimal:
    return Decimal(str(value))
