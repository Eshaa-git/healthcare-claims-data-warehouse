# Contributing

Use a branch and keep changes scoped. Before opening a pull request:

```bash
make lint
make test        # needs `make up`; integration tests use a separate claims_test database
```

- Add behavior tests for changed contracts, migrations and recovery paths.
- Never edit an applied migration. The runner refuses changed checksums, so add a new numbered
  file instead.
- Raw and stage DDL is generated from `config/`. After changing a contract or field mapping, run
  `uv run claims-dw generate-ddl` (the unit tests fail if they drift).
- After changing dependencies, run `make lock`. CI checks that `requirements.lock.txt` matches
  `uv.lock`.
- Keep data, credentials and generated databases out of git. Update the docs when commands,
  schemas or measured results change.
