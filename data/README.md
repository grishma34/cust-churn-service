# data/ — dataset access

The dataset itself is **not** committed (claude.md rule 10). Only this README
and `fixtures/` live in git.

## IBM Telco Customer Churn

- **Records:** 7,043 (+1 header row) · 21 columns (customerID + 19 features + `Churn` target)
- **Source:**
  `https://raw.githubusercontent.com/IBM/telco-customer-churn-on-icp4d/master/data/Telco-Customer-Churn.csv`
- **sha256:** `16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91`

Download and verify:

```bash
curl -sL -o data/telco.csv \
  "https://raw.githubusercontent.com/IBM/telco-customer-churn-on-icp4d/master/data/Telco-Customer-Churn.csv"
echo "16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91  data/telco.csv" | sha256sum -c
```

Training verifies this hash and records it in `model_meta.json` (REQ-0007), so
a model is traceable to the exact bytes it was trained on.

## Known data quirks (handled inside the Pipeline, REQ-0005)

- `TotalCharges` is a **string** column containing 11 blank (`" "`) values —
  all rows with `tenure == 0`. Coercion to numeric + imputation happens inside
  the Pipeline, never in handler code.
- `SeniorCitizen` is `0/1` integer while every other binary field is
  `Yes`/`No`; treated as categorical (see `src/shared/schema.py`).
- Churn base rate ≈ 26.5% — imbalanced enough that ROC AUC alone flatters;
  PR AUC and the cost at the chosen threshold are also reported (REQ-0002).

## fixtures/telco_60.csv

Committed 60-row stratified sample of the real file (seeded, ~26% churn),
force-including 2 blank-`TotalCharges` rows so tests exercise the coercion
path. Regenerate with `python scripts/make_fixture.py` (deterministic).
Tests use only this fixture — never the full dataset (NFR-0002).
