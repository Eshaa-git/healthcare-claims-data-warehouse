import json
from dataclasses import replace

import pytest

from claims_dw import cohort, fixtures
from claims_dw.acquire import sha256_file
from claims_dw.config import DbSettings, Settings


@pytest.fixture
def fixture_settings(tmp_path):
    db = DbSettings("x", 1, "x", "a", "a", "l", "t", "d")
    s = Settings(db=db, data_dir=tmp_path, source="fixture", cohort_size=1000, chunk_rows=7)
    fixtures.write_source_archives(s.raw_dir)
    return s


def test_fixture_archives_are_byte_for_byte_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    fixtures.write_source_archives(a)
    fixtures.write_source_archives(b)
    for entry in fixtures.source_entries():
        assert sha256_file(a / entry["archive"]) == sha256_file(b / entry["archive"])


def test_fixture_truth_counts():
    _, truth = fixtures.generate_base()
    assert truth["beneficiary_years"] == {"2008": 30, "2009": 29, "2010": 28}
    assert truth["inpatient"]["claims"] == 10
    assert truth["outpatient"]["claims"] == 40
    assert truth["outpatient"]["orphan_segments"] == 1


def test_cohort_takes_first_n_sorted_ids_and_all_their_rows(fixture_settings):
    s = replace(fixture_settings, cohort_size=5)
    manifest = cohort.build_cohort(s)
    ids = (s.cohort_dir / "cohort_ids.txt").read_text().split()
    assert ids == [fixtures.bene_id(n) for n in range(1, 6)]
    by_extract = {e["extract"]: e for e in manifest["extracts"]}
    ip = by_extract["fixture_2008_to_2010_inpatient_claims.csv"]
    assert ip["source_rows"] == 11 and ip["rows"] == 6  # benes 1-5 plus bene 1's segment 2
    lines = (s.cohort_dir / ip["extract"]).read_text().splitlines()
    assert lines[0].startswith("_source_row_number,DESYNPUF_ID,CLM_ID")
    assert [line.split(",")[0] for line in lines[1:]] == ["1", "2", "3", "4", "5", "6"]


def test_cohort_is_reproducible(fixture_settings):
    first = cohort.build_cohort(fixture_settings)
    second = cohort.build_cohort(fixture_settings)
    assert first == second
    assert json.loads((fixture_settings.cohort_dir / "cohort.json").read_text()) == second


def test_cohort_rejects_header_drift(fixture_settings):
    with pytest.raises(cohort.ContractError):
        cohort.check_header(["DESYNPUF_ID", "SURPRISE"], "drug_events", "test")
