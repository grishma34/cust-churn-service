# ARCHITECTURE.md — Customer Churn Prediction Service

## Overview

Two halves that share one artifact:

1. **Training (offline, local):** a script builds a single scikit-learn
   Pipeline (preprocessing + classifier), evaluates it, chooses the decision
   threshold from business costs, and serializes `model.joblib` +
   `model_meta.json`.
2. **Serving (online, AWS):** a Lambda container image bakes that artifact in,
   answers `POST /predict`, logs every prediction to DynamoDB, and emits input
   distributions to CloudWatch. A Streamlit app is the human front door.

```
             ┌────────────── offline ──────────────┐
 telco.csv ──► training/train.py ──► artifacts/
                (Pipeline + CV +      ├─ model.joblib
                 cost threshold)      └─ model_meta.json
                                            │  baked into image at docker build
             ┌────────────── online ────────▼──────────────────────────┐
 Streamlit ──► Lambda Function URL ──► inference handler               │
   (user)      (POST /predict)         ├─ validate input (REQ-0013)    │
                                       ├─ pipeline.predict_proba       │
                                       ├─ decide via stored threshold  │
                                       ├─ DynamoDB PutItem (REQ-0011)──┼──► churn-predictions table
                                       └─ EMF metrics (REQ-0014) ──────┼──► CloudWatch → drift report
                                       response: probability, decision,│
                                       threshold, model_version        │
             └─────────────────────────────────────────────────────────┘
```

## The load-bearing decisions

### One Pipeline object (REQ-0005/0006)

Imputation, one-hot encoding, scaling, and the classifier are composed with
`ColumnTransformer` + `Pipeline` and fitted as a unit on the training split
only. Consequences:

- **No leakage:** encoders/scalers never see validation or test rows during
  `fit`; cross-validation clones the whole Pipeline per fold.
- **No train/serve skew:** serving calls the exact fitted object; there is no
  second implementation of preprocessing to drift out of sync. The handler
  passes raw request fields straight into `pipeline.predict_proba`.

### Cost-based threshold (REQ-0003)

A missed churner (~$450 lost) costs ~9× a wasted retention offer (~$50). The
threshold is chosen by sweeping t over the validation split and minimizing
`C_FP·FP(t) + C_FN·FN(t)`; with calibrated probabilities this lands near
`C_FP/(C_FP+C_FN) = 0.10`, far from the 0.5 default. The chosen t, the cost
curve, and both cost constants are stored in `model_meta.json` — the server
reads the threshold from metadata, never hardcodes it.

### Versioned artifact in the image (REQ-0007/0009/0010)

`model_version = <semver>+<git-sha>` is written into `model_meta.json` at
training time. The Dockerfile copies `artifacts/` into the image, so an image
digest maps to exactly one model. Every API response and every DynamoDB item
carries `model_version` — "which model said this?" is always answerable.

Deploying a new model = retrain → rebuild image → push to ECR → update the
Lambda. Rollback = point the Lambda at the previous image tag.

### Serving stack

- **Lambda container image** (`public.ecr.aws/lambda/python:3.14` base) rather
  than a zip: scikit-learn + numpy exceed the 250 MB zip limit; a container
  also makes the runtime bit-identical between local tests and production.
- **Lambda Function URL** instead of API Gateway: one endpoint, no routing
  needs beyond it, and the Streamlit client is the only consumer. (Swap for
  API Gateway later if auth/throttling is needed; the handler is
  transport-agnostic.)
- **Model load at init:** the artifact is deserialized at module import, once
  per container, keeping warm p95 under the NFR-0006 budget.

### Observability split

- **DynamoDB** is the per-prediction audit log — point lookups and
  "what did model X predict" queries (`docs/DYNAMODB_DESIGN.md`).
- **CloudWatch EMF** is the aggregate view — input feature distributions over
  time. The drift script (REQ-0015) pulls metric statistics and compares them
  to the training baselines stored in `model_meta.json` via PSI.

They intentionally overlap: DynamoDB answers "this prediction," CloudWatch
answers "predictions lately."

### Cost ceiling: < $5/month (NFR-0008)

Everything above is chosen to have no idle cost: Lambda bills per request,
Function URL is free (API Gateway is not), DynamoDB is on-demand with a 90-day
TTL, and there is no VPC/NAT or always-on compute. The two line items that
could break the budget, and how they're capped:

- **CloudWatch custom metrics** — $0.30/metric/month past the 10 always-free.
  Naively metric-izing 19 features (with categorical values as dimensions)
  would be dozens of billable metrics. Instead, EMF *extracts* ≤ 10 metrics
  (the 3 numerics, prediction count, positive-rate, probability); everything
  else stays as fields in the same EMF log line, which costs only log ingest
  and is queryable via Logs Insights (pennies at demo volume). Log retention
  is set to 30 days.
- **ECR storage** — ~$0.10/GB-month; a ~1 GB sklearn image accumulating tags
  would creep. A lifecycle policy keeps the 2 most recent images (current +
  rollback target).

Expected steady state ≈ $0–1/month at demo traffic.

### Streamlit as a thin client (REQ-0016)

The Streamlit app holds no model and no AWS credentials — it only POSTs to the
Function URL. That keeps exactly one inference path in existence (the Lambda),
so the demo UI can never disagree with production behavior.

## Layering (mirrors `serverless-order-api`)

```
src/
  handlers/     # Lambda entry: parse event → call service → HTTP response
  services/     # prediction service: validate → predict → log; no boto3
  data/         # DynamoDB repository + CloudWatch EMF emitter (all boto3 here)
  model/        # artifact loading, schema of model_meta.json
  shared/       # responses, errors, logging, input schema
training/       # offline only; never imported by src/
```

`training/` and `src/` share nothing but the artifact contract
(`model.joblib` + `model_meta.json`). Training dependencies (pandas,
matplotlib) never enter the inference image.
