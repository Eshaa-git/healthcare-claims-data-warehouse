# Proposed data model

| Table | Grain | Keys and main fields |
|---|---|---|
| ingestion_files | One source file/checksum | file_id, source_uri, sha256, status, run_id, counts |
| dim_beneficiary_year | One beneficiary per source year | beneficiary_id + year; annual eligibility/demographic fields |
| dim_date | One calendar day | date_key, date, month, year |
| fact_inpatient_claim | One documented source claim | beneficiary_id + claim_id; admission/discharge dates, documented payment columns |
| fact_outpatient_claim | One documented source claim | beneficiary_id + claim_id; service dates, payment |
| fact_drug_event | One prescription drug event | beneficiary_id + PDE_ID; service date, documented drug/payment fields |
| quarantine_rows | One rejected source row | file_id + source_row_number; raw payload, reason |

## Mapping implementation requirement

Create `config/field_mapping.yaml` with source field, target field, source type, target type,
transformation, null handling, code system/unit, key role and source documentation reference.
The listed names are target concepts, not a guarantee that the source headers use the same names.
Inspect real inputs before finalizing DDL. Preserve raw values and source/run lineage.
Use timezone-aware UTC timestamps and decimal money; define rounding and precision explicitly.
Add schema migrations and a machine-readable contract. Record schema/version changes.
