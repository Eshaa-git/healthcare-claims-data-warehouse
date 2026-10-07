-- One row per accepted source row of inpatient_claim_segment.
select * from {{ source('stage', 'inpatient_claim_segment') }}
