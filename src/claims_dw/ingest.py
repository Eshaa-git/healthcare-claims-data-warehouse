"""Register, load and stage input files.

Commit boundaries
-----------------
1. Registration commits on its own: the file is recorded as `loading` (or skipped when the
   same checksum already `loaded`).
2. Everything else for that file happens in ONE transaction: raw rows (COPY), typed rows into a
   temporary table, row-level rejects into quarantine, set-based checks, promotion into stage,
   and the registry update to `loaded`. If anything fails or the process dies, PostgreSQL rolls
   the transaction back, the registry row stays `loading`/`failed`, and a rerun loads the file
   from scratch. Accepted data is never half-written.
"""

from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from psycopg import sql

from .acquire import dataset_version, sha256_file
from .cohort import ContractError, check_header
from .config import Settings, contracts, field_mapping
from .db import connect
from .ddl import RAW_TABLES, stage_columns, stage_key
from .validate import ROW_NUMBER, transform_chunk

LOAD_ORDER = ["beneficiary_summary", "inpatient_claims", "outpatient_claims", "drug_events"]
LINEAGE = ["file_id", "source_row_number", "row_hash", "run_id"]


class InjectedFailure(RuntimeError):
    """Raised by the failure-injection hook used in recovery tests."""


class LoadReconciliationError(RuntimeError):
    """Source rows != accepted + rejected for a file."""


@dataclass
class InputFile:
    dataset: str
    path: Path
    source_uri: str
    sha256: str
    size_bytes: int
    year: int | None = None
    archive: str | None = None
    member: str | None = None

    @property
    def source_file(self) -> str:
        return f"{self.archive}!{self.member}" if self.archive else self.path.name


@dataclass
class LoadResult:
    dataset: str
    input: str
    status: str
    file_id: int | None = None
    row_count: int = 0
    accepted: int = 0
    rejected: int = 0
    reasons: dict[str, int] = field(default_factory=dict)


def discover_inputs(settings: Settings) -> list[InputFile]:
    """Cohort extracts from cohort.json, then incoming batches named <dataset>__<label>.csv."""
    manifest_path = settings.cohort_dir / "cohort.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"{manifest_path} not found; run the cohort step first")
    manifest = json.loads(manifest_path.read_text())
    inputs = [
        InputFile(
            dataset=e["dataset"],
            path=settings.cohort_dir / e["extract"],
            source_uri=e["source_uri"],
            sha256=e["sha256"],
            size_bytes=e["size_bytes"],
            year=e["year"],
            archive=e["archive"],
            member=e["member"],
        )
        for e in manifest["extracts"]
    ]
    if settings.incoming_dir.exists():
        for path in sorted(settings.incoming_dir.glob("*__*.csv")):
            dataset = path.name.split("__", 1)[0]
            if dataset not in LOAD_ORDER or dataset == "beneficiary_summary":
                raise ContractError(f"{path.name}: unsupported incoming dataset {dataset!r}")
            inputs.append(
                InputFile(
                    dataset=dataset,
                    path=path,
                    source_uri=f"incoming://{path.name}",
                    sha256=sha256_file(path),
                    size_bytes=path.stat().st_size,
                )
            )
    return sorted(inputs, key=lambda i: (LOAD_ORDER.index(i.dataset), i.year or 0, i.source_uri))


def _register(conn: psycopg.Connection, inp: InputFile, run_id: str, version: str) -> int | None:
    row = conn.execute(
        """
        insert into ops.ingestion_files (dataset, source_year, dataset_version, source_uri,
            source_archive, source_member, input_path, sha256, size_bytes, run_id, status)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'loading')
        on conflict (sha256, dataset_version) do update
            set status = 'loading', run_id = excluded.run_id, input_path = excluded.input_path,
                attempts = ops.ingestion_files.attempts + 1, started_at = now(),
                finished_at = null, error = null
            where ops.ingestion_files.status <> 'loaded'
        returning file_id
        """,
        (
            inp.dataset,
            inp.year,
            version,
            inp.source_uri,
            inp.archive,
            inp.member,
            str(inp.path),
            inp.sha256,
            inp.size_bytes,
            run_id,
        ),
    ).fetchone()
    conn.commit()
    return row[0] if row else None


def _mark_failed(settings: Settings, file_id: int, error: BaseException) -> None:
    with connect(settings, "loader") as conn:
        conn.execute(
            "update ops.ingestion_files set status = 'failed', error = %s, finished_at = now() "
            "where file_id = %s and status = 'loading'",
            (f"{type(error).__name__}: {error}"[:2000], file_id),
        )
        conn.commit()


