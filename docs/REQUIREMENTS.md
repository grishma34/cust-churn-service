# REQUIREMENTS.md — Customer Churn Prediction Service

Every requirement has a stable ID. IDs are never reused or renumbered.
`PLAN.md` phases and `TASKS.md` checkboxes reference these IDs.

## Context

Predict which customers of a subscription telco business are likely to churn,
so the retention team can intervene. Dataset: IBM Telco Customer Churn
(7,043 records, 19 features, binary `Churn` target). The service must be
usable by non-technical users and every prediction must be traceable to the
exact model that produced it.

---

## Functional requirements

### Model training & evaluation

- **REQ-0001** — Train a binary churn classifier on the Telco dataset. Training
  is a repeatable script (`python -m training.train`), not a notebook-only
  artifact; fixed random seed, pinned dependencies.
- **REQ-0002** — Model selection by stratified 5-fold cross-validated ROC AUC on
  the training split; final metrics (ROC AUC, PR AUC, confusion matrix at the
  chosen threshold) reported on a held-out test split that is touched exactly
  once. Target: ROC AUC ≥ 0.83 on the test split.
- **REQ-0003** — The decision threshold is chosen by minimizing expected
  business cost on a validation split, **not** defaulted to 0.5. Cost model
  (documented, adjustable in `training/config.py`):
  - False positive (retention offer to a customer who would have stayed): **$50**
  - False negative (churner missed, lost customer): **$450**
  - With calibrated probabilities the theoretical optimum is
    t* = C_FP / (C_FP + C_FN) = 0.10; the empirical cost curve and the chosen
    threshold are both recorded in the model metadata.
- **REQ-0004** — Predicted probabilities are calibrated (reliability curve
  inspected; `CalibratedClassifierCV` applied if the base model is
  poorly calibrated), because the cost-based threshold is only meaningful on
  calibrated probabilities.

### Pipeline & artifact

- **REQ-0005** — All preprocessing (imputation, encoding, scaling) and the
  estimator live in **one** scikit-learn `Pipeline` object. `pipeline.predict`
  accepts raw feature values as they arrive from the API. No preprocessing code
  exists outside the Pipeline.
- **REQ-0006** — Nothing is fitted outside the training split: `fit` /
  `fit_transform` are called only on training data; the test split flows through
  `transform`/`predict` only. A test guards this (see `docs/TEST_STRATEGY.md`).
- **REQ-0007** — The serialized artifact is the Pipeline (joblib) plus a
  `model_meta.json` containing: `model_version` (semver + short git SHA, e.g.
  `1.0.0+ab12cd3`), training timestamp, dataset hash, chosen threshold, cost
  parameters, test-split metrics, and training-data baseline distributions
  (numeric means/stds/quantiles, categorical frequencies) for drift comparison.

### Inference service

- **REQ-0008** — `POST /predict` accepts one customer's raw features and returns
  `churn_probability`, `churn_predicted` (probability ≥ threshold),
  `threshold`, `model_version`, and `prediction_id`. See `docs/API_SPEC.md`.
- **REQ-0009** — Inference runs as a **Lambda container image** (Docker, pushed
  to ECR). The Pipeline and metadata are baked into the image and loaded once
  per container lifetime, outside the handler.
- **REQ-0010** — Every response includes the `model_version` from
  `model_meta.json` — never hardcoded — so any logged prediction can be traced
  to the artifact that produced it.
- **REQ-0011** — Every prediction is written to DynamoDB (prediction ID, inputs,
  probability, decision, model version, timestamp) per
  `docs/DYNAMODB_DESIGN.md`. Logging failure must not fail the prediction
  response (best-effort write, error logged).
- **REQ-0012** — `GET /model` returns the model metadata (version, threshold,
  metrics, trained-at); `GET /health` returns 200 with the model version once
  the artifact is loaded.
- **REQ-0013** — Invalid input (missing/unknown fields, out-of-domain values)
  returns 400 with a structured error envelope; the model is never called on
  unvalidated input.

### Monitoring & UI

- **REQ-0014** — Each request's input feature values are emitted to CloudWatch
  via Embedded Metric Format. Extracted custom metrics are capped per NFR-0008
  (numeric features + prediction counts); the full feature payload rides in the
  same EMF log line, so categorical distributions are queryable without
  per-dimension metric cost. This is the raw material for drift detection.
- **REQ-0015** — A drift report script compares recent input distributions
  (numerics from metric statistics, categoricals from a Logs Insights query
  over the EMF lines) against the training baselines in `model_meta.json`
  using PSI (Population Stability Index); PSI > 0.2 on any feature is flagged.
- **REQ-0016** — A Streamlit app lets a non-technical user fill in customer
  attributes via form controls (dropdowns for categoricals, sliders/inputs for
  numerics), calls the deployed API, and displays probability, decision,
  and model version. It talks to the API only — it never loads the model.

## Non-functional requirements

- **NFR-0001** — Test coverage ≥ 90% on `src/` (`pytest --cov=src
  --cov-fail-under=90`); gate enforced in CI.
- **NFR-0002** — No live AWS in tests: moto for DynamoDB/CloudWatch, a stub
  model artifact fixture for the handler. No real credentials, no network.
- **NFR-0003** — Training is reproducible: same data + same config ⇒ same
  metrics (fixed seeds, pinned `requirements.txt`).
- **NFR-0004** — Least-privilege IAM: the inference function may `PutItem` to
  its table and `PutLogEvents`/metric-write only; nothing else.
- **NFR-0005** — No secrets in code, image, or template; config via environment
  variables / SAM parameters.
- **NFR-0006** — Warm-invocation latency < 300 ms p95 (model loaded at init,
  not per request); container image kept < 1 GB (slim base, no training deps in
  the inference image).
- **NFR-0007** — Structured JSON logs with request ID on every invocation.
- **NFR-0008** — Total AWS cost < **$5/month** at demo traffic. Mechanisms:
  no always-on compute (Lambda + Function URL, no API Gateway, no VPC/NAT);
  DynamoDB on-demand with 90-day TTL; ECR lifecycle policy retaining ≤ 2 image
  versions; CloudWatch log retention 30 days; **≤ 10 extracted custom metrics**
  (the always-free tier) — numeric features and headline counts become metrics,
  full categorical distributions stay in the EMF log lines and are read by the
  drift report via Logs Insights instead of metric statistics. Abuse backstops
  (added post-v1.0.0): reserved concurrency of 5 on the function, so a
  request flood throttles instead of billing, and an account-level $5/month
  AWS Budget with email alerts at 80% actual and 100% forecasted. Expected
  steady state ≈ $0–1/month.
