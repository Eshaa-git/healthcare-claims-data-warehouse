"""Command-line entry point: `claims-dw <step>`.

Exit codes: 0 success, 1 failure (data, contract or check failure; do not retry),
75 transient failure (network or database unavailable; safe to retry).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

from . import acquire, cohort, ddl, fixtures, ingest, publish, reconcile, report, runs
from .config import ConfigError, Settings, load_dotenv_if_present, load_settings
from .db import TransientError, migrate
from .dbt_steps import run_dbt

EXIT_TRANSIENT = 75
log = logging.getLogger("claims_dw")


def _run_id(args: argparse.Namespace) -> str:
    return args.run_id or os.environ.get("CLAIMS_DW_RUN_ID") or runs.new_run_id()


def cmd_check_config(settings: Settings, args) -> None:
    from .config import contracts, field_mapping, sources

    assert set(contracts()) == set(field_mapping()), "contracts and field mapping disagree"
    print(
        json.dumps(
            {
                "source": settings.source,
                "data_dir": str(settings.data_dir),
                "datasets": sorted(contracts()),
                "source_files": len(sources()["files"]),
                "warehouse": f"{settings.db.host}:{settings.db.port}/{settings.db.database}",
            }
        )
    )


def cmd_migrate(settings: Settings, args) -> None:
    applied = migrate(settings)
    print(f"migrations applied: {applied or 'none (up to date)'}")


def cmd_acquire(settings: Settings, args) -> None:
    run_id = _run_id(args)
    with runs.step(settings, run_id, "acquire", "loader") as detail:
        manifest = acquire.acquire(settings)
        detail["files"] = {f["archive"]: f["status"] for f in manifest["files"]}
    print(json.dumps(detail["files"], indent=2))


def cmd_cohort(settings: Settings, args) -> None:
    run_id = _run_id(args)
    with runs.step(settings, run_id, "cohort", "loader") as detail:
        manifest = cohort.build_cohort(settings)
        detail.update(
            cohort_size=manifest["cohort_size"],
            cohort_sha256=manifest["cohort_sha256"],
            rows={e["extract"]: e["rows"] for e in manifest["extracts"]},
        )
    print(json.dumps(detail, indent=2))


def cmd_stage(settings: Settings, args) -> None:
    run_id = _run_id(args)
    with runs.step(settings, run_id, "stage", "loader") as detail:
        results = ingest.stage_all(settings, run_id)
        detail["files"] = [r.__dict__ for r in results]
    for r in results:
        print(
            f"{r.status:8} {r.input}: rows={r.row_count} accepted={r.accepted} "
            f"rejected={r.rejected} {r.reasons or ''}"
        )


def cmd_dbt_run(settings: Settings, args) -> None:
    run_id = _run_id(args)
    with runs.step(settings, run_id, "dbt_run", "transformer"):
        run_dbt(settings, "run")


def cmd_dbt_test(settings: Settings, args) -> None:
    run_id = _run_id(args)
    with runs.step(settings, run_id, "dbt_test", "transformer"):
        run_dbt(settings, "test")


def cmd_reconcile(settings: Settings, args) -> None:
    run_id = _run_id(args)
    with runs.step(settings, run_id, "reconcile", "transformer") as detail:
        checks = reconcile.reconcile(settings, run_id)
        detail["checks"] = len(checks)
    print(f"reconciliation: {len(checks)} checks passed")


def cmd_publish(settings: Settings, args) -> None:
    run_id = _run_id(args)
    with runs.step(settings, run_id, "publish", "transformer") as detail:
        detail.update(publish.publish(settings, run_id))
    runs.finish_run(settings, run_id, "succeeded")
    print(f"published run {run_id}: {detail['tables']}")


def cmd_report(settings: Settings, args) -> None:
    kwargs = {"out_dir": Path(args.out_dir)} if args.out_dir else {}
    path = report.write_report(settings, args.run_id, **kwargs)
    print(f"wrote {path}")


def cmd_pipeline(settings: Settings, args) -> None:
    """All steps in order in one process (the Airflow DAG runs the same steps as tasks)."""
    args.run_id = _run_id(args)
    print(f"run_id={args.run_id}")
    try:
        for fn in (
            cmd_acquire,
            cmd_cohort,
            cmd_stage,
            cmd_dbt_run,
            cmd_dbt_test,
            cmd_reconcile,
            cmd_publish,
        ):
            fn(settings, args)
    except BaseException:
        runs.finish_run(settings, args.run_id, "failed", role="loader")
        raise


def cmd_finish_run(settings: Settings, args) -> None:
    if not args.run_id or args.status not in {"succeeded", "failed"}:
        raise ConfigError("finish-run needs --run-id and --status succeeded|failed")
    runs.finish_run(settings, args.run_id, args.status, role="loader")


def cmd_generate_ddl(settings: Settings | None, args) -> None:
    from .config import MIGRATIONS_DIR

    (MIGRATIONS_DIR / "002_raw_tables.sql").write_text(ddl.raw_table_ddl())
    (MIGRATIONS_DIR / "003_stage_tables.sql").write_text(ddl.stage_table_ddl())
    print("regenerated migrations/002_raw_tables.sql and 003_stage_tables.sql")


def cmd_fixture_batch(settings: Settings, args) -> None:
    writer = {"incremental": fixtures.write_incremental_batch, "bad": fixtures.write_bad_batch}
    expected = writer[args.kind](settings.incoming_dir)
    print(json.dumps(expected, indent=2))


COMMANDS: dict[str, Callable] = {
    "check-config": cmd_check_config,
    "migrate": cmd_migrate,
    "acquire": cmd_acquire,
    "cohort": cmd_cohort,
    "stage": cmd_stage,
    "dbt-run": cmd_dbt_run,
    "dbt-test": cmd_dbt_test,
    "reconcile": cmd_reconcile,
    "publish": cmd_publish,
    "report": cmd_report,
    "pipeline": cmd_pipeline,
    "finish-run": cmd_finish_run,
    "generate-ddl": cmd_generate_ddl,
    "fixture-batch": cmd_fixture_batch,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claims-dw", description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--run-id", help="run identifier shared by all steps of one pipeline run")
    parser.add_argument("--kind", choices=["incremental", "bad"], help="fixture-batch kind")
    parser.add_argument("--status", help="finish-run status: succeeded or failed")
    parser.add_argument("--out-dir", help="report output directory (default: reports/)")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    load_dotenv_if_present()
    try:
        settings = None if args.command == "generate-ddl" else load_settings()
        COMMANDS[args.command](settings, args)
    except TransientError as exc:
        log.error("transient failure: %s", exc)
        return EXIT_TRANSIENT
    except (
        ConfigError,
        ingest.InjectedFailure,
        reconcile.ReconciliationFailed,
        publish.PublishRefused,
        acquire.AcquisitionError,
        cohort.ContractError,
    ) as exc:
        log.error("%s: %s", type(exc).__name__, exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - report every other failure as non-transient
        log.exception("unexpected failure: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
