"""Deterministic CMS-format fixtures with known expected results.

The base fixture mirrors the DE-SynPUF file layout (same headers, same archive structure) at a
tiny scale. Extra batches exercise incremental ingestion and quarantine rules. Every expected
count and amount is computed here from the generated rows, so tests compare the warehouse to
fixture truth rather than to the implementation.
"""

from __future__ import annotations

import csv
import io
import json
import random
import zipfile
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import contracts

DATASET_VERSION = "fixture-v1"
SEED = 42
N_BENEFICIARIES = 30

ARCHIVES = {
    ("beneficiary_summary", 2008): "fixture_2008_beneficiary_summary.zip",
    ("beneficiary_summary", 2009): "fixture_2009_beneficiary_summary.zip",
    ("beneficiary_summary", 2010): "fixture_2010_beneficiary_summary.zip",
    ("inpatient_claims", None): "fixture_2008_to_2010_inpatient_claims.zip",
    ("outpatient_claims", None): "fixture_2008_to_2010_outpatient_claims.zip",
    ("drug_events", None): "fixture_2008_to_2010_drug_events.zip",
}


def bene_id(n: int) -> str:
    return f"{n:016X}"


def source_entries() -> list[dict[str, Any]]:
    entries = []
    for (dataset, year), archive in ARCHIVES.items():
        entries.append(
            {
                "dataset": dataset,
                "year": year,
                "url": f"fixture://claims-dw/{archive}?seed={SEED}",
                "archive": archive,
                "member": archive.replace(".zip", ".csv"),
            }
        )
    return entries


def _blank_row(dataset: str) -> dict[str, str]:
    return dict.fromkeys(contracts()[dataset]["columns"], "")


def _money(cents: int) -> str:
    return f"{Decimal(cents) / 100:.2f}"


