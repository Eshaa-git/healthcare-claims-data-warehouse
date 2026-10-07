# Server setup and deployment record

## Planned local server

Local Docker host: PostgreSQL warehouse and a separate Airflow metadata database; Airflow orchestrator; Streamlit application. Suggested starting host: 4 CPU cores, 16 GB RAM, 30 GB free disk; this is a planning estimate, not a measured minimum.

Define all services, persistent volumes, startup health checks, resource settings and dependency
versions in `compose.yaml`. Separate database users for loaders, transformations and dashboard reads.
Keep credentials in environment/secret files outside git. Record localhost ports and internal hostnames.

## Optional cloud extension

Optional AWS demo: Ubuntu EC2 for the orchestrator, S3 for raw files, RDS PostgreSQL for the warehouse, and CloudWatch for logs. Use separate database roles and private networking. Record exact instance class, region, service versions, runtime and costs after deployment. Local execution is the required first release.

Before cloud execution, create a resource inventory and owner-defined budget. Deploy only the selected
profile. Use TLS, private database access and restricted inbound rules; never expose a raw unauthenticated
database/broker. Use least-privilege credentials and keep tokens out of logs and screenshots.

## Actual environment — fill only after running

| Field | Actual value |
|---|---|
| Execution date / git commit | Not run |
| Local host OS / CPU / RAM | Not recorded |
| Runtime and container versions | Not recorded |
| Database/server versions | Not recorded |
| Cloud provider / region / resource class | Not deployed |
| Storage size / actual runtime | Not measured |
| Measured cost / cost window | Not measured |

## Recovery and cleanup

Test database backup and restore locally. Document which inputs permit a full rebuild and which
state/watermarks must be restored. `make down` must retain data. List a separate confirmed reset
procedure. For cloud work, document stopping compute, deleting unused storage and retained snapshots;
verify billing/resource inventory after cleanup. A VM Compose deployment is a demo, not proof of HA.
