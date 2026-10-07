-- One row per beneficiary per source year (2008, 2009, 2010 summary files).
select
    md5(beneficiary_id || '|' || year::text) as beneficiary_year_key,
    *
from {{ source('stage', 'beneficiary_year') }}
