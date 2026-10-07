"""Failure handling: injected failure, killed process, and a failed reconciliation."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest

from claims_dw import acquire, cohort, fixtures, ingest, publish, reconcile
from claims_dw.dbt_steps import run_dbt

from .conftest import full_run, rows, scalar, snapshot, write_evidence

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


def file_counts(settings, file_id):
    return {
        "raw": scalar(
            settings, "select count(*) from raw.drug_events where file_id = %s", (file_id,)
        ),
        "stage": scalar(
            settings, "select count(*) from stage.drug_event where file_id = %s", (file_id,)
        ),
        "quarantine": scalar(
            settings, "select count(*) from ops.quarantine_rows where file_id = %s", (file_id,)
        ),
    }


def test_injected_failure_rolls_back_the_file_and_rerun_recovers(settings, monkeypatch):
    acquire.acquire(settings)
    cohort.build_cohort(settings)
    monkeypatch.setenv("CLAIMS_DW_FAIL_AFTER_CHUNKS", "2")
    monkeypatch.setenv("CLAIMS_DW_FAIL_DATASET", "drug_events")
    with pytest.raises(ingest.InjectedFailure):
        ingest.stage_all(settings, "rec-1")
    status = dict(rows(settings, "select dataset, status from ops.ingestion_files"))
    assert status == {
        "beneficiary_summary": "loaded",
        "inpatient_claims": "loaded",
        "outpatient_claims": "loaded",
        "drug_events": "failed",
    }
    file_id, error = rows(
        settings, "select file_id, error from ops.ingestion_files where dataset = 'drug_events'"
    )[0]
    assert "InjectedFailure" in error
    after_failure = file_counts(settings, file_id)
    assert after_failure == {"raw": 0, "stage": 0, "quarantine": 0}

    monkeypatch.delenv("CLAIMS_DW_FAIL_AFTER_CHUNKS")
    results = ingest.stage_all(settings, "rec-2")
    assert [(r.dataset, r.status) for r in results if r.status == "loaded"] == [
        ("drug_events", "loaded")
    ]
    truth_events = fixtures.generate_base()[1]["drug"]["events"]
    after_retry = file_counts(settings, file_id)
    assert after_retry["stage"] == truth_events
    attempts = scalar(
        settings, "select attempts from ops.ingestion_files where file_id = %s", (file_id,)
    )
    assert attempts == 2
    write_evidence(
        "injected_failure_recovery",
        {
            "failed_file": "drug_events",
            "error": error,
            "rows_after_failure": after_failure,
            "rows_after_rerun": after_retry,
            "attempts": attempts,
        },
    )


def test_killed_loader_leaves_no_partial_rows(settings):
    fixtures.write_incremental_batch(settings.incoming_dir)
    env = {
        **os.environ,
        "WAREHOUSE_HOST": settings.db.host,
        "WAREHOUSE_PORT": str(settings.db.port),
        "WAREHOUSE_DB": settings.db.database,
        "DATA_DIR": str(settings.data_dir),
        "CLAIMS_DW_SOURCE": "fixture",
        "CHUNK_ROWS": "1",
        "CLAIMS_DW_PAUSE_AFTER_CHUNKS": "2",
        "CLAIMS_DW_PAUSE_SECONDS": "120",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "claims_dw.cli", "stage", "--run-id", "rec-kill"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    uri = "incoming://inpatient_claims__batch_002.csv"
    deadline = time.time() + 60
    while time.time() < deadline:
        found = rows(
            settings,
            "select file_id, status from ops.ingestion_files where source_uri = %s",
            (uri,),
        )
        in_txn = scalar(
            settings,
            "select count(*) from pg_stat_activity where application_name = "
            "'claims-dw-loader' and state = 'idle in transaction'",
        )
        if found and found[0][1] == "loading" and in_txn:
            break
        time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail("loader never reached the paused, mid-transaction state")
    file_id = found[0][0]
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)
    deadline = time.time() + 30
    while (
        scalar(
            settings,
            "select count(*) from pg_stat_activity where application_name = 'claims-dw-loader'",
        )
        and time.time() < deadline
    ):
        time.sleep(0.2)
    status = scalar(
        settings, "select status from ops.ingestion_files where file_id = %s", (file_id,)
    )
    leftover = {
        "raw": scalar(
            settings, "select count(*) from raw.inpatient_claims where file_id = %s", (file_id,)
        ),
        "stage": scalar(
            settings,
            "select count(*) from stage.inpatient_claim_segment where file_id = %s",
            (file_id,),
        ),
    }
    assert status == "loading" and leftover == {"raw": 0, "stage": 0}

    results = ingest.stage_all(settings, "rec-kill-retry")
    retried = [r for r in results if r.status == "loaded"]
    assert [(r.input, r.accepted) for r in retried] == [("inpatient_claims__batch_002.csv", 3)]
    write_evidence(
        "killed_loader_recovery",
        {
            "signal": "SIGKILL after 2 of 3 chunks",
            "registry_status_after_kill": status,
            "committed_rows_after_kill": leftover,
            "rerun": [(r.input, r.status, r.accepted) for r in retried],
        },
    )


def test_failed_reconciliation_keeps_last_good_marts(settings):
    full_run(settings, "rec-good")
    good = snapshot(settings)
    run_dbt(settings, "run", "--quiet")
    with __import__("claims_dw.db", fromlist=["connect"]).connect(settings, "admin") as conn:
        conn.execute(
            "update dw_build_marts.fact_inpatient_claim set medicare_claim_payment_amt = "
            "medicare_claim_payment_amt + 0.01 where claim_id = (select min(claim_id) from "
            "dw_build_marts.fact_inpatient_claim)"
        )
        conn.commit()
    with pytest.raises(reconcile.ReconciliationFailed) as failure:
        reconcile.reconcile(settings, "rec-tampered")
    with pytest.raises(publish.PublishRefused):
        publish.publish(settings, "rec-tampered")
    assert snapshot(settings) == good
    assert (
        scalar(settings, "select run_id from marts.publication_info", role="dashboard")
        == "rec-good"
    )
    write_evidence(
        "failed_reconciliation_blocks_publish",
        {
            "tampering": "+0.01 on one inpatient fact in the build schema",
            "reconciliation_error": str(failure.value)[:500],
            "published_run_still": "rec-good",
        },
    )
