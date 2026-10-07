# Deployment record

## Actual environment (recorded run, 2026-10-07)

| Field | Actual value |
|---|---|
| Execution date / git commit | 2026-10-07 22:13–22:16 UTC / `61313ec0e7f56a8a82e2d3285897d6c15bae1fde` |
| Host | MacBook (Apple M1, 8 cores, 8 GB RAM), macOS 14.5, on AC power |
| Container runtime | Docker Desktop 4.94.0, Engine 29.8.2, Compose v5.5.1; Linux VM with 4 GB memory and 8 CPUs |
| Images | `postgres:17.11-alpine` (×2), `claims-dw:local` built from `apache/airflow:3.3.2-python3.12` |
| Database / orchestrator | PostgreSQL 17.11; Airflow 3.3.2 `standalone` with LocalExecutor and its own metadata database |
| Memory in use | Airflow container about 1.3–1.8 GB; each PostgreSQL under 210 MB; dashboard about 50 MB |
| Storage | Images about 4.7 GB; database volumes about 290 MB; CMS archives 148 MB (`data/raw`, not in git) |
| Measured runtime | 36 s of step time for a loading run, 27 s for a rerun (see [RESULTS.md](RESULTS.md)) |
| Cloud provider / region / cost | Not deployed. No cloud resources were created and there was no cost. |

## Services and ports

`compose.yaml` defines `warehouse-db`, `airflow-db`, `airflow` and `dashboard`, each with a health
check. Host ports are bound to 127.0.0.1 only:

| Service | Address |
|---|---|
| Warehouse | `127.0.0.1:55432` |
| Airflow UI | `127.0.0.1:8080` |
| Dashboard | `127.0.0.1:8501` |

Inside the Compose network, services reach the warehouse at `warehouse-db:5432`. Credentials come
from `.env`, which is git-ignored; `scripts/check_env.sh` refuses placeholder values. The
loader, transformer and dashboard each use their own database role (see
[ARCHITECTURE.md](ARCHITECTURE.md)).

## Operating notes

- **`make down` keeps data.** It stops the containers but keeps the named volumes
  (`warehouse-data`, `airflow-db-data`). After `make up`, the published marts are still there.
- **`make reset` deletes data.** It removes the volumes and `data/processed`, and asks you to type
  `reset` first. Raw CMS archives in `data/raw` are kept, and `make seed` re-verifies their
  checksums.
- **Rebuilding.** Everything can be rebuilt from the CMS archives plus this repository. The only
  state that matters is the ingestion registry (`ops.ingestion_files`), which makes reruns
  idempotent. It lives in the warehouse volume. A database backup and restore was not tested.
- **Host sleep pauses everything.** In early attempts, the Mac went to sleep with the lid closed,
  which froze the Docker VM and left tasks waiting about 16 minutes at a time. The recorded run
  used `caffeinate -s` to keep the host awake.
- **Airflow `standalone` is a development mode.** One container runs the scheduler, API server,
  DAG processor and triggerer. A VM running Compose like this is a demo, not a highly available
  deployment.

## Optional cloud extension (not done)

The specification describes an optional AWS profile (EC2 for orchestration, S3 for raw files,
RDS PostgreSQL, CloudWatch). None of it was deployed. Before any cloud run, define a budget and
a resource inventory, use private database networking and TLS, use least-privilege credentials,
and record instance classes, region, runtime and cost here.
