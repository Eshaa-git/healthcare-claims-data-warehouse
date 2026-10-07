# Claude Code build prompt

You are building `healthcare-claims-data-warehouse` as a reproducible healthcare portfolio project. Read README.md and all
docs before editing. Implement the complete project in this folder using the specified stack and
the step sequence in docs/BUILD_GUIDE.md. Do the implementation; do not stop at another design draft.

First inspect existing files and available runtime resources. Preserve documentation and implement
source code, migrations, deterministic fixtures/generator, dependency locks, Dockerfile, Compose,
Makefile, tests, CI and the actual dashboard/API. Add dbt models/DAGs only where specified. Pin
compatible versions from official documentation. Keep the first release local and small enough to run.

Implement each documented grain, contract, lineage field, quarantine rule and retry/commit boundary.
Honor the exact validation plan, particularly idempotency, split leakage or streaming/API recovery
where relevant. The specified development size is a target, not permission to claim processed data.
Use a fixture path for CI and document full source acquisition separately. Do not use employer data.

Provide working `make setup`, `make up`, `make seed`, `make pipeline`, `make test`, `make report`, and
`make down`. Run appropriate tests and then a complete small-data demo. Diagnose failures and fix them.
If a runtime/download/credential dependency is unavailable, complete independent work and mark that
execution explicitly blocked; never invent test passes or silently replace the advertised dataset.
No cloud resource creation or paid LLM calls are required for this local build.

Generate reports/metrics.json from actual execution with data counts, hashes, run ID, git commit,
environment, durations and failed checks. Capture actual UI screenshots if the environment permits.
Rewrite README quick start to commands tested on a clean checkout; update RESULTS.md and DEPLOYMENT.md.
Keep missing measurements and unexecuted cloud work clearly labeled. Do not claim production usage,
HIPAA compliance, clinical validity, superior model performance or high availability without evidence.

At completion report implemented files, how to run, actual test results, actual dataset/counts, actual
server/tools/versions, limitations and unfinished work. Leave no placeholder logic in the required
local path. Do not create/push a GitHub repository unless separately instructed by the owner.
