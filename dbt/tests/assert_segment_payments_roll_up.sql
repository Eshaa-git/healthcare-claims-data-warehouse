-- Claim facts must carry every staged segment payment (no segment lost or double counted).
with staged as (
    select 'inpatient' as claim_type, sum(claim_payment_amt) as amt from {{ ref('stg_inpatient_claim_segment') }}
    union all
    select 'outpatient', sum(claim_payment_amt) from {{ ref('stg_outpatient_claim_segment') }}
),
facts as (
    select 'inpatient' as claim_type, sum(medicare_claim_payment_amt) as amt from {{ ref('fact_inpatient_claim') }}
    union all
    select 'outpatient', sum(medicare_claim_payment_amt) from {{ ref('fact_outpatient_claim') }}
)
select s.claim_type, s.amt as staged_amt, f.amt as fact_amt
from staged s join facts f using (claim_type)
where s.amt is distinct from f.amt
