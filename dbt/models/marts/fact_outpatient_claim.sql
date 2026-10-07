-- Grain: one outpatient claim (CLM_ID), amounts summed across segments.
-- Join rule: the claim belongs to the beneficiary-year of its segment-1 CLM_THRU_DT.
select
    md5('outpatient|' || claim_id) as outpatient_claim_key,
    claim_id,
    beneficiary_id,
    md5(beneficiary_id || '|' || claim_year::text) as beneficiary_year_key,
    claim_year,
    to_char(claim_thru_date, 'YYYYMMDD')::int as claim_thru_date_key,
    claim_from_date,
    claim_thru_date,
    provider_id,
    admitting_dx_code,
    principal_dx_code,
    segment_count,
    claim_payment_amt as medicare_claim_payment_amt,
    primary_payer_paid_amt,
    blood_deductible_amt,
    part_b_deductible_amt,
    part_b_coinsurance_amt
from {{ ref('int_outpatient_claims') }}
