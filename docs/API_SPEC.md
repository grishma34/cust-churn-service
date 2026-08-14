# API_SPEC.md — the inference API

The service answers at a single public URL (a Lambda Function URL — the
current one is in the README). Everything is JSON: send
`Content-Type: application/json`, get JSON back. Every response carries an
`X-Request-Id` header you can quote when tracing a request through the logs.

There are three endpoints:

| Endpoint | In one sentence |
|---|---|
| `POST /predict` | Send one customer's details, get their churn risk and a yes/no decision |
| `GET /model` | Ask "which model is running, and how good is it?" |
| `GET /health` | Ask "are you alive?" |

## POST /predict  (REQ-0008)

Send the customer's raw attributes exactly as they appear in the dataset —
no preprocessing on your side; the model's Pipeline does all of that
internally.

### Request

All 19 fields are required:

```json
{
  "gender": "Female",
  "SeniorCitizen": 0,
  "Partner": "Yes",
  "Dependents": "No",
  "tenure": 5,
  "PhoneService": "Yes",
  "MultipleLines": "No",
  "InternetService": "Fiber optic",
  "OnlineSecurity": "No",
  "OnlineBackup": "No",
  "DeviceProtection": "No",
  "TechSupport": "No",
  "StreamingTV": "Yes",
  "StreamingMovies": "No",
  "Contract": "Month-to-month",
  "PaperlessBilling": "Yes",
  "PaymentMethod": "Electronic check",
  "MonthlyCharges": 85.7,
  "TotalCharges": 420.35
}
```

**Validation rules (REQ-0013), in plain terms:**

- Every field must be present; unknown extra fields are rejected.
- Category fields (like `Contract`) must use one of the exact values the
  model was trained on — the full lists live in `src/shared/schema.py` and
  are generated from the dataset, so they can't drift from the model.
- Numbers must be numbers, and ≥ 0.
- One special case: `TotalCharges` may be `null`, because brand-new
  customers (tenure 0) haven't been billed yet — the Pipeline fills the gap.
  Every other field must have a real value.
- If several things are wrong, the response lists **all** of them at once,
  so you fix everything in one round-trip.

### Success — 200

```json
{
  "prediction_id": "01JEXAMPLEULID0000000000",
  "churn_probability": 0.72,
  "churn_predicted": true,
  "threshold": 0.065,
  "model_version": "1.0.0+ab12cd3",
  "timestamp": "2026-08-14T09:30:00Z"
}
```

What each field means:

- `churn_probability` — the model's estimate, 0 to 1.
- `threshold` — the cutoff in force, read from the model's metadata
  (chosen from business costs, not 0.5 — see `docs/ARCHITECTURE.md`).
- `churn_predicted` — simply `probability >= threshold`. The server applies
  the cutoff so no client ever invents its own (REQ-0003).
- `model_version` — exactly which model (and which git commit) produced this
  answer (REQ-0010).
- `prediction_id` — quote this to look the prediction up in the audit log
  later (`scripts/audit_query.py get <id>`).

### Bad input — 400

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input",
    "details": [
      {"field": "Contract", "issue": "must be one of: Month-to-month, One year, Two year"},
      {"field": "tenure", "issue": "must be an integer >= 0"}
    ]
  },
  "request_id": "..."
}
```

### Server error — 500

Same envelope with `code: "INTERNAL_ERROR"` and no internal details leaked.
Note: a failure to write the audit log is **not** a 500 — the prediction
still returns 200 and the write error goes to the logs (REQ-0011).

## GET /model  (REQ-0012)

The running model's identity card, straight from its `model_meta.json`
(minus the bulky per-feature statistics):

```json
{
  "model_version": "1.0.0+ab12cd3",
  "trained_at": "2026-08-10T14:00:00Z",
  "dataset_hash": "sha256:...",
  "threshold": 0.065,
  "costs": {"false_positive": 50, "false_negative": 450},
  "metrics": {"roc_auc": 0.843, "pr_auc": 0.634, "expected_cost_per_customer": 24.52}
}
```

## GET /health  (REQ-0012)

`200 {"status": "ok", "model_version": "1.0.0+ab12cd3"}` — if you get this,
the container started and its model loaded. (A container whose model fails
to load dies at startup and never serves at all.)

## All the ways a request can fail

| Status | Code | When |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Missing/unknown/bad-value fields (REQ-0013) |
| 404 | `NOT_FOUND` | Unknown path |
| 405 | `METHOD_NOT_ALLOWED` | Right path, wrong verb (e.g. GET /predict) |
| 500 | `INTERNAL_ERROR` | Unexpected failure |
| 429 | *(throttle)* | More than 5 simultaneous requests — the abuse cap (NFR-0008); retry shortly |
