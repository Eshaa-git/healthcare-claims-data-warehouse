# Run manual__20261007T221339Z

- Status: failed; source: cms; commit: 61313ec0e7f56a8a82e2d3285897d6c15bae1fde
- Reconciliation: 0/0 checks passed

Cohort: 1000 beneficiaries (sha256 208419882777…)

| Step | Attempt | Status | Seconds |
|---|---|---|---|
| acquire | 1 | succeeded | 2.680 |
| cohort | 1 | succeeded | 17.403 |
| stage | 1 | failed | 8.432 |

| File | Rows | Accepted | Quarantined | Attempts |
|---|---|---|---|---|
| de1_0_2008_beneficiary_summary_file_sample_1.zip | 1000 | 1000 | 0 | 1 |
| de1_0_2009_beneficiary_summary_file_sample_1.zip | 982 | 982 | 0 | 1 |
| de1_0_2010_beneficiary_summary_file_sample_20.zip | 968 | 968 | 0 | 1 |
| de1_0_2008_to_2010_inpatient_claims_sample_1.zip | 580 | 580 | 0 | 1 |
| de1_0_2008_to_2010_outpatient_claims_sample_1.zip | 7117 | 7116 | 1 | 1 |
| DE1_0_2008_to_2010_Prescription_Drug_Events_Sample_1.zip | 45269 | 45269 | 0 | 2 |

| Dataset | Reason | Rows |
|---|---|---|
| outpatient_claims | orphan_segment | 1 |

Failed: stage attempt 1