def _copy_rows(conn: psycopg.Connection, table: str, columns: list[str], rows: Any) -> None:
    stmt = sql.SQL("copy {} ({}) from stdin").format(
        sql.SQL(table), sql.SQL(", ").join(map(sql.Identifier, columns))
    )
    with conn.cursor().copy(stmt) as copy:
        for row in rows:
            copy.write_row(row)


def _quarantine_python_rejects(conn, chunk, rejected, file_id, dataset, run_id, columns) -> None:
    if not rejected:
        return
    by_number = chunk.set_index(chunk[ROW_NUMBER].astype("int64"))
    rows = []
    for number, reasons in rejected.items():
        payload = {c.lower(): by_number.at[number, c] for c in columns}
        rows.append((file_id, number, dataset, reasons, json.dumps(payload), run_id))
    _copy_rows(
        conn,
        "ops.quarantine_rows",
        ["file_id", "source_row_number", "dataset", "reason_codes", "raw_payload", "run_id"],
        rows,
    )


def _quarantine_where(conn, dataset, file_id, run_id, delete_sql: str, params: dict) -> int:
    """Move rows matched by `delete_sql` (DELETE ... RETURNING source_row_number, reason) to quarantine."""
    raw_table = RAW_TABLES[dataset]
    stmt = f"""
        with rejected as ({delete_sql})
        insert into ops.quarantine_rows
            (file_id, source_row_number, dataset, reason_codes, raw_payload, run_id)
        select %(file_id)s, r.source_row_number, %(dataset)s, array[r.reason],
               to_jsonb(raw) - 'file_id' - 'source_row_number' - 'run_id' - 'source_file' - 'loaded_at',
               %(run_id)s
        from rejected r
        join {raw_table} raw on raw.file_id = %(file_id)s and raw.source_row_number = r.source_row_number
    """
    cur = conn.execute(stmt, {"file_id": file_id, "dataset": dataset, "run_id": run_id, **params})
    return cur.rowcount


def _set_based_checks(conn: psycopg.Connection, dataset: str, file_id: int, run_id: str) -> None:
    stage_table = field_mapping()[dataset]["stage_table"]
    key = stage_key(dataset)
    key_cols = ", ".join(key)
    key_match = " and ".join(f"s.{k} = t.{k}" for k in key)

    # 1. duplicate natural key inside this file: keep the first row, quarantine the rest
    _quarantine_where(
        conn,
        dataset,
        file_id,
        run_id,
        f"""
        delete from tmp_stage t
        using (select source_row_number,
                      row_number() over w as rn,
                      first_value(row_hash) over w as first_hash
               from tmp_stage window w as (partition by {key_cols} order by source_row_number)) d
        where t.source_row_number = d.source_row_number and d.rn > 1
        returning t.source_row_number,
                  case when t.row_hash = d.first_hash then 'duplicate_key_in_file:exact'
                       else 'duplicate_key_in_file:conflict' end as reason
    """,
        {},
    )

    # 2. natural key already accepted from an earlier file
    _quarantine_where(
        conn,
        dataset,
        file_id,
        run_id,
        f"""
        delete from tmp_stage t using {stage_table} s
        where {key_match}
        returning t.source_row_number,
                  case when t.row_hash = s.row_hash then 'duplicate_key_existing:exact'
                       else 'duplicate_key_existing:conflict' end as reason
    """,
        {},
    )

    if dataset in {"inpatient_claims", "outpatient_claims"}:
        # 3. continuation segment without a segment 1 for the same claim (no dates to place it)
        _quarantine_where(
            conn,
            dataset,
            file_id,
            run_id,
            f"""
            delete from tmp_stage t
            where t.segment > 1
              and not exists (select 1 from tmp_stage p where p.claim_id = t.claim_id and p.segment = 1)
              and not exists (select 1 from {stage_table} p where p.claim_id = t.claim_id and p.segment = 1)
            returning t.source_row_number, 'orphan_segment' as reason
        """,
            {},
        )
        # 4. claim year (segment 1 CLM_THRU_DT) must have a beneficiary-year record
        _quarantine_where(
            conn,
            dataset,
            file_id,
            run_id,
            f"""
            delete from tmp_stage t
            where not exists (
                select 1
                from (select claim_id, beneficiary_id, claim_thru_date from tmp_stage where segment = 1
                      union all
                      select claim_id, beneficiary_id, claim_thru_date from {stage_table} where segment = 1)
                     p
                join stage.beneficiary_year b
                  on b.beneficiary_id = p.beneficiary_id
                 and b.year = extract(year from p.claim_thru_date)::int
                where p.claim_id = t.claim_id)
            returning t.source_row_number, 'no_beneficiary_year' as reason
        """,
            {},
        )
    elif dataset == "drug_events":
        _quarantine_where(
            conn,
            dataset,
            file_id,
            run_id,
            """
            delete from tmp_stage t
            where not exists (select 1 from stage.beneficiary_year b
                              where b.beneficiary_id = t.beneficiary_id
                                and b.year = extract(year from t.service_date)::int)
            returning t.source_row_number, 'no_beneficiary_year' as reason
        """,
            {},
        )


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    return int(value) if value else None


