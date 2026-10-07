-- Grain: one inpatient claim (CLM_ID), amounts summed across segments.
-- Join rule: the claim belongs to the beneficiary-year of its segment-1 CLM_THRU_DT.
select
    md5('inpatient|' || claim_id) as inpatient_claim_key,
    claim_id,
    beneficiary_id,
    md5(beneficiary_id || '|' || claim_year::text) as beneficiary_year_key,
    claim_year,
    to_char(claim_thru_date, 'YYYYMMDD')::int as claim_thru_date_key,
    to_char(admission_date, 'YYYYMMDD')::int as admission_date_key,
    claim_from_date,
    claim_thru_date,
    admission_date,
    discharge_date,
    length_of_stay_days,
    utilization_day_count,
    provider_id,
    drg_code,
    admitting_dx_code,
    principal_dx_code,
    segment_count,
    claim_payment_amt as medicare_claim_payment_amt,
    primary_payer_paid_amt,
    pass_thru_per_diem_amt,
    ip_deductible_amt,
    part_a_coinsurance_amt,
    blood_deductible_amt
from {{ ref('int_inpatient_claims') }}
