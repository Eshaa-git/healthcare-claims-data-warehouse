# Validation

Each requirement maps to an automated check. Results from the recorded run are in
[RESULTS.md](RESULTS.md) and [`reports/`](../reports).

## Required checks

| Requirement | Where it is enforced |
|---|---|
| No duplicate fact keys; beneficiary-year key unique | dbt `unique`/`not_null` tests on every fact and dimension key; stage primary keys; `duplicate_key_*` quarantine |
| Every accepted fact references a beneficiary-year under the documented join rule | dbt `relationships` tests (fact → `dim_beneficiary_year`); loader quarantines `no_beneficiary_year` |
| Source rows = accepted + rejected; duplicates classified explicitly | Loader refuses to commit a file that does not balance; reconciliation checks registry, raw, stage and quarantine counts per file |
| Money reconciles with decimal arithmetic per source and year | `claims_dw.reconcile`: source sum = stage + quarantine per file; stage = fact per year; exact `numeric`, tolerance 0.00 |
| No negative length of stay; negative amounts read from documentation | Loader quarantines `negative_length_of_stay`; dbt `non_negative` test; negative `CLM_PMT_AMT` kept (codebook IP-7, OP-7) |
| A duplicate rerun changes neither counts nor totals | `test_02_rerun_is_idempotent`; second CMS run compared with `marts_previous` in `reports/metrics.json` |

## Test layers

| Layer | Files | Needs |
|---|---|---|
| Unit | `tests/unit/` (validation rules, DDL matches config, fixture determinism, cohort selection, checksum handling) | Nothing |
| Integration and end-to-end | `tests/integration/test_pipeline_e2e.py`: fixture run equals fixture truth, idempotent rerun, incremental batch, quarantine reason per bad row, dashboard role limited to `marts` | PostgreSQL (`make up`); uses a separate `claims_test` database |
| Failure and recovery | `tests/integration/test_recovery.py`: injected failure mid-file rolls back and retries; SIGKILL of a real loader process mid-transaction leaves zero rows; tampered build fails reconciliation and publish is refused | PostgreSQL |
| dbt | 48 data tests (`dbt/models/**/_*.yml`, `dbt/tests/`) | Warehouse |
| Reconciliation | 38 checks per CMS run, stored in `ops.reconciliation_results` | Warehouse |

The deterministic fixture (`claims_dw.fixtures`) writes CMS-format archives and a
`fixture_truth.json` with the expected counts and amounts, computed while the rows are
generated. End-to-end tests compare the warehouse to that truth, not to the code under test.

## CI

`.github/workflows/ci.yml` runs on every push and pull request:

1. Ruff lint and format check.
2. Unit tests.
3. Integration and recovery tests against a `postgres:17.11-alpine` service container.
4. The full fixture pipeline through the CLI, with the run summary added to the job summary.
5. A Docker image build, a check that `requirements.lock.txt` matches `uv.lock`, and a DAG import
   and task-chain check inside the image.

Full CMS downloads are not part of CI.
