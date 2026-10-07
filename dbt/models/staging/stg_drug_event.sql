-- One row per accepted source row of drug_event.
select * from {{ source('stage', 'drug_event') }}
