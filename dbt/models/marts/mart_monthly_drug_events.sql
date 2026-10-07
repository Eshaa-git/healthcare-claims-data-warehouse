-- Part D events by month of service. Gross drug cost is TOT_RX_CST_AMT (codebook PDE-8);
-- patient pay is PTNT_PAY_AMT (PDE-7).
select
    date_trunc('month', service_date)::date as month_start,
    count(*) as drug_event_count,
    count(distinct beneficiary_id) as beneficiaries_with_events,
    sum(gross_drug_cost_amt) as gross_drug_cost_amt,
    sum(patient_pay_amt) as patient_pay_amt
from {{ ref('fact_drug_event') }}
group by 1
