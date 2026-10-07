"""Select a reproducible beneficiary cohort and extract every matching source row."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from .acquire import sha256_file, source_entries
from .config import Settings, contracts
from .validate import ROW_NUMBER


class ContractError(RuntimeError):
    """Source columns do not match config/contracts.yaml (not retryable)."""


def _open_member(raw_dir: Path, entry: dict[str, Any]) -> io.TextIOWrapper:
    zf = zipfile.ZipFile(raw_dir / entry["archive"])
    return io.TextIOWrapper(zf.open(entry["member"]), encoding="utf-8", newline="")


def check_header(columns: list[str], dataset: str, where: str) -> None:
    expected = contracts()[dataset]["columns"]
    if list(columns) != expected:
        missing = [c for c in expected if c not in columns]
        extra = [c for c in columns if c not in expected]
        raise ContractError(f"{where}: header mismatch (missing={missing}, unexpected={extra})")


def select_cohort(settings: Settings) -> list[str]:
    """First N beneficiary IDs, sorted, across all beneficiary summary files."""
    ids: set[str] = set()
    for entry in source_entries(settings):
        if entry["dataset"] != "beneficiary_summary":
            continue
        with _open_member(settings.raw_dir, entry) as fh:
            frame = pd.read_csv(fh, dtype=str, keep_default_na=False, usecols=["DESYNPUF_ID"])
        ids.update(frame["DESYNPUF_ID"].str.strip())
    ids.discard("")
    return sorted(ids)[: settings.cohort_size]


def cohort_hash(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()


def extract_name(entry: dict[str, Any]) -> str:
    return Path(entry["archive"]).stem + ".csv"


def build_cohort(settings: Settings) -> dict[str, Any]:
    """Write cohort_ids.txt, one filtered CSV per source file and cohort.json."""
    out_dir = settings.cohort_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = select_cohort(settings)
    id_set = set(ids)
    (out_dir / "cohort_ids.txt").write_text("\n".join(ids) + "\n")

    extracts = []
    for entry in source_entries(settings):
        dataset = entry["dataset"]
        target = out_dir / extract_name(entry)
        tmp = target.with_suffix(".csv.tmp")
        source_rows = kept = 0
        with _open_member(settings.raw_dir, entry) as fh, tmp.open("w", newline="") as out:
            header = next(csv.reader([fh.readline()]))
            check_header(header, dataset, entry["archive"])
            writer = csv.writer(out, lineterminator="\n")
            writer.writerow([ROW_NUMBER, *header])
            reader = pd.read_csv(
                fh,
                dtype=str,
                keep_default_na=False,
                header=None,
                names=header,
                chunksize=settings.chunk_rows,
            )
            for chunk in reader:
                numbers = pd.RangeIndex(source_rows + 1, source_rows + len(chunk) + 1)
                source_rows += len(chunk)
                mask = chunk["DESYNPUF_ID"].isin(id_set).to_numpy()
                selected = chunk[mask]
                selected.insert(0, ROW_NUMBER, numbers[mask].astype(str))
                writer.writerows(selected.itertuples(index=False, name=None))
                kept += len(selected)
        os.replace(tmp, target)
        extracts.append(
            {
                "dataset": dataset,
                "year": entry.get("year"),
                "archive": entry["archive"],
                "member": entry["member"],
                "source_uri": entry["url"],
                "extract": target.name,
                "source_rows": source_rows,
                "rows": kept,
                "sha256": sha256_file(target),
                "size_bytes": target.stat().st_size,
            }
        )

    manifest = {
        "source": settings.source,
        "cohort_size_requested": settings.cohort_size,
        "cohort_size": len(ids),
        "cohort_sha256": cohort_hash(ids),
        "selection_rule": "first N DESYNPUF_ID values in ascending order across all beneficiary summary files",
        "extracts": extracts,
    }
    (out_dir / "cohort.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
