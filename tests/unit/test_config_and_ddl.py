from claims_dw import ddl
from claims_dw.config import MIGRATIONS_DIR, contracts, field_mapping, sources


def test_committed_migrations_match_generated_ddl():
    assert (MIGRATIONS_DIR / "002_raw_tables.sql").read_text() == ddl.raw_table_ddl()
    assert (MIGRATIONS_DIR / "003_stage_tables.sql").read_text() == ddl.stage_table_ddl()


def test_mapping_sources_exist_in_contracts():
    for dataset, spec in field_mapping().items():
        columns = contracts()[dataset]["columns"]
        for f in spec["fields"]:
            assert f["source"] in columns, (dataset, f["source"])
            assert f["doc"].startswith("Codebook "), f


def test_every_dataset_has_contract_mapping_and_source():
    datasets = {f["dataset"] for f in sources()["files"]}
    assert datasets == set(contracts()) == set(field_mapping())


def test_stage_keys():
    assert ddl.stage_key("beneficiary_summary") == ["beneficiary_id", "year"]
    assert ddl.stage_key("inpatient_claims") == ["claim_id", "segment"]
    assert ddl.stage_key("drug_events") == ["pde_id"]
