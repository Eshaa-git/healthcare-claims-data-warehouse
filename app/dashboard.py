"""Streamlit dashboard over the published `marts` schema (read-only dashboard role)."""

from __future__ import annotations

import os

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import URL, create_engine, text

st.set_page_config(page_title="Claims Warehouse", layout="wide")


@st.cache_resource
def get_engine():
    url = URL.create(
        "postgresql+psycopg",
        username="claims_dashboard",
        password=os.environ["DASHBOARD_PASSWORD"],
        host=os.environ.get("WAREHOUSE_HOST", "127.0.0.1"),
        port=int(os.environ.get("WAREHOUSE_PORT", "5432")),
        database=os.environ.get("WAREHOUSE_DB", "claims_warehouse"),
    )
    return create_engine(url, pool_pre_ping=True)


@st.cache_data(ttl=60)
def query(sql: str) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn)


def download(df: pd.DataFrame, name: str) -> None:
    st.download_button(
        f"Download {name}.csv", df.to_csv(index=False).encode(), f"{name}.csv", "text/csv", key=name
    )


st.title("Synthetic Medicare claims warehouse")
st.caption(
    "Data: CMS 2008–2010 DE-SynPUF Sample 1 (fully synthetic). CMS warns that analyses of this file "
    "about real Medicare beneficiaries or spending will be misleading; the figures below demonstrate "
    "the pipeline, not Medicare trends."
)

try:
    info = query("select run_id, published_at, reconciliation_checks from marts.publication_info")
except Exception as exc:  # noqa: BLE001
    st.error(f"No published marts yet ({type(exc).__name__}). Run the pipeline first.")
    st.stop()

row = info.iloc[0]
st.markdown(
    f"**Published run** `{row.run_id}` at {row.published_at:%Y-%m-%d %H:%M UTC} · "
    f"{row.reconciliation_checks} reconciliation checks passed before publication."
)

util = query("select * from marts.mart_inpatient_utilization_yearly order by year")
payments = query("select * from marts.mart_monthly_claim_payments order by month_start, claim_type")
drugs = query("select * from marts.mart_monthly_drug_events order by month_start")
quality = query("select * from marts.mart_data_quality order by file_id, reason_code")
quality["reason_code"] = quality["reason_code"].fillna("(none)")

files = quality.drop_duplicates("file_id")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Beneficiary-years", f"{int(util.beneficiary_years.sum()):,}")
c2.metric("Inpatient claims", f"{int(util.admissions.sum()):,}")
c3.metric(
    "Outpatient claims",
    f"{int(payments.loc[payments.claim_type == 'outpatient', 'claim_count'].sum()):,}",
)
c4.metric("Drug events", f"{int(drugs.drug_event_count.sum()):,}")
c5.metric("Quarantined rows", f"{int(files.rejected_count.sum()):,}")

st.subheader("Monthly Medicare claim payments")
st.caption(
    "Sum of CLM_PMT_AMT by month of the claim's segment-1 thru date. Institutional inpatient and "
    "outpatient claims only — not total cost of care. Negative payments (documented adjustments) "
    "are included."
)
chart = (
    alt.Chart(payments)
    .mark_line(point=True)
    .encode(
        x=alt.X("month_start:T", title="Month"),
        y=alt.Y("medicare_claim_payment_amt:Q", title="Medicare claim payment (USD)"),
        color=alt.Color("claim_type:N", title="Claim type"),
        tooltip=["month_start:T", "claim_type", "claim_count", "medicare_claim_payment_amt"],
    )
    .properties(height=320)
)
st.altair_chart(chart, use_container_width=True)
download(payments, "monthly_claim_payments")

left, right = st.columns(2)
with left:
    st.subheader("Admissions per 1,000 beneficiary-years")
    st.caption(
        "Denominator: cohort beneficiaries with a summary record that year (not adjusted for "
        "partial-year enrollment). Observed inpatient days = discharge − admission date."
    )
    st.altair_chart(
        alt.Chart(util)
        .mark_bar()
        .encode(
            x=alt.X("year:O", title="Year"),
            y=alt.Y("admissions_per_1000_beneficiary_years:Q", title="Admissions per 1,000"),
            tooltip=list(util.columns),
        )
        .properties(height=260),
        use_container_width=True,
    )
    st.dataframe(util, hide_index=True, use_container_width=True)
    download(util, "inpatient_utilization_yearly")
with right:
    st.subheader("Part D drug events per month")
    st.caption(
        "Count of prescription drug events by service month; gross drug cost is TOT_RX_CST_AMT."
    )
    st.altair_chart(
        alt.Chart(drugs)
        .mark_area(opacity=0.7)
        .encode(
            x=alt.X("month_start:T", title="Month"),
            y=alt.Y("drug_event_count:Q", title="Drug events"),
            tooltip=list(drugs.columns),
        )
        .properties(height=260),
        use_container_width=True,
    )
    download(drugs, "monthly_drug_events")

st.subheader("Data quality: accepted and quarantined rows")
st.caption(
    "Every source row is either accepted into the warehouse or quarantined with a reason code. "
    "Quarantined rows are excluded from all charts above."
)
st.dataframe(quality, hide_index=True, use_container_width=True)
download(quality, "data_quality")
