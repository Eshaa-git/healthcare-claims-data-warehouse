-- One row per calendar day covering every claim and drug-event date in the source (2007-2011).
select
    to_char(d, 'YYYYMMDD')::int as date_key,
    d::date as calendar_date,
    extract(year from d)::int as year,
    extract(quarter from d)::int as quarter,
    extract(month from d)::int as month,
    date_trunc('month', d)::date as month_start,
    extract(isodow from d)::int as iso_day_of_week
from generate_series('2007-01-01'::date, '2011-12-31'::date, interval '1 day') as d
