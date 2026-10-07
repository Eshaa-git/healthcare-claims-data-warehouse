-- Medicare claim payment (CLM_PMT_AMT) by month of segment-1 CLM_THRU_DT. This is the Medicare
-- payment on institutional claims only; it is not total cost of care (no carrier, beneficiary
-- cost-sharing or drug spend). Negative payments are documented adjustments and are included.
with claims as (
    select 'inpatient' as claim_type, date_trunc('month', claim_thru_date)::date as month_start,
           beneficiary_id, medicare_claim_payment_amt
    from {{ ref('fact_inpatient_claim') }}
    union all
    select 'outpatient', date_trunc('month', claim_thru_date)::date,
           beneficiary_id, medicare_claim_payment_amt
    from {{ ref('fact_outpatient_claim') }}
)

select
    month_start,
    claim_type,
    count(*) as claim_count,
    count(distinct beneficiary_id) as beneficiaries_with_claims,
    sum(medicare_claim_payment_amt) as medicare_claim_payment_amt,
    count(*) filter (where medicare_claim_payment_amt < 0) as negative_payment_claims
from claims
group by month_start, claim_type
