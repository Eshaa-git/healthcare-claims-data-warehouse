# Sources and attribution

## Data

- **CMS 2008–2010 Data Entrepreneurs' Synthetic Public Use File (DE-SynPUF), Sample 1.** Centers
  for Medicare & Medicaid Services.
  [Landing page](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf/de10-sample-1).
  Archive URLs, sizes and SHA-256 values (downloaded 2026-10-07) are in
  [`config/sources.yaml`](../config/sources.yaml).
- **DE-SynPUF Data Users Guide.** [synpuf_dug.pdf](https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/synpuf_dug.pdf)
- **DE-SynPUF Codebook.** [de-10-codebook.pdf](https://www.cms.gov/files/document/de-10-codebook.pdf-0).
  The section IDs cited in `config/field_mapping.yaml` (for example IP-7, PDE-8) come from this
  document.

The CMS files are public use files of fully synthetic data. They are downloaded at run time and
are not redistributed in this repository. CMS notes that the synthetic process "significantly
diminishes the analytic utility of the file" and that inferences about Medicare beneficiaries,
providers or the program "will be misleading and often incorrect".

## Tools

PostgreSQL, Apache Airflow, dbt Core and dbt-postgres, pandas, SQLAlchemy, psycopg, Streamlit,
Altair, pytest, Ruff and uv are used under their own open-source licenses. The exact versions
are pinned in `uv.lock`, `requirements.lock.txt` and the image tags in `compose.yaml` and the
`Dockerfile`.

## Build process

The project was implemented with Claude Code, an AI coding assistant, from the specification in
[`CLAUDE_BUILD_PROMPT.md`](../CLAUDE_BUILD_PROMPT.md) and [`BUILD_GUIDE.md`](BUILD_GUIDE.md),
then run and verified locally as recorded in [RESULTS.md](RESULTS.md).
