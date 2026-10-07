# Validation plan

## Required tests

- [ ] No duplicate fact keys; annual beneficiary key is unique.
- [ ] Every accepted fact references an eligible beneficiary-year under the documented join rule.
- [ ] Source rows = accepted rows + rejected rows; duplicate classification is explicit.
- [ ] Money reconciliation uses decimal arithmetic, per source/year, with documented null handling and tolerance.
- [ ] No negative length of stay; interpret financial adjustments from documentation rather than rejecting all negative amounts.
- [ ] Duplicate rerun changes neither row counts nor payment totals.

## Test layers

Unit tests validate transformations and edge cases using small fixtures. Integration tests exercise
real local services, migrations and API/broker/database boundaries. End-to-end tests execute the
seeded pipeline, verify output against fixture truth and rerun it. Failure tests interrupt a defined
commit boundary and prove recovery. Assertions must test behavior, not merely echo implementation.

## Required evidence

- Rows by input file and warehouse fact
- Accepted, quarantined and duplicate counts
- Source-to-warehouse payment reconciliation
- End-to-end and per-stage runtime
- Second-run idempotency result
- Dashboard denominators and excluded records

Write `reports/metrics.json` with run ID, source/cohort/split hashes, git commit, versions, host specs,
timestamps, counters, measured timings, failed checks and limitations. Use a monotonic timer for
elapsed processing duration. Save logs without credentials. Missing evidence remains "not measured".

## CI design — implement during build

Pull-request CI installs locked dependencies, lints, tests fixtures, starts required service containers,
applies migrations and runs a small end-to-end test. Keep full public-dataset downloads and paid LLM
calls out of routine CI. Provide explicit manual jobs for larger runs. Do not add passing badges
before the associated workflow exists and passes.
