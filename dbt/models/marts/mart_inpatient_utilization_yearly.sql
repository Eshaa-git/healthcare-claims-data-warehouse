-- Denominator: beneficiary-years = cohort beneficiaries with a summary record for that year
-- (not adjusted for partial-year enrollment or death). Numerator: inpatient claims whose
-- segment-1 CLM_THRU_DT falls in the year. Observed inpatient days = discharge - admission.
with denominators as (
    select year, count(*) as beneficiary_years
    from {{ ref('dim_beneficiary_year') }}
    group by year
),

stays as (
    select
        claim_year as year,
        count(*) as admissions,
        sum(length_of_stay_days) as observed_inpatient_days,
        sum(utilization_day_count) as utilization_days
    from {{ ref('fact_inpatient_claim') }}
    group by claim_year
)

select
    d.year,
    d.beneficiary_years,
    coalesce(s.admissions, 0) as admissions,
    round(1000.0 * coalesce(s.admissions, 0) / d.beneficiary_years, 2)
        as admissions_per_1000_beneficiary_years,
    coalesce(s.observed_inpatient_days, 0) as observed_inpatient_days,
    coalesce(s.utilization_days, 0) as utilization_days,
    round(s.observed_inpatient_days::numeric / nullif(s.admissions, 0), 2) as mean_length_of_stay_days
from denominators as d
left join stays as s on s.year = d.year
