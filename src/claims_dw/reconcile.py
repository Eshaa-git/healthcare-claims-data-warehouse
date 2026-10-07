"""Source-to-warehouse reconciliation with exact decimal arithmetic (tolerance 0.00).

Null handling: amounts that are empty or unparseable in the source are excluded from sums on
both sides; rows with an unparseable required amount are quarantined, so they appear in the
row balance but not in the money balance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .config import BUILD_MARTS_SCHEMA, Settings
from .db import connect

MONEY_RE = r"^-?\d+(\.\d{1,2})?$"

# dataset -> (raw table, stage table, [(raw column, stage column)])
MONEY_COLUMNS = {
    "inpatient_claims": (
        "raw.inpatient_claims",
        "stage.inpatient_claim_segment",
        [("clm_pmt_amt", "claim_payment_amt")],
    ),
    "outpatient_claims": (
        "raw.outpatient_claims",
        "stage.outpatient_claim_segment",
        [("clm_pmt_amt", "claim_payment_amt")],
    ),
    "drug_events": (
        "raw.drug_events",
        "stage.drug_event",
        [("tot_rx_cst_amt", "gross_drug_cost_amt"), ("ptnt_pay_amt", "patient_pay_amt")],
    ),
}
STAGE_TABLES = {
    "beneficiary_summary": "stage.beneficiary_year",
    "inpatient_claims": "stage.inpatient_claim_segment",
    "outpatient_claims": "stage.outpatient_claim_segment",
    "drug_events": "stage.drug_event",
}
RAW_TABLES = {
    "beneficiary_summary": "raw.beneficiary_summary",
    "inpatient_claims": "raw.inpatient_claims",
    "outpatient_claims": "raw.outpatient_claims",
    "drug_events": "raw.drug_events",
}


class ReconciliationFailed(RuntimeError):
    pass


@dataclass
class Check:
    name: str
    scope: str
    expected: Decimal
    actual: Decimal
    detail: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return self.expected == self.actual


def _parsed(expr: str) -> str:
    return f"case when {expr} ~ '{MONEY_RE}' then ({expr})::numeric end"


def run_checks(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    marts = BUILD_MARTS_SCHEMA
    with connect(settings, "transformer") as conn:
        files = conn.execute(
            "select file_id, dataset, coalesce(source_archive, source_uri), row_count, "
            "accepted_count, rejected_count from ops.ingestion_files where status = 'loaded' "
            "order by file_id"
        ).fetchall()
        for file_id, dataset, name, rows, accepted, rejected in files:
            scope = f"file {file_id} {name}"
            raw_rows = conn.execute(
                f"select count(*) from {RAW_TABLES[dataset]} where file_id = %s", (file_id,)
            ).fetchone()[0]
            stage_rows = conn.execute(
                f"select count(*) from {STAGE_TABLES[dataset]} where file_id = %s", (file_id,)
            ).fetchone()[0]
            q_rows = conn.execute(
                "select count(*) from ops.quarantine_rows where file_id = %s", (file_id,)
            ).fetchone()[0]
            checks.append(
                Check(
                    "rows: registry total = accepted + rejected",
                    scope,
                    Decimal(rows),
                    Decimal(accepted + rejected),
                )
            )
            checks.append(
                Check("rows: raw rows = registry total", scope, Decimal(rows), Decimal(raw_rows))
            )
            checks.append(
                Check(
                    "rows: raw = stage + quarantine",
                    scope,
                    Decimal(raw_rows),
                    Decimal(stage_rows + q_rows),
                )
            )
            if dataset in MONEY_COLUMNS:
                raw_table, stage_table, cols = MONEY_COLUMNS[dataset]
                for raw_col, stage_col in cols:
                    source_sum = conn.execute(
                        f"select coalesce(sum({_parsed(raw_col)}), 0) from {raw_table} "
                        "where file_id = %s",
                        (file_id,),
                    ).fetchone()[0]
                    stage_sum = conn.execute(
                        f"select coalesce(sum({stage_col}), 0) from {stage_table} where file_id = %s",
                        (file_id,),
                    ).fetchone()[0]
                    q_sum = conn.execute(
                        f"select coalesce(sum({_parsed(f'(raw_payload->>{raw_col!r})')}), 0) "
                        "from ops.quarantine_rows where file_id = %s",
                        (file_id,),
                    ).fetchone()[0]
                    checks.append(
                        Check(
                            f"money: source {raw_col} = stage + quarantine",
                            scope,
                            source_sum,
                            stage_sum + q_sum,
                            {"stage": str(stage_sum), "quarantine": str(q_sum)},
                        )
                    )

        # Stage -> warehouse, per year (claim year = segment-1 CLM_THRU_DT year).
        for kind in ("inpatient", "outpatient"):
            stage_by_year = dict(
                conn.execute(f"""
                select extract(year from p.claim_thru_date)::int, sum(s.claim_payment_amt)
                from stage.{kind}_claim_segment s
                join stage.{kind}_claim_segment p on p.claim_id = s.claim_id and p.segment = 1
                group by 1""").fetchall()
            )
            fact_by_year = dict(
                conn.execute(
                    f"select claim_year, sum(medicare_claim_payment_amt) from {marts}.fact_{kind}_claim "
                    "group by 1"
                ).fetchall()
            )
            for year in sorted(set(stage_by_year) | set(fact_by_year)):
                checks.append(
                    Check(
                        f"money: stage = fact_{kind}_claim medicare payment",
                        str(year),
                        stage_by_year.get(year, Decimal(0)),
                        fact_by_year.get(year, Decimal(0)),
                    )
                )
            stage_claims = conn.execute(
                f"select count(distinct claim_id) from stage.{kind}_claim_segment"
            ).fetchone()[0]
            facts = conn.execute(f"select count(*) from {marts}.fact_{kind}_claim").fetchone()[0]
            checks.append(
                Check(
                    f"rows: distinct staged claims = fact_{kind}_claim",
                    "all",
                    Decimal(stage_claims),
                    Decimal(facts),
                )
            )

        for stage_col in ("gross_drug_cost_amt", "patient_pay_amt"):
            stage_by_year = dict(
                conn.execute(
                    f"select extract(year from service_date)::int, sum({stage_col}) from stage.drug_event "
                    "group by 1"
                ).fetchall()
            )
            fact_by_year = dict(
                conn.execute(
                    f"select service_year, sum({stage_col}) from {marts}.fact_drug_event group by 1"
                ).fetchall()
            )
            for year in sorted(set(stage_by_year) | set(fact_by_year)):
                checks.append(
                    Check(
                        f"money: stage = fact_drug_event {stage_col}",
                        str(year),
                        stage_by_year.get(year, Decimal(0)),
                        fact_by_year.get(year, Decimal(0)),
                    )
                )
        for stage_table, mart_table in (
            ("stage.drug_event", "fact_drug_event"),
            ("stage.beneficiary_year", "dim_beneficiary_year"),
        ):
            a = conn.execute(f"select count(*) from {stage_table}").fetchone()[0]
            b = conn.execute(f"select count(*) from {marts}.{mart_table}").fetchone()[0]
            checks.append(
                Check(f"rows: {stage_table} = {mart_table}", "all", Decimal(a), Decimal(b))
            )
    return checks


def reconcile(settings: Settings, run_id: str) -> list[Check]:
    checks = run_checks(settings)
    with connect(settings, "transformer") as conn, conn.transaction():
        conn.execute("delete from ops.reconciliation_results where run_id = %s", (run_id,))
        for c in checks:
            conn.execute(
                "insert into ops.reconciliation_results (run_id, check_name, scope, expected, "
                "actual, difference, passed, detail) values (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    run_id,
                    c.name,
                    c.scope,
                    c.expected,
                    c.actual,
                    c.actual - c.expected,
                    c.passed,
                    json.dumps(c.detail) if c.detail else None,
                ),
            )
    failed = [c for c in checks if not c.passed]
    if failed:
        lines = "; ".join(
            f"{c.name} [{c.scope}] expected {c.expected} got {c.actual}" for c in failed
        )
        raise ReconciliationFailed(f"{len(failed)} of {len(checks)} checks failed: {lines}")
    return checks
