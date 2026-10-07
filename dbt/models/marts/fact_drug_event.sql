-- Grain: one Part D prescription drug event (PDE_ID). Joins to the beneficiary-year of SRVC_DT.
select
    md5('pde|' || pde_id) as drug_event_key,
    pde_id,
    beneficiary_id,
    md5(beneficiary_id || '|' || extract(year from service_date)::int::text) as beneficiary_year_key,
    extract(year from service_date)::int as service_year,
    to_char(service_date, 'YYYYMMDD')::int as service_date_key,
    service_date,
    product_service_id,
    quantity_dispensed,
    days_supply,
    patient_pay_amt,
    gross_drug_cost_amt
from {{ ref('stg_drug_event') }}