def generate_base() -> tuple[dict[tuple[str, int | None], list[dict[str, str]]], dict[str, Any]]:
    """Rows per source file plus the expected accepted results."""
    rng = random.Random(SEED)
    rows: dict[tuple[str, int | None], list[dict[str, str]]] = defaultdict(list)

    # Beneficiaries: everyone in 2008; #30 dies in 2008, #29 has no 2010 record.
    years_present = {n: [2008, 2009, 2010] for n in range(1, N_BENEFICIARIES + 1)}
    years_present[30] = [2008]
    years_present[29] = [2008, 2009]
    for n, years in years_present.items():
        for year in years:
            r = _blank_row("beneficiary_summary")
            r.update(
                DESYNPUF_ID=bene_id(n),
                BENE_BIRTH_DT=f"19{30 + n:02d}0{1 + n % 9}15",
                BENE_DEATH_DT="20081215" if n == 30 else "",
                BENE_SEX_IDENT_CD=str(1 + n % 2),
                BENE_RACE_CD=str(1 + n % 3),
                BENE_ESRD_IND="Y" if n % 7 == 0 else "0",
                SP_STATE_CODE=f"{10 + n % 5}",
                BENE_COUNTY_CD=f"{100 + n:03d}",
                BENE_HI_CVRAGE_TOT_MONS="12",
                BENE_SMI_CVRAGE_TOT_MONS="12",
                BENE_HMO_CVRAGE_TOT_MONS="0",
                PLAN_CVRG_MOS_NUM="12",
            )
            for cc in [
                "SP_ALZHDMTA",
                "SP_CHF",
                "SP_CHRNKIDN",
                "SP_CNCR",
                "SP_COPD",
                "SP_DEPRESSN",
                "SP_DIABETES",
                "SP_ISCHMCHT",
                "SP_OSTEOPRS",
                "SP_RA_OA",
                "SP_STRKETIA",
            ]:
                r[cc] = rng.choice(["1", "2"])
            for amt in [
                "MEDREIMB_IP",
                "BENRES_IP",
                "PPPYMT_IP",
                "MEDREIMB_OP",
                "BENRES_OP",
                "PPPYMT_OP",
                "MEDREIMB_CAR",
                "BENRES_CAR",
                "PPPYMT_CAR",
            ]:
                r[amt] = _money(rng.randrange(0, 500_000, 1000))
            rows[("beneficiary_summary", year)].append(r)

    truth: dict[str, Any] = {
        "beneficiary_years": {
            str(y): sum(y in v for v in years_present.values()) for y in (2008, 2009, 2010)
        },
        "inpatient": {
            "claims": 0,
            "payment_by_year": defaultdict(int),
            "los_days_by_year": defaultdict(int),
        },
        "outpatient": {"claims": 0, "payment_by_year": defaultdict(int), "orphan_segments": 0},
        "drug": {
            "events": 0,
            "gross_cost_by_year": defaultdict(int),
            "patient_pay_by_year": defaultdict(int),
        },
    }

    # Inpatient: beneficiaries 1-10, one stay each in 2008; #1 has a second segment; #10 negative payment.
    for n in range(1, 11):
        los = n
        admit = f"200803{10 + n:02d}"
        discharge = f"200803{10 + n + los:02d}"
        cents = -5_000 if n == 10 else 100_000 * n
        r = _blank_row("inpatient_claims")
        r.update(
            DESYNPUF_ID=bene_id(n),
            CLM_ID=f"1{n:014d}",
            SEGMENT="1",
            CLM_FROM_DT=admit,
            CLM_THRU_DT=discharge,
            PRVDR_NUM=f"PRV{n:03d}",
            CLM_PMT_AMT=_money(cents),
            NCH_PRMRY_PYR_CLM_PD_AMT="0.00",
            CLM_ADMSN_DT=admit,
            NCH_BENE_DSCHRG_DT=discharge,
            CLM_UTLZTN_DAY_CNT=str(los),
            CLM_DRG_CD=f"{200 + n}",
            ICD9_DGNS_CD_1="4280",
            ADMTNG_ICD9_DGNS_CD="7865",
            NCH_BENE_IP_DDCTBL_AMT="1024.00",
        )
        rows[("inpatient_claims", None)].append(r)
        truth["inpatient"]["claims"] += 1
        truth["inpatient"]["payment_by_year"]["2008"] += cents
        truth["inpatient"]["los_days_by_year"]["2008"] += los
        if n == 1:
            s2 = _blank_row("inpatient_claims")
            s2.update(
                DESYNPUF_ID=bene_id(n),
                CLM_ID=r["CLM_ID"],
                SEGMENT="2",
                PRVDR_NUM="PRV001",
                CLM_PMT_AMT=_money(25_000),
            )
            rows[("inpatient_claims", None)].append(s2)
            truth["inpatient"]["payment_by_year"]["2008"] += 25_000

    # Outpatient: beneficiaries 1-20, a 2009 and a 2010 visit; #2 has a second segment;
    # one segment-2 row (beneficiary 3) has no segment 1 and must be quarantined.
    for n in range(1, 21):
        for year in (2009, 2010):
            day = f"{year}06{n:02d}"
            cents = rng.randrange(1_000, 90_000, 10)
            r = _blank_row("outpatient_claims")
            r.update(
                DESYNPUF_ID=bene_id(n),
                CLM_ID=f"5{year}{n:010d}",
                SEGMENT="1",
                CLM_FROM_DT=day,
                CLM_THRU_DT=day,
                PRVDR_NUM=f"OPV{n:03d}",
                CLM_PMT_AMT=_money(cents),
                NCH_PRMRY_PYR_CLM_PD_AMT="0.00",
                ICD9_DGNS_CD_1="V5869",
                NCH_BENE_PTB_DDCTBL_AMT="0.00",
                NCH_BENE_PTB_COINSRNC_AMT="10.00",
            )
            rows[("outpatient_claims", None)].append(r)
            truth["outpatient"]["claims"] += 1
            truth["outpatient"]["payment_by_year"][str(year)] += cents
            if n == 2 and year == 2009:
                s2 = _blank_row("outpatient_claims")
                s2.update(
                    DESYNPUF_ID=bene_id(n),
                    CLM_ID=r["CLM_ID"],
                    SEGMENT="2",
                    PRVDR_NUM="OPV002",
                    CLM_PMT_AMT=_money(3_000),
                )
                rows[("outpatient_claims", None)].append(s2)
                truth["outpatient"]["payment_by_year"]["2009"] += 3_000
    orphan = _blank_row("outpatient_claims")
    orphan.update(
        DESYNPUF_ID=bene_id(3),
        CLM_ID="599999999999999",
        SEGMENT="2",
        PRVDR_NUM="OPV003",
        CLM_PMT_AMT=_money(7_000),
    )
    rows[("outpatient_claims", None)].append(orphan)
    truth["outpatient"]["orphan_segments"] = 1

    # Drug events: beneficiaries 1-25, one per year they are enrolled; NDCs keep leading zeros.
    pde = 0
    for n in range(1, 26):
        for year in years_present[n]:
            pde += 1
            cost = rng.randrange(500, 40_000, 5)
            pay = min(cost, rng.randrange(0, 5_000, 5))
            r = _blank_row("drug_events")
            r.update(
                DESYNPUF_ID=bene_id(n),
                PDE_ID=f"2{pde:014d}",
                SRVC_DT=f"{year}0{1 + n % 9}20",
                PROD_SRVC_ID=f"00{n:03d}012345",
                QTY_DSPNSD_NUM="30.000",
                DAYS_SUPLY_NUM="30",
                PTNT_PAY_AMT=_money(pay),
                TOT_RX_CST_AMT=_money(cost),
            )
            rows[("drug_events", None)].append(r)
            truth["drug"]["events"] += 1
            truth["drug"]["gross_cost_by_year"][str(year)] += cost
            truth["drug"]["patient_pay_by_year"][str(year)] += pay
    return dict(rows), _finalize(truth)


