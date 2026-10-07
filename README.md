# Healthcare Claims Data Warehouse

A reproducible batch pipeline that ingests synthetic Medicare claims, validates and reconciles records, builds a dimensional warehouse, and serves utilization and payment dashboards.

**Status: planned portfolio project.** This repository currently contains a build specification
and documentation templates. Pipeline code, deployment and measured results are not completed.
Update this status only after reproducible execution.

## Business problem and output

Demonstrate the complete path from source acquisition through durable ingestion, validation,
transformation, serving and failure recovery. The output is a reproducible engineering demo
with an inspectable data model, dashboard/API and actual validation evidence.

## Tools

Python, pandas, SQLAlchemy, PostgreSQL, dbt Core + dbt-postgres, Apache Airflow, Docker Compose, Streamlit, pytest, GitHub Actions

## Data

CMS 2008–2010 DE-SynPUF, Sample 1. Begin with beneficiary summary, inpatient, outpatient, and prescription drug event files. Add carrier files later because their line structure needs a separate grain.

Development target: first 1,000 beneficiary IDs and every matching claim/PDE row. Stream the source files in chunks; do not assume the full downloads fit in RAM. Record actual resulting counts. Later run full Sample 1 only if resources permit.

## Proposed servers

Local Docker host: PostgreSQL warehouse and a separate Airflow metadata database; Airflow orchestrator; Streamlit application. Suggested starting host: 4 CPU cores, 16 GB RAM, 30 GB free disk; this is a planning estimate, not a measured minimum.

Optional AWS demo: Ubuntu EC2 for the orchestrator, S3 for raw files, RDS PostgreSQL for the warehouse, and CloudWatch for logs. Use separate database roles and private networking. Record exact instance class, region, service versions, runtime and costs after deployment. Local execution is the required first release.

These describe planned infrastructure. Record the host actually used in
[DEPLOYMENT.md](docs/DEPLOYMENT.md); do not describe proposed cloud services as deployed.

## Architecture

[Architecture and diagram](docs/ARCHITECTURE.md)

## Build and run

1. Follow [BUILD_GUIDE.md](docs/BUILD_GUIDE.md) in order.
2. Give [CLAUDE_BUILD_PROMPT.md](CLAUDE_BUILD_PROMPT.md) to Claude Code inside this repository.
3. Implement the commands defined in the guide, run them on a clean checkout, and save evidence.
4. Replace planned instructions with verified commands and actual versions before claiming completion.

## Repository layout

```text
README.md
CLAUDE_BUILD_PROMPT.md
PROJECT_TASKS.md
CONTRIBUTING.md
SECURITY.md
.env.example
.gitignore
docs/
  BUILD_GUIDE.md
  ARCHITECTURE.md
  DATA_DICTIONARY.md
  VALIDATION_PLAN.md
  DEPLOYMENT.md
  RESULTS.md
  SOURCES.md
  screenshots/README.md
```

The build should add `src/`, `tests/`, `config/`, `scripts/`, an appropriate dependency lockfile,
`Dockerfile`, `compose.yaml`, `Makefile`, and `.github/workflows/ci.yml`.
Batch projects should also add `dbt/` and, where specified, `dags/`.
Those implementation files are tasks, not pre-existing working code in this pack.

## Documentation

- [Data model and grain](docs/DATA_DICTIONARY.md)
- [Validation and recovery tests](docs/VALIDATION_PLAN.md)
- [Deployment and cleanup](docs/DEPLOYMENT.md)
- [Results template](docs/RESULTS.md)
- [Data sources and attribution](docs/SOURCES.md)
- [Implementation checklist](PROJECT_TASKS.md)

## Results

Not measured yet. See the results template for required evidence. No performance,
clinical accuracy, production use or regulatory compliance is claimed.

## Reuse and attribution

Code license has not yet been selected by the repository owner. Add a LICENSE before advertising
open-source reuse. Third-party datasets, tools and models retain their own licenses and terms.
Public code visibility does not itself grant a license or permission to redistribute source data.
