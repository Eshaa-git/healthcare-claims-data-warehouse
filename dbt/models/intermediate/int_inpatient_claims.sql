-- Claim grain: one row per CLM_ID. Segment 1 carries the dates and attributes; amounts are
-- summed over all segments of the claim (segment 2 rows carry real payments but no dates).
-- Orphan continuation segments never reach stage (they are quarantined), so every claim has a segment 1.
with segments as (
    select * from {{ ref('stg_inpatient_claim_segment') }}
),

totals as (
    select
        claim_id,
        count(*) as segment_count,
        sum(claim_payment_amt) as claim_payment_amt,
        sum(primary_payer_paid_amt) as primary_payer_paid_amt,
        sum(pass_thru_per_diem_amt) as pass_thru_per_diem_amt,
        sum(ip_deductible_amt) as ip_deductible_amt,
        sum(part_a_coinsurance_amt) as part_a_coinsurance_amt,
        sum(blood_deductible_amt) as blood_deductible_amt
    from segments
    group by claim_id
)

select
    p.claim_id,
    p.beneficiary_id,
    extract(year from p.claim_thru_date)::int as claim_year,
    p.claim_from_date,
    p.claim_thru_date,
    p.admission_date,
    p.discharge_date,
    p.drg_code,
    p.utilization_day_count,
    (p.discharge_date - p.admission_date) as length_of_stay_days,
    p.provider_id,
    p.admitting_dx_code,
    p.principal_dx_code,
    t.segment_count,
    t.claim_payment_amt,
    t.primary_payer_paid_amt,
    t.pass_thru_per_diem_amt,
    t.ip_deductible_amt,
    t.part_a_coinsurance_amt,
    t.blood_deductible_amt
from segments as p
join totals as t on t.claim_id = p.claim_id
where p.segment = 1
