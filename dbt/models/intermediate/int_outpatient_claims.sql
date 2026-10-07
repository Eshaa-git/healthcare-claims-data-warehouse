-- Claim grain: one row per CLM_ID. Segment 1 carries the dates and attributes; amounts are
-- summed over all segments of the claim (segment 2 rows carry real payments but no dates).
-- Orphan continuation segments never reach stage (they are quarantined), so every claim has a segment 1.
with segments as (
    select * from {{ ref('stg_outpatient_claim_segment') }}
),

totals as (
    select
        claim_id,
        count(*) as segment_count,
        sum(claim_payment_amt) as claim_payment_amt,
        sum(primary_payer_paid_amt) as primary_payer_paid_amt,
        sum(blood_deductible_amt) as blood_deductible_amt,
        sum(part_b_deductible_amt) as part_b_deductible_amt,
        sum(part_b_coinsurance_amt) as part_b_coinsurance_amt
    from segments
    group by claim_id
)

select
    p.claim_id,
    p.beneficiary_id,
    extract(year from p.claim_thru_date)::int as claim_year,
    p.claim_from_date,
    p.claim_thru_date,
    
    p.provider_id,
    p.admitting_dx_code,
    p.principal_dx_code,
    t.segment_count,
    t.claim_payment_amt,
    t.primary_payer_paid_amt,
    t.blood_deductible_amt,
    t.part_b_deductible_amt,
    t.part_b_coinsurance_amt
from segments as p
join totals as t on t.claim_id = p.claim_id
where p.segment = 1
