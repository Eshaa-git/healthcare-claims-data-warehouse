import pandas as pd

from claims_dw.config import contracts
from claims_dw.validate import transform_chunk


def frame(dataset: str, rows: list[dict[str, str]]) -> pd.DataFrame:
    cols = contracts()[dataset]["columns"]
    data = [{c: r.get(c, "") for c in cols} for r in rows]
    df = pd.DataFrame(data, columns=cols, dtype=str)
    df.insert(0, "_source_row_number", [str(i + 1) for i in range(len(rows))])
    return df


def run(dataset, rows, year=None):
    df = frame(dataset, rows)
    return transform_chunk(df, dataset, contracts()[dataset]["columns"], year)


OP_OK = {
    "DESYNPUF_ID": "A",
    "CLM_ID": "1",
    "SEGMENT": "1",
    "CLM_FROM_DT": "20090101",
    "CLM_THRU_DT": "20090102",
    "CLM_PMT_AMT": "-10.50",
}


def test_valid_outpatient_row_is_typed_and_negative_payment_kept():
    res = run("outpatient_claims", [OP_OK])
    assert res.rejected == {}
    row = res.staged.iloc[0]
    assert row["claim_from_date"] == "2009-01-01"
    assert row["claim_payment_amt"] == "-10.50"
    assert row["primary_payer_paid_amt"] is None  # empty optional money -> NULL
    assert row["source_row_number"] == "1"
    assert len(row["row_hash"]) == 64


def test_each_row_rule_produces_its_reason_code():
    rows = [
        {**OP_OK, "CLM_FROM_DT": "20091332"},
        {**OP_OK, "CLM_PMT_AMT": ""},
        {**OP_OK, "CLM_PMT_AMT": "12.345"},
        {**OP_OK, "CLM_THRU_DT": "20081231"},
        {**OP_OK, "SEGMENT": "x"},
        {**OP_OK, "SEGMENT": "0"},
    ]
    res = run("outpatient_claims", rows)
    assert res.rejected == {
        1: ["invalid_date:CLM_FROM_DT"],
        2: ["missing_required:CLM_PMT_AMT"],
        3: ["invalid_amount:CLM_PMT_AMT"],
        4: ["thru_before_from"],
        5: ["invalid_integer:SEGMENT"],
        6: ["invalid_code:SEGMENT"],
    }
    assert res.staged.empty


def test_segment_2_rows_may_omit_dates_but_segment_1_may_not():
    seg2 = {"DESYNPUF_ID": "A", "CLM_ID": "1", "SEGMENT": "2", "CLM_PMT_AMT": "5.00"}
    seg1_missing = {**seg2, "SEGMENT": "1"}
    res = run("outpatient_claims", [seg2, seg1_missing])
    assert list(res.staged["segment"]) == ["2"]
    assert res.rejected == {2: ["missing_required:CLM_FROM_DT", "missing_required:CLM_THRU_DT"]}


def test_negative_length_of_stay_is_rejected():
    ip = {
        "DESYNPUF_ID": "A",
        "CLM_ID": "9",
        "SEGMENT": "1",
        "CLM_FROM_DT": "20090101",
        "CLM_THRU_DT": "20090105",
        "CLM_ADMSN_DT": "20090105",
        "NCH_BENE_DSCHRG_DT": "20090101",
        "CLM_PMT_AMT": "1.00",
    }
    res = run("inpatient_claims", [ip])
    assert res.rejected == {1: ["negative_length_of_stay"]}


def test_beneficiary_codes_flags_and_year():
    bene = {
        "DESYNPUF_ID": "A",
        "BENE_BIRTH_DT": "19300101",
        "BENE_SEX_IDENT_CD": "2",
        "BENE_ESRD_IND": "Y",
        "SP_DIABETES": "1",
        "SP_CHF": "2",
        "SP_STATE_CODE": "05",
    }
    bad = {**bene, "DESYNPUF_ID": "B", "BENE_SEX_IDENT_CD": "3", "SP_COPD": "9"}
    res = run("beneficiary_summary", [bene, bad], year=2009)
    row = res.staged.iloc[0]
    assert (row["year"], row["has_esrd"], row["cc_diabetes"], row["cc_heart_failure"]) == (
        "2009",
        "true",
        "true",
        "false",
    )
    assert row["state_code"] == "05"  # codes keep leading zeros
    assert res.rejected == {2: ["invalid_code:BENE_SEX_IDENT_CD", "invalid_code:SP_COPD"]}


def test_ndc_keeps_leading_zeros_and_row_hash_changes_with_content():
    pde = {
        "DESYNPUF_ID": "A",
        "PDE_ID": "1",
        "SRVC_DT": "20080103",
        "PROD_SRVC_ID": "00247037252",
        "QTY_DSPNSD_NUM": "30.000",
        "DAYS_SUPLY_NUM": "20",
        "PTNT_PAY_AMT": "10.00",
        "TOT_RX_CST_AMT": "120.00",
    }
    res = run("drug_events", [pde, {**pde, "PDE_ID": "2", "TOT_RX_CST_AMT": "121.00"}])
    assert res.staged.iloc[0]["product_service_id"] == "00247037252"
    assert res.staged.iloc[0]["row_hash"] != res.staged.iloc[1]["row_hash"]
