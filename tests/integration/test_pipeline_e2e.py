"""End-to-end on the deterministic fixture: results must equal fixture truth, then a rerun,
an incremental batch and a batch of invalid rows are applied in order."""

from __future__ import annotations

import json
from decimal import Decimal

import psycopg
import pytest

from claims_dw import acquire, cohort, fixtures
from claims_dw.db import connect

from .conftest import full_run, money, rows, scalar, snapshot, write_evidence

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


def test_01_fixture_run_matches_truth(settings):
    acquire.acquire(settings)
    cohort.build_cohort(settings)
    results = full_run(settings, "e2e-1")
    truth = json.loads((settings.raw_dir / "fixture_truth.json").read_text())

    assert {r.status for r in results} == {"loaded"}
    assert (
        dict(
            rows(settings, "select year::text, count(*) from marts.dim_beneficiary_year group by 1")
        )
        == truth["beneficiary_years"]
    )
    ip = dict(
        rows(
            settings,
            "select claim_year::text, sum(medicare_claim_payment_amt) from marts.fact_inpatient_claim group by 1",
        )
    )
    assert ip == {y: money(v) for y, v in truth["inpatient"]["payment_by_year"].items()}
    assert (
        scalar(settings, "select count(*) from marts.fact_inpatient_claim")
        == truth["inpatient"]["claims"]
    )
    assert (
        scalar(settings, "select sum(length_of_stay_days) from marts.fact_inpatient_claim")
        == truth["inpatient"]["los_days_by_year"]["2008"]
    )
    op = dict(
        rows(
            settings,
            "select claim_year::text, sum(medicare_claim_payment_amt) from marts.fact_outpatient_claim group by 1",
        )
    )
    assert op == {y: money(v) for y, v in truth["outpatient"]["payment_by_year"].items()}
    assert (
        scalar(settings, "select count(*) from marts.fact_outpatient_claim")
        == truth["outpatient"]["claims"]
    )
    drug = dict(
        rows(
            settings,
            "select service_year::text, sum(gross_drug_cost_amt) from marts.fact_drug_event group by 1",
        )
    )
    assert drug == {y: money(v) for y, v in truth["drug"]["gross_cost_by_year"].items()}
    assert scalar(settings, "select count(*) from marts.fact_drug_event") == truth["drug"]["events"]
    # the single orphan continuation segment is quarantined, not dropped
    assert rows(settings, "select dataset, reason_codes from ops.quarantine_rows") == [
        ("outpatient_claims", ["orphan_segment"])
    ]
    # admissions per 1,000 beneficiary-years: 10 stays / 30 beneficiaries in 2008
    assert scalar(
        settings,
        "select admissions_per_1000_beneficiary_years from marts.mart_inpatient_utilization_yearly where year = 2008",
    ) == Decimal("333.33")
    # the negative payment claim is kept and counted
    assert (
        scalar(
            settings, "select sum(negative_payment_claims) from marts.mart_monthly_claim_payments"
        )
        == 1
    )


def test_02_rerun_is_idempotent(settings):
    before = snapshot(settings)
    results = full_run(settings, "e2e-2")
    after = snapshot(settings)
    assert {r.status for r in results} == {"skipped"}
    assert after == before
    assert snapshot(settings, "marts_previous") == before
    write_evidence(
        "rerun_idempotency",
        {
            "second_run_file_statuses": [r.status for r in results],
            "published_marts_unchanged": after == before,
            "fact_counts_and_sums": {k: v for k, v in after.items() if k != "monthly_payments"},
        },
    )


def test_03_incremental_batch_loads_only_new_file(settings):
    expected = fixtures.write_incremental_batch(settings.incoming_dir)
    before_ip = scalar(settings, "select count(*) from marts.fact_inpatient_claim")
    before_2009 = scalar(
        settings,
        "select coalesce(sum(medicare_claim_payment_amt), 0) from marts.fact_inpatient_claim where claim_year = 2009",
    )
    results = full_run(settings, "e2e-3")
    loaded = [r for r in results if r.status == "loaded"]
    assert [(r.input, r.accepted, r.rejected) for r in loaded] == [
        ("inpatient_claims__batch_002.csv", 3, 0)
    ]
    assert (
        scalar(settings, "select count(*) from marts.fact_inpatient_claim")
        == before_ip + expected["claims"]
    )
    after_2009 = scalar(
        settings,
        "select sum(medicare_claim_payment_amt) from marts.fact_inpatient_claim where claim_year = 2009",
    )
    assert after_2009 - before_2009 == money(expected["payment_2009"])


def test_04_invalid_rows_are_quarantined_with_reason_codes(settings):
    expected = fixtures.write_bad_batch(settings.incoming_dir)
    before_2009 = scalar(
        settings,
        "select sum(medicare_claim_payment_amt) from marts.fact_outpatient_claim where claim_year = 2009",
    )
    results = full_run(settings, "e2e-4")  # reconciliation must still balance
    by_input = {r.input: r for r in results if r.status == "loaded"}
    evidence = {}
    for name, exp in expected.items():
        r = by_input[name]
        assert (r.row_count, r.accepted, r.rejected) == (
            exp["rows"],
            exp["accepted"],
            exp["rows"] - exp["accepted"],
        )
        got = dict(
            rows(
                settings,
                "select q.source_row_number, q.reason_codes[1] from ops.quarantine_rows q "
                "join ops.ingestion_files f using (file_id) where f.source_uri = %s",
                (f"incoming://{name}",),
            )
        )
        assert got == {int(k): v for k, v in exp["reasons"].items()}
        evidence[name] = {"rows": r.row_count, "accepted": r.accepted, "quarantined": got}
    after_2009 = scalar(
        settings,
        "select sum(medicare_claim_payment_amt) from marts.fact_outpatient_claim where claim_year = 2009",
    )
    assert after_2009 - before_2009 == Decimal("40.00")
    write_evidence("quarantine_rules", evidence)


def test_05_dashboard_role_can_read_only_published_marts(settings):
    assert scalar(settings, "select count(*) from marts.fact_inpatient_claim", role="dashboard") > 0
    for table in (
        "stage.inpatient_claim_segment",
        "ops.quarantine_rows",
        "raw.drug_events",
        "dw_build_staging.stg_drug_event",
    ):
        with (
            connect(settings, "dashboard") as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(f"select 1 from {table} limit 1")
