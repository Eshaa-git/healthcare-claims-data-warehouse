# End-to-end build guide

## Prerequisites and environment

Install git, Docker Engine/Desktop with Compose, and the language runtime compatible with the
selected tool versions. The implementation must pin compatible dependencies and image tags/digests;
never assume independently newest versions work together. Create `.env` from `.env.example`.
Choose local ports before running the stack; bind demo interfaces to 127.0.0.1.

Local Docker host: PostgreSQL warehouse and a separate Airflow metadata database; Airflow orchestrator; Streamlit application. Suggested starting host: 4 CPU cores, 16 GB RAM, 30 GB free disk; this is a planning estimate, not a measured minimum.

## Data acquisition

CMS 2008–2010 DE-SynPUF, Sample 1. Begin with beneficiary summary, inpatient, outpatient, and prescription drug event files. Add carrier files later because their line structure needs a separate grain.

Development target: first 1,000 beneficiary IDs and every matching claim/PDE row. Stream the source files in chunks; do not assume the full downloads fit in RAM. Record actual resulting counts. Later run full Sample 1 only if resources permit.

## Implementation sequence

### 1. Acquire and document data

Download selected CMS archives; retain source URL, retrieval date, SHA-256, file size, year, sample and data dictionary. Inspect headers before coding mappings. Keep raw archives outside git.

**Deliverable:** implementation, a deterministic test and recorded output for this step.

### 2. Select a reproducible cohort

Choose the first 1,000 sorted beneficiary IDs from the selected summary files. Filter all fact files to the same IDs; retain cohort IDs locally and record a cohort hash. Preserve multiple annual beneficiary records.

**Deliverable:** implementation, a deterministic test and recorded output for this step.

### 3. Define file contracts

Store expected columns, key rules, nullable fields and CMS-specific money/date semantics in config/contracts.yaml. Preserve IDs and diagnosis/procedure codes as strings. Parse dates explicitly, retaining raw values for troubleshooting.

**Deliverable:** implementation, a deterministic test and recorded output for this step.

### 4. Register ingestion

Use an ingestion_files table keyed by source checksum and dataset version. Track run ID, row count, rejected count and status. Download to a temporary name, check hash and archive validity, then atomically promote to raw storage.

**Deliverable:** implementation, a deterministic test and recorded output for this step.

### 5. Load raw and stage

Use chunked pandas reads and PostgreSQL COPY. Attach run_id, source_file, source_row_number and loaded_at. Route invalid rows to quarantine with reason codes. Never silently discard malformed records.

**Deliverable:** implementation, a deterministic test and recorded output for this step.

### 6. Model the warehouse

Use one fact per source grain. Build annual beneficiary dimension, date dimension, inpatient and outpatient claim facts, and drug-event fact. Join claims to beneficiary-year using the documented date rule; do not multiply claims across all beneficiary years.

**Deliverable:** implementation, a deterministic test and recorded output for this step.

### 7. Transform with dbt

Implement staging, intermediate and mart models. Use explicit column mappings and tested surrogate keys; publish marts for monthly payments, admissions, length of stay and drug payments. Label available payment measures accurately; do not call Medicare payment the total cost of care.

**Deliverable:** implementation, a deterministic test and recorded output for this step.

### 8. Orchestrate and recover

Airflow tasks: acquire -> cohort -> stage -> dbt run -> dbt test -> reconcile -> publish. Retry transient errors only. Use transactional stage/promote logic so failed reconciliation prevents publication; a failed run must not destroy the last successful mart.

**Deliverable:** implementation, a deterministic test and recorded output for this step.

### 9. Serve analytics

Create Streamlit charts and downloadable aggregates: monthly claim payments, admissions per 1,000 beneficiary-years, observed inpatient days and drug-event counts. Document denominators, date filters and excluded/quarantined records.

**Deliverable:** implementation, a deterministic test and recorded output for this step.

### 10. Prove repeatability

Run the same batch twice and assert unchanged fact counts and sums. Add one controlled new fixture batch; test incremental ingestion. Inject bad dates, duplicates and an interrupted load; demonstrate quarantine and safe restart.

**Deliverable:** implementation, a deterministic test and recorded output for this step.

### 11. Publish evidence

Save measured counts, runtimes, reconciliation outputs, dbt docs screenshot and dashboard screenshot. Write RESULTS.md only from actual output; synthetic historical claims support a pipeline demo, not conclusions about current Medicare populations.

**Deliverable:** implementation, a deterministic test and recorded output for this step.

## Required command contract — to implement

These commands are acceptance requirements for the future Makefile, not working commands yet.

```bash
cp .env.example .env
# Fill required local credentials; never commit .env.
make setup        # validate runtime, install locked dependencies, check config
make up           # start services with persistent volumes and health checks
make seed         # acquire/generate deterministic demo inputs; write manifest
make pipeline     # ingest, process and validate; exit nonzero on failure
make test         # unit + integration + replay/recovery tests
make report       # measured, machine-readable metrics plus summary
make down         # stop services while retaining volumes
```

`make reset` may be added for local demo data only, with explicit confirmation and clear destructive
scope. All commands must be implemented and verified before moving these to a README quick start.

## Acceptance gate

A new user can clone the repository, follow the verified commands, run the small dataset and inspect
the output. A repeated run does not duplicate accepted data. A simulated failure preserves the last
good state. Screenshots and metric files are generated from that same recorded run.
