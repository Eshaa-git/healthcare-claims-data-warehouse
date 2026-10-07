-- Operational metadata: runs, ingestion registry, quarantine, reconciliation and publication.

create table ops.pipeline_runs (
    run_id text primary key,
    source text not null,
    git_commit text,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    status text not null default 'running' check (status in ('running', 'succeeded', 'failed'))
);

create table ops.run_steps (
    run_id text not null,
    step text not null,
    attempt integer not null default 1,
    started_at timestamptz not null,
    finished_at timestamptz,
    duration_seconds numeric(12, 3),
    status text not null check (status in ('running', 'succeeded', 'failed')),
    detail jsonb,
    primary key (run_id, step, attempt)
);

-- One row per input file version. A file is identified by its checksum within a dataset version,
-- so re-presenting the same bytes is a no-op once it has loaded.
create table ops.ingestion_files (
    file_id bigserial primary key,
    dataset text not null,
    source_year integer,
    dataset_version text not null,
    source_uri text not null,
    source_archive text,
    source_member text,
    input_path text not null,
    sha256 text not null,
    size_bytes bigint not null,
    run_id text not null,
    attempts integer not null default 1,
    status text not null check (status in ('loading', 'loaded', 'failed')),
    row_count bigint,
    accepted_count bigint,
    rejected_count bigint,
    error text,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    unique (sha256, dataset_version)
);

-- One row per rejected source row; raw_payload keeps every source column as text.
create table ops.quarantine_rows (
    file_id bigint not null references ops.ingestion_files (file_id),
    source_row_number bigint not null,
    dataset text not null,
    reason_codes text[] not null,
    raw_payload jsonb not null,
    run_id text not null,
    quarantined_at timestamptz not null default now(),
    primary key (file_id, source_row_number)
);

create table ops.reconciliation_results (
    run_id text not null,
    check_name text not null,
    scope text not null,
    expected numeric,
    actual numeric,
    difference numeric,
    passed boolean not null,
    detail jsonb,
    checked_at timestamptz not null default now(),
    primary key (run_id, check_name, scope)
);

create table ops.publications (
    run_id text primary key,
    published_at timestamptz not null default now(),
    published_schema text not null,
    previous_schema text,
    detail jsonb
);