def _finalize(truth: dict[str, Any]) -> dict[str, Any]:
    """Convert cent counters to decimal strings for JSON."""

    def conv(obj: Any, key: str = "") -> Any:
        if isinstance(obj, dict):
            return {k: conv(v, k) for k, v in sorted(obj.items())}
        return obj

    out = conv(truth)
    for section, fields in {
        "inpatient": ["payment_by_year"],
        "outpatient": ["payment_by_year"],
        "drug": ["gross_cost_by_year", "patient_pay_by_year"],
    }.items():
        for f in fields:
            out[section][f] = {y: _money(c) for y, c in out[section][f].items()}
    return out


def _csv_bytes(columns: list[str], rows: list[dict[str, str]]) -> bytes:
    buf = io.StringIO()
    buf.write(",".join(f'"{c}"' for c in columns) + "\n")  # CMS quotes the header row only
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    for r in rows:
        writer.writerow([r[c] for c in columns])
    return buf.getvalue().encode()


def write_source_archives(raw_dir: Path) -> dict[str, Any]:
    """Write the base fixture as CMS-style zip archives and fixture_truth.json (deterministic)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows, truth = generate_base()
    for entry in source_entries():
        key = (entry["dataset"], entry["year"])
        data = _csv_bytes(contracts()[entry["dataset"]]["columns"], rows[key])
        info = zipfile.ZipInfo(entry["member"], date_time=(2012, 11, 29, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        with zipfile.ZipFile(raw_dir / entry["archive"], "w") as zf:
            zf.writestr(info, data)
    (raw_dir / "fixture_truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    return truth


# --- extra batches written to data/processed/incoming/<dataset>__<label>.csv ---------------------


def _write_batch(
    path: Path, dataset: str, rows: list[dict[str, str]], first_row_number: int
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = contracts()[dataset]["columns"]
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["_source_row_number", *columns])
        for i, r in enumerate(rows):
            writer.writerow([str(first_row_number + i), *[r[c] for c in columns]])


def write_incremental_batch(incoming_dir: Path) -> dict[str, Any]:
    """Three new 2009 inpatient stays for beneficiaries 11-13 (all valid)."""
    rows, cents_total, los_total = [], 0, 0
    for n in (11, 12, 13):
        cents, los = 200_000 + n, 2
        r = _blank_row("inpatient_claims")
        admit, discharge = f"200902{n:02d}", f"200902{n + los:02d}"
        r.update(
            DESYNPUF_ID=bene_id(n),
            CLM_ID=f"3{n:014d}",
            SEGMENT="1",
            CLM_FROM_DT=admit,
            CLM_THRU_DT=discharge,
            PRVDR_NUM=f"PRV{n:03d}",
            CLM_PMT_AMT=_money(cents),
            CLM_ADMSN_DT=admit,
            NCH_BENE_DSCHRG_DT=discharge,
            CLM_UTLZTN_DAY_CNT=str(los),
        )
        rows.append(r)
        cents_total += cents
        los_total += los
    _write_batch(incoming_dir / "inpatient_claims__batch_002.csv", "inpatient_claims", rows, 1)
    return {"claims": 3, "payment_2009": _money(cents_total), "los_days_2009": los_total}


def write_bad_batch(incoming_dir: Path) -> dict[str, Any]:
    """Outpatient and inpatient rows that each break one rule, plus one valid row."""
    base, _ = generate_base()
    existing = next(r for r in base[("outpatient_claims", None)] if r["SEGMENT"] == "1")

    def op(**kw: str) -> dict[str, str]:
        r = _blank_row("outpatient_claims")
        r.update(
            DESYNPUF_ID=bene_id(5),
            SEGMENT="1",
            CLM_FROM_DT="20090801",
            CLM_THRU_DT="20090801",
            CLM_PMT_AMT="40.00",
            PRVDR_NUM="OPV005",
        )
        r.update(kw)
        return r

    op_rows = [
        op(CLM_ID="700000000000001", CLM_FROM_DT="20091332"),  # invalid_date
        dict(existing),  # exact duplicate of loaded row
        op(CLM_ID="700000000000003"),  # first of two with same key
        op(CLM_ID="700000000000003", CLM_PMT_AMT="99.00"),  # conflicting duplicate
        op(CLM_ID="700000000000005", CLM_PMT_AMT=""),  # missing payment
        op(CLM_ID="700000000000006", DESYNPUF_ID="FFFFFFFFFFFFFFFF"),  # no beneficiary-year
        op(CLM_ID="700000000000007", CLM_THRU_DT="20090701"),  # thru before from
        op(CLM_ID="700000000000008", CLM_PMT_AMT="12.3x"),  # invalid amount
    ]
    ip = _blank_row("inpatient_claims")
    ip.update(
        DESYNPUF_ID=bene_id(6),
        CLM_ID="800000000000001",
        SEGMENT="1",
        CLM_FROM_DT="20090310",
        CLM_THRU_DT="20090312",
        CLM_ADMSN_DT="20090312",
        NCH_BENE_DSCHRG_DT="20090310",
        CLM_PMT_AMT="500.00",
    )  # discharge before admission
    _write_batch(incoming_dir / "outpatient_claims__batch_bad.csv", "outpatient_claims", op_rows, 1)
    _write_batch(incoming_dir / "inpatient_claims__batch_bad.csv", "inpatient_claims", [ip], 1)
    return {
        "outpatient_claims__batch_bad.csv": {
            "rows": 8,
            "accepted": 1,
            "accepted_payment_2009": "40.00",
            "reasons": {
                1: "invalid_date:CLM_FROM_DT",
                2: "duplicate_key_existing:exact",
                4: "duplicate_key_in_file:conflict",
                5: "missing_required:CLM_PMT_AMT",
                6: "no_beneficiary_year",
                7: "thru_before_from",
                8: "invalid_amount:CLM_PMT_AMT",
            },
        },
        "inpatient_claims__batch_bad.csv": {
            "rows": 1,
            "accepted": 0,
            "reasons": {1: "negative_length_of_stay"},
        },
    }
