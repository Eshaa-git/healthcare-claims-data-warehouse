"""Machine-readable run metrics (reports/metrics.json) and a short Markdown summary.

Everything here is read back from the warehouse and manifests; nothing is estimated.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from importlib import metadata
from pathlib import Path
from typing import Any

from .config import PREVIOUS_SCHEMA, PUBLISHED_SCHEMA, REPORTS_DIR, Settings
from .db import connect
from .runs import git_commit

LIMITATIONS = [
    "DE-SynPUF is fully synthetic; CMS states analyses of it 'will be misleading and often incorrect' "
    "for inferences about Medicare beneficiaries, providers or the program. Results here demonstrate "
    "the pipeline, not Medicare utilization or spending.",
    "The cohort is the first N beneficiary IDs in sort order, not a random sample.",
    "Medicare claim payment (CLM_PMT_AMT) covers inpatient and outpatient institutional claims only; "
    "carrier (physician) claims are not loaded, so payments are not total cost of care.",
    "Admissions per 1,000 beneficiary-years uses beneficiary summary records as the denominator, "
    "without adjusting for partial-year enrollment, HMO months or death.",
    "Single-node local deployment with Docker Compose; no high availability is claimed.",
]


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(type(obj))


def _rows(conn, query: str, params: tuple = ()) -> list[dict[str, Any]]:
    cur = conn.execute(query, params)
    names = [d.name for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def _host() -> dict[str, Any]:
    info: dict[str, Any] = {
        "os": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "inside_container": Path("/.dockerenv").exists(),
    }
    try:
        pages = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        info["memory_gb"] = round(pages / 1024**3, 1)
    except (ValueError, OSError, AttributeError):
        pass
    host_label = os.environ.get("CLAIMS_DW_HOST_LABEL")
    if host_label:
        info["docker_host"] = host_label
    return info


def _mart_snapshot(conn, schema: str) -> dict[str, Any] | None:
    exists = conn.execute("select 1 from pg_namespace where nspname = %s", (schema,)).fetchone()
    if not exists:
        return None
    snap: dict[str, Any] = {}
    for table, amount in [
        ("fact_inpatient_claim", "medicare_claim_payment_amt"),
        ("fact_outpatient_claim", "medicare_claim_payment_amt"),
        ("fact_drug_event", "gross_drug_cost_amt"),
        ("dim_beneficiary_year", None),
    ]:
        sum_expr = f"sum({amount})" if amount else "null"
        count, total = conn.execute(f"select count(*), {sum_expr} from {schema}.{table}").fetchone()
        snap[table] = {"rows": count, "amount_sum": total}
    return snap


def build_report(settings: Settings, run_id: str | None = None) -> dict[str, Any]:
    with connect(settings, "transformer") as conn:
        if run_id is None:
            row = conn.execute(
                "select run_id from ops.pipeline_runs order by started_at desc limit 1"
            ).fetchone()
            if row is None:
                raise RuntimeError("no pipeline runs recorded")
            run_id = row[0]
        run = _rows(conn, "select * from ops.pipeline_runs where run_id = %s", (run_id,))[0]
        steps = _rows(
            conn,
            "select step, attempt, status, duration_seconds, started_at, finished_at, "
            "detail from ops.run_steps where run_id = %s order by started_at",
            (run_id,),
        )
        files = _rows(
            conn,
            "select file_id, dataset, source_year, coalesce(source_archive, source_uri) "
            "as input, sha256, status, attempts, row_count, accepted_count, "
            "rejected_count, run_id as loaded_by_run, error "
            "from ops.ingestion_files order by file_id",
        )
        reasons = _rows(
            conn,
            "select dataset, reason_codes[1] as reason, count(*) as rows "
            "from ops.quarantine_rows group by 1, 2 order by 1, 2",
        )
        recon = _rows(
            conn,
            "select check_name, scope, expected, actual, passed "
            "from ops.reconciliation_results where run_id = %s "
            "order by check_name, scope",
            (run_id,),
        )
        publication = _rows(conn, "select * from ops.publications where run_id = %s", (run_id,))
        server_version = conn.execute("show server_version").fetchone()[0]
        published = _mart_snapshot(conn, PUBLISHED_SCHEMA)
        previous = _mart_snapshot(conn, PREVIOUS_SCHEMA)
        marts: dict[str, Any] = {}
        if published:
            marts["utilization_by_year"] = _rows(
                conn,
                f"select * from {PUBLISHED_SCHEMA}.mart_inpatient_utilization_yearly order by year",
            )
            marts["claim_payments_by_year"] = _rows(
                conn,
                f"""
                select extract(year from month_start)::int as year, claim_type,
                       sum(claim_count)::bigint as claims, sum(medicare_claim_payment_amt) as medicare_claim_payment_amt,
                       sum(negative_payment_claims)::bigint as negative_payment_claims
                from {PUBLISHED_SCHEMA}.mart_monthly_claim_payments group by 1, 2 order by 1, 2""",
            )
            marts["drug_events_by_year"] = _rows(
                conn,
                f"""
                select extract(year from month_start)::int as year, sum(drug_event_count)::bigint as events,
                       sum(gross_drug_cost_amt) as gross_drug_cost_amt, sum(patient_pay_amt) as patient_pay_amt
                from {PUBLISHED_SCHEMA}.mart_monthly_drug_events group by 1 order by 1""",
            )
            marts["beneficiary_years"] = _rows(
                conn,
                f"""
                select year, count(*) as beneficiary_years from {PUBLISHED_SCHEMA}.dim_beneficiary_year
                group by 1 order by 1""",
            )

    manifests: dict[str, Any] = {}
    for name in ("sources.json",):
        path = settings.manifest_dir / name
        if path.exists():
            manifests[name] = json.loads(path.read_text())
    cohort_path = settings.cohort_dir / "cohort.json"
    cohort = json.loads(cohort_path.read_text()) if cohort_path.exists() else None

    failed_checks = [f"{r['check_name']} [{r['scope']}]" for r in recon if not r["passed"]]
    failed_steps = [f"{s['step']} attempt {s['attempt']}" for s in steps if s["status"] == "failed"]
    report = {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "run": run,
        "environment": {
            "host": _host(),
            "postgres_server_version": server_version,
            "packages": {
                p: _version(p)
                for p in [
                    "claims-dw",
                    "pandas",
                    "sqlalchemy",
                    "psycopg",
                    "dbt-core",
                    "dbt-postgres",
                    "streamlit",
                ]
            },
            "airflow_version": os.environ.get("AIRFLOW_VERSION"),
        },
        "source": {
            "kind": settings.source,
            "manifest": manifests.get("sources.json"),
            "cohort": None
            if cohort is None
            else {
                k: cohort[k]
                for k in ("cohort_size_requested", "cohort_size", "cohort_sha256", "selection_rule")
            }
            | {
                "extracts": [
                    {
                        k: e[k]
                        for k in ("extract", "dataset", "year", "source_rows", "rows", "sha256")
                    }
                    for e in cohort["extracts"]
                ]
            },
        },
        "ingestion_files": files,
        "quarantine_by_reason": reasons,
        "step_timings": steps,
        "reconciliation": {
            "checks": len(recon),
            "passed": sum(r["passed"] for r in recon),
            "results": recon,
        },
        "publication": publication[0] if publication else None,
        "published_marts": published,
        "previous_marts": previous,
        "published_equals_previous": None if previous is None else published == previous,
        "marts": marts,
        "failed_checks": failed_checks,
        "failed_steps": failed_steps,
        "limitations": LIMITATIONS,
    }
    return json.loads(json.dumps(report, default=_json_default))


def write_report(
    settings: Settings, run_id: str | None = None, out_dir: Path = REPORTS_DIR
) -> Path:
    report = build_report(settings, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "metrics.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    (out_dir / "summary.md").write_text(render_summary(report))
    return path


def render_summary(r: dict[str, Any]) -> str:
    lines = [
        f"# Run {r['run_id']}",
        "",
        f"- Status: {r['run']['status']}; source: {r['source']['kind']}; commit: {r['git_commit']}",
        f"- Reconciliation: {r['reconciliation']['passed']}/{r['reconciliation']['checks']} checks passed",
        "",
    ]
    if r["source"]["cohort"]:
        c = r["source"]["cohort"]
        lines.append(
            f"Cohort: {c['cohort_size']} beneficiaries (sha256 {c['cohort_sha256'][:12]}…)"
        )
        lines.append("")
    lines += ["| Step | Attempt | Status | Seconds |", "|---|---|---|---|"]
    lines += [
        f"| {s['step']} | {s['attempt']} | {s['status']} | {s['duration_seconds']} |"
        for s in r["step_timings"]
    ]
    lines += ["", "| File | Rows | Accepted | Quarantined | Attempts |", "|---|---|---|---|---|"]
    lines += [
        f"| {f['input']} | {f['row_count']} | {f['accepted_count']} | {f['rejected_count']} | "
        f"{f['attempts']} |"
        for f in r["ingestion_files"]
    ]
    if r["quarantine_by_reason"]:
        lines += ["", "| Dataset | Reason | Rows |", "|---|---|---|"]
        lines += [
            f"| {q['dataset']} | {q['reason']} | {q['rows']} |" for q in r["quarantine_by_reason"]
        ]
    if r["failed_checks"] or r["failed_steps"]:
        lines += ["", "Failed: " + "; ".join(r["failed_checks"] + r["failed_steps"])]
    return "\n".join(lines) + "\n"


def server_info() -> str:  # pragma: no cover - convenience for debugging
    return subprocess.run(["uname", "-a"], capture_output=True, text=True).stdout
