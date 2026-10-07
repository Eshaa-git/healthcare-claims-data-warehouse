"""Row-level validation and typing of source rows, driven by config/field_mapping.yaml.

Rules that need other rows or tables (duplicate keys, orphan claim segments, a matching
beneficiary-year) run later in SQL; see ingest.py.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import pandas as pd

from .config import field_mapping

DATE_RE = r"\d{8}"
MONEY_RE = r"-?\d+(?:\.\d{1,2})?"
INTEGER_RE = r"-?\d+"
DECIMAL_RE = r"-?\d+(?:\.\d+)?"
ROW_NUMBER = "_source_row_number"


@dataclass
class ChunkResult:
    staged: pd.DataFrame
    """Stage columns plus source_row_number and row_hash, values as str or None."""
    rejected: dict[int, list[str]] = field(default_factory=dict)
    """source_row_number -> reason codes, in rule order."""


def row_hashes(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    """SHA-256 of the row's source values joined by the unit separator."""
    joined = df[columns].astype(str).agg("\x1f".join, axis=1)
    return joined.map(lambda s: hashlib.sha256(s.encode()).hexdigest())


def transform_chunk(
    df: pd.DataFrame, dataset: str, source_columns: list[str], year: int | None = None
) -> ChunkResult:
    """Validate and type one chunk of source rows (all values are strings)."""
    spec = field_mapping()[dataset]
    row_numbers = df[ROW_NUMBER].astype("int64")
    reasons: dict[int, list[str]] = {}

    def flag(mask: pd.Series, code: str) -> None:
        for rn in row_numbers[mask.fillna(False).astype(bool)]:
            reasons.setdefault(int(rn), []).append(code)

    out: dict[str, pd.Series] = {}
    is_segment_1 = (
        df["SEGMENT"].str.strip() == "1" if "SEGMENT" in df else pd.Series(True, index=df.index)
    )
    for f in spec["fields"]:
        src, target, kind = f["source"], f["target"], f["type"]
        s = df[src].astype(str).str.strip()
        empty = s == ""
        if f["nulls"] == "reject":
            flag(empty, f"missing_required:{src}")
        elif f["nulls"] == "reject_segment_1":
            flag(empty & is_segment_1, f"missing_required:{src}")

        if kind == "date":
            shaped = s.where(s.str.fullmatch(DATE_RE), None)
            parsed = pd.to_datetime(shaped, format="%Y%m%d", errors="coerce")
            valid = parsed.notna()
            flag(~empty & ~valid, f"invalid_date:{src}")
            value = parsed.dt.strftime("%Y-%m-%d")
        elif kind in {"money", "integer", "decimal"}:
            pattern = {"money": MONEY_RE, "integer": INTEGER_RE, "decimal": DECIMAL_RE}[kind]
            code = {
                "money": "invalid_amount",
                "integer": "invalid_integer",
                "decimal": "invalid_decimal",
            }
            valid = s.str.fullmatch(pattern)
            flag(~empty & ~valid, f"{code[kind]}:{src}")
            value = s
        elif kind in {"flag_1yes_2no", "esrd", "sex"}:
            allowed = {
                "flag_1yes_2no": {"1": "true", "2": "false"},
                "esrd": {"Y": "true", "0": "false"},
                "sex": {"1": "1", "2": "2"},
            }[kind]
            valid = s.isin(list(allowed))
            flag(~empty & ~valid, f"invalid_code:{src}")
            value = s.map(allowed)
        elif kind == "text":
            valid = pd.Series(True, index=df.index)
            value = s
        else:
            raise ValueError(f"unknown field type {kind!r} for {dataset}.{src}")
        out[target] = value.where(~empty & valid, None)

    staged = pd.DataFrame(out, index=df.index)

    if "segment" in staged:
        seg = pd.to_numeric(staged["segment"], errors="coerce")
        flag(seg.notna() & (seg < 1), "invalid_code:SEGMENT")
    if {"claim_from_date", "claim_thru_date"} <= set(staged):
        both = staged["claim_from_date"].notna() & staged["claim_thru_date"].notna()
        flag(both & (staged["claim_thru_date"] < staged["claim_from_date"]), "thru_before_from")
    if {"admission_date", "discharge_date"} <= set(staged):
        both = staged["admission_date"].notna() & staged["discharge_date"].notna()
        flag(
            both & (staged["discharge_date"] < staged["admission_date"]), "negative_length_of_stay"
        )

    if spec.get("year_from_source_config"):
        if year is None:
            raise ValueError(f"{dataset} needs the source year from config")
        staged.insert(1, "year", str(year))

    staged["source_row_number"] = row_numbers.astype(str)
    staged["row_hash"] = row_hashes(df, source_columns)
    keep = ~row_numbers.isin(list(reasons))
    staged = staged[keep].astype(object)
    staged = staged.where(staged.notna(), None)
    return ChunkResult(staged=staged, rejected=reasons)
