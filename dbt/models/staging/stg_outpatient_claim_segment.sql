-- One row per accepted source row of outpatient_claim_segment.
select * from {{ source('stage', 'outpatient_claim_segment') }}