def _fail_after_chunks(dataset: str) -> int | None:
    value = os.environ.get("CLAIMS_DW_FAIL_AFTER_CHUNKS")
    target = os.environ.get("CLAIMS_DW_FAIL_DATASET")
    if value and (not target or target == dataset):
        return int(value)
    return None


def load_file(settings: Settings, inp: InputFile, run_id: str) -> LoadResult:
    dataset = inp.dataset
    columns = contracts()[dataset]["columns"]
    stage_table = field_mapping()[dataset]["stage_table"]
    raw_table = RAW_TABLES[dataset]
    stage_cols = stage_columns(dataset)
    fail_after = _fail_after_chunks(dataset)
    pause_after = _env_int("CLAIMS_DW_PAUSE_AFTER_CHUNKS")

    with inp.path.open(newline="") as fh:
        header = next(csv.reader(fh))
    if header[:1] != [ROW_NUMBER]:
        raise ContractError(f"{inp.path.name}: first column must be {ROW_NUMBER}")
    check_header(header[1:], dataset, inp.path.name)

    with connect(settings, "loader") as conn:
        file_id = _register(conn, inp, run_id, dataset_version(settings))
    if file_id is None:
        return LoadResult(dataset, inp.path.name, "skipped")

    try:
        with connect(settings, "loader") as conn, conn.transaction():
            conn.execute(
                f"create temp table tmp_stage (like {stage_table} including defaults) on commit drop"
            )
            total = 0
            reader = pd.read_csv(
                inp.path, dtype=str, keep_default_na=False, chunksize=settings.chunk_rows
            )
            for i, chunk in enumerate(reader):
                total += len(chunk)
                _copy_rows(
                    conn,
                    raw_table,
                    [
                        "file_id",
                        "source_row_number",
                        "run_id",
                        "source_file",
                        *[c.lower() for c in columns],
                    ],
                    (
                        (file_id, int(r[0]), run_id, inp.source_file, *r[1:])
                        for r in chunk[[ROW_NUMBER, *columns]].itertuples(index=False, name=None)
                    ),
                )
                result = transform_chunk(chunk, dataset, columns, inp.year)
                staged = result.staged
                _copy_rows(
                    conn,
                    "tmp_stage",
                    [*stage_cols, "source_row_number", "row_hash", "file_id", "run_id"],
                    (
                        (*r, file_id, run_id)
                        for r in staged[[*stage_cols, "source_row_number", "row_hash"]].itertuples(
                            index=False, name=None
                        )
                    ),
                )
                _quarantine_python_rejects(
                    conn, chunk, result.rejected, file_id, dataset, run_id, columns
                )
                if fail_after is not None and i + 1 >= fail_after:
                    raise InjectedFailure(f"injected failure after chunk {i + 1}")
                if pause_after is not None and i + 1 == pause_after:
                    # recovery tests kill the process here, mid-transaction
                    time.sleep(float(os.environ.get("CLAIMS_DW_PAUSE_SECONDS", "300")))

            _set_based_checks(conn, dataset, file_id, run_id)
            accepted = conn.execute(
                f"insert into {stage_table} ({', '.join(stage_cols)}, {', '.join(LINEAGE)}) "
                f"select {', '.join(stage_cols)}, {', '.join(LINEAGE)} from tmp_stage"
            ).rowcount
            reasons = dict(
                conn.execute(
                    "select reason_codes[1], count(*) from ops.quarantine_rows "
                    "where file_id = %s group by 1 order by 1",
                    (file_id,),
                ).fetchall()
            )
            rejected = sum(reasons.values())
            if total != accepted + rejected:
                raise LoadReconciliationError(
                    f"{inp.path.name}: {total} rows != {accepted} accepted + {rejected} rejected"
                )
            conn.execute(
                "update ops.ingestion_files set status = 'loaded', row_count = %s, "
                "accepted_count = %s, rejected_count = %s, finished_at = now() where file_id = %s",
                (total, accepted, rejected, file_id),
            )
    except BaseException as exc:
        _mark_failed(settings, file_id, exc)
        raise
    return LoadResult(dataset, inp.path.name, "loaded", file_id, total, accepted, rejected, reasons)


def stage_all(settings: Settings, run_id: str) -> list[LoadResult]:
    return [load_file(settings, inp, run_id) for inp in discover_inputs(settings)]
