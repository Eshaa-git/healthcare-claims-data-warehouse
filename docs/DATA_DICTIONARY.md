# Data model

Field-level mappings (source column, target column, type, null rule, unit, codebook reference)
are in [`config/field_mapping.yaml`](../config/field_mapping.yaml). The staging loader reads that
file directly. File contracts (expected headers, keys, date and money columns, allowed codes)
are in [`config/contracts.yaml`](../config/contracts.yaml).

## Operational schema (`ops`)

| Table | Grain | Notes |
|---|---|---|
| `ingestion_files` | One input file version | Unique on `(sha256, dataset_version)`; status `loading` / `loaded` / `failed`; row, accepted and rejected counts; attempt count |
| `quarantine_rows` | One rejected source row | `(file_id, source_row_number)`; `reason_codes text[]`; full raw row as `jsonb` |
| `pipeline_runs`, `run_steps` | One run / one step attempt | Step durations come from a monotonic clock |
| `reconciliation_results` | One check per run and scope | Expected, actual and difference as exact `numeric` |
| `publications` | One successful publish | Which schema became `marts` and which became `marts_previous` |
| `schema_migrations` | One applied migration | sha256 of the SQL file; an edited migration is refused |

## Landing and staging

| Schema.table | Grain | Key |
|---|---|---|
| `raw.<dataset>` | One source row, every column as text | `(file_id, source_row_number)` |
| `stage.beneficiary_year` | One beneficiary per summary-file year | `(beneficiary_id, year)` |
| `stage.inpatient_claim_segment` | One inpatient claim segment | `(claim_id, segment)` |
| `stage.outpatient_claim_segment` | One outpatient claim segment | `(claim_id, segment)` |
| `stage.drug_event` | One Part D event | `pde_id` |

Each staged row carries `file_id`, `source_row_number` (the row's position in the original CMS
CSV), `row_hash` and `run_id`, so every warehouse value traces back to a source file and row.

## Warehouse (`marts`)

| Table | Grain | Keys and main fields |
|---|---|---|
| `dim_beneficiary_year` | Beneficiary × summary year | `beneficiary_year_key = md5(id \| year)`; demographics, coverage months, 11 chronic-condition flags |
| `dim_date` | Calendar day, 2007–2011 | `date_key` (yyyymmdd), month, quarter |
| `fact_inpatient_claim` | One inpatient claim (`CLM_ID`) | `beneficiary_year_key`, admission/discharge, `length_of_stay_days`, `medicare_claim_payment_amt` |
| `fact_outpatient_claim` | One outpatient claim (`CLM_ID`) | `beneficiary_year_key`, service dates, `medicare_claim_payment_amt` |
| `fact_drug_event` | One prescription drug event (`PDE_ID`) | `beneficiary_year_key`, NDC, `gross_drug_cost_amt`, `patient_pay_amt` |
| `mart_monthly_claim_payments` | Month × claim type | Claim count, Medicare payment, count of negative-payment claims |
| `mart_monthly_drug_events` | Month | Event count, gross drug cost, patient pay |
| `mart_inpatient_utilization_yearly` | Year | Beneficiary-years, admissions, admissions per 1,000, observed inpatient days |
| `mart_data_quality` | Input file × reason | Accepted and quarantined row counts |
| `publication_info` | One row | Run that produced this `marts` schema |

## Rules that are easy to get wrong

- **Claim segments.** `SEGMENT = 2` rows continue a claim. They carry real payments but no dates,
  and they share the `CLM_ID` of segment 1. Facts are at claim grain: payments are summed over all
  segments, and dates and attributes come from segment 1. A segment-2 row with no segment 1 cannot
  be dated, so it is quarantined (`orphan_segment`).
- **Join to beneficiary-year.** A claim belongs to the beneficiary-year of its segment-1
  `CLM_THRU_DT`. A drug event belongs to the beneficiary-year of `SRVC_DT`. A row with no matching
  summary record is quarantined (`no_beneficiary_year`), never multiplied across years.
- **Negative payments are valid.** The codebook (IP-7, OP-7) explains negative `CLM_PMT_AMT` as
  deductible or coinsurance exceeding the Medicare payment. These claims are kept and counted in
  `negative_payment_claims`.
- **Payment labels.** `medicare_claim_payment_amt` is the Medicare payment on institutional
  inpatient and outpatient claims. It is not total cost of care: carrier claims are not loaded,
  and beneficiary cost-sharing is a separate field.
- **Money** is exact `numeric(14,2)` from source text and is never stored as a float.
- **Codes stay text.** `DESYNPUF_ID`, `CLM_ID`, ICD-9 codes, DRG codes and NDCs (`PROD_SRVC_ID`)
  keep their leading zeros.

## Quarantine reason codes

| Code | Meaning |
|---|---|
| `missing_required:<COL>` | Required value empty (dates only required on segment 1) |
| `invalid_date:<COL>` | Not a real `YYYYMMDD` date |
| `invalid_amount:<COL>`, `invalid_integer:<COL>`, `invalid_decimal:<COL>` | Not parseable as that type |
| `invalid_code:<COL>` | Value outside the codebook's allowed codes |
| `thru_before_from` | `CLM_THRU_DT` earlier than `CLM_FROM_DT` |
| `negative_length_of_stay` | Discharge earlier than admission |
| `duplicate_key_in_file:exact` / `:conflict` | Key repeated within one file (identical or different content) |
| `duplicate_key_existing:exact` / `:conflict` | Key already accepted from an earlier file |
| `orphan_segment` | Continuation segment without a segment 1 |
| `no_beneficiary_year` | No beneficiary summary record for the claim or event year |
