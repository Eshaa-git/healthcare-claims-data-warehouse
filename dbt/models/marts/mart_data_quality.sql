-- Accepted and quarantined rows per loaded input file and primary reason code.
with reasons as (
    select file_id, reason_codes[1] as reason_code, count(*) as quarantined_rows
    from {{ source('ops', 'quarantine_rows') }}
    group by file_id, reason_codes[1]
)

select
    f.file_id,
    f.dataset,
    coalesce(f.source_archive || '!' || f.source_member, f.source_uri) as input_file,
    f.row_count,
    f.accepted_count,
    f.rejected_count,
    r.reason_code,
    coalesce(r.quarantined_rows, 0) as quarantined_rows
from {{ source('ops', 'ingestion_files') }} as f
left join reasons as r on r.file_id = f.file_id
where f.status = 'loaded'
