# Implementation checklist

Status after the recorded run on 2026-10-07 (commit `61313ec`). Evidence links point to the
code, reports or tests that show each item.

- [x] 1. Acquire and document data: `claims_dw.acquire`, `config/sources.yaml`, `data/manifest/sources.json`
- [x] 2. Select a reproducible cohort: `claims_dw.cohort`; identical cohort sha256 on host and in container
- [x] 3. Define file contracts: `config/contracts.yaml`, `config/field_mapping.yaml`
- [x] 4. Register ingestion: `ops.ingestion_files` keyed by `(sha256, dataset_version)`
- [x] 5. Load raw and stage: chunked pandas + COPY, lineage columns, `ops.quarantine_rows`
- [x] 6. Model the warehouse: `dim_beneficiary_year`, `dim_date`, three facts (one per source grain)
- [x] 7. Transform with dbt: staging, intermediate and mart models; 48 data tests
- [x] 8. Orchestrate and recover: Airflow DAG; transient-only retries; gated schema-swap publish
- [x] 9. Serve analytics: Streamlit dashboard with CSV downloads and denominators
- [x] 10. Prove repeatability: recorded runs A/B/C plus integration recovery tests
- [x] 11. Publish evidence: `reports/`, `docs/RESULTS.md`, `docs/screenshots/`
- [x] Lock dependency and container versions (`uv.lock`, `requirements.lock.txt` with hashes, image tags)
- [x] Implement the Makefile command contract and CI (`Makefile`, `.github/workflows/ci.yml`)
- [x] Run from a clean stack and save real evidence (`docker compose down -v`, then the full sequence)
- [x] Update README status, quick start and deployment record
- [ ] Choose a code license (left to the repository owner); data and tool attribution is in `docs/SOURCES.md`
- [ ] Optional: full Sample 1 run (not attempted on an 8 GB host); optional AWS profile (not deployed)
