-- Least-privilege grants. Roles are created by `claims-dw migrate` before migrations run.
--   claims_loader       writes raw, stage, quarantine and the ingestion registry
--   claims_transformer  reads stage/raw/ops, builds dbt schemas, records reconciliation, publishes marts
--   claims_dashboard    reads the published marts schema only (granted by the publish step)

revoke all on database {{database}} from public;
revoke create on schema public from public;
grant connect on database {{database}} to claims_loader, claims_transformer, claims_dashboard;
grant temporary on database {{database}} to claims_loader;

grant usage on schema ops, raw, stage to claims_loader;
grant select, insert, update on ops.ingestion_files, ops.pipeline_runs, ops.run_steps to claims_loader;
grant usage on sequence ops.ingestion_files_file_id_seq to claims_loader;
grant select, insert on ops.quarantine_rows to claims_loader;
grant select, insert on all tables in schema raw to claims_loader;
grant select, insert on all tables in schema stage to claims_loader;

grant usage on schema ops, raw, stage to claims_transformer;
grant select on all tables in schema raw to claims_transformer;
grant select on all tables in schema stage to claims_transformer;
grant select on ops.ingestion_files, ops.quarantine_rows, ops.schema_migrations to claims_transformer;
grant select, insert, update on ops.pipeline_runs, ops.run_steps to claims_transformer;
grant select, insert, update, delete on ops.reconciliation_results to claims_transformer;
grant select, insert on ops.publications to claims_transformer;
grant create on database {{database}} to claims_transformer;
