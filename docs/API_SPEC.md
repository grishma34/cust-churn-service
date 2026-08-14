# API_SPEC.md — Inference API

Single Lambda Function URL. All bodies are JSON (`Content-Type:
application/json`). Every response carries `X-Request-Id`.

## POST /predict  (REQ-0008)

Predict churn for one customer from raw feature values — the same columns the
Pipeline was trained on, no client-side preprocessing.

### Request

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

Validation (REQ-0013): all 19 fields required; categorical values must be in
the training domain (enumerated in `src/shared/schema.py`, generated from the
training data); numerics must be numbers ≥ 0. `TotalCharges` may be `null`
(blank in the source data for tenure-0 customers; imputed inside the
Pipeline) — every other field is non-null. Unknown fields are rejected. All
problems are reported in one response.

### Response 200

```json
{
  "prediction_id": "01JEXAMPLEULID0000000000",
  "churn_probability": 0.72,
  "churn_predicted": true,
  "threshold": 0.10,
  "model_version": "1.0.0+ab12cd3",
  "timestamp": "2026-08-14T09:30:00Z"
}
```

`churn_predicted = churn_probability >= threshold`, where `threshold` comes
from `model_meta.json` (REQ-0003) — the client never applies its own cutoff.
`model_version` likewise comes from the artifact metadata (REQ-0010).

### Response 400 — validation failure

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

### Response 500 — internal error

Same envelope, `code: "INTERNAL_ERROR"`, no stack trace in the body.
Note: a DynamoDB logging failure is **not** a 500 — the prediction still
returns 200 (REQ-0011); the write error is logged.

## GET /model  (REQ-0012)

Returns the deployed model's metadata, verbatim from `model_meta.json`:

```json
{
  "model_version": "1.0.0+ab12cd3",
  "trained_at": "2026-08-10T14:00:00Z",
  "dataset_hash": "sha256:...",
  "threshold": 0.10,
  "costs": {"false_positive": 50, "false_negative": 450},
  "metrics": {"roc_auc": 0.845, "pr_auc": 0.65, "expected_cost_per_customer": 21.4}
}
```

(Baseline distributions are in the artifact but omitted here for payload size.)

## GET /health  (REQ-0012)

`200 {"status": "ok", "model_version": "1.0.0+ab12cd3"}` once the artifact is
loaded. A container that cannot load the artifact fails at init — it never
serves.

## Errors summary

| Status | Code | When |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Bad/missing/unknown fields (REQ-0013) |
| 404 | `NOT_FOUND` | Unknown path |
| 405 | `METHOD_NOT_ALLOWED` | e.g. GET /predict |
| 500 | `INTERNAL_ERROR` | Unexpected failure |
