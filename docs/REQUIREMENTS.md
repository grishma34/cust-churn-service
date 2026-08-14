# REQUIREMENTS.md — what the system must do

Every requirement has a permanent ID (`REQ-####` for behavior, `NFR-####`
for qualities like speed and cost). Code comments, tests, and the checklist
all cite these IDs — that's how you trace a line of code back to the reason
it exists. IDs are never reused or renumbered.

## Context, in two sentences

Predict which customers of a subscription telco are likely to cancel
("churn"), so a retention team can intervene before they do. The dataset is
IBM's public Telco Customer Churn sample (7,043 customers, 19 attributes, a
yes/no churn label); the service must be usable by non-technical people, and
every prediction must be traceable to the exact model that made it.

---

## Functional requirements

### Training & evaluation

- **REQ-0001 — Repeatable training.** Train a churn classifier with one
  command (`python -m training.train`), not a notebook ritual. Fixed random
  seed, pinned library versions.
- **REQ-0002 — Honest evaluation.** Pick the model by 5-fold
  cross-validation on training data only. Final scores (ROC AUC, PR AUC,
  the confusion matrix at the chosen threshold) come from a held-out test
  split that is scored **exactly once**. Target: test ROC AUC ≥ 0.83.
- **REQ-0003 — Cost-based threshold.** The probability→decision cutoff is
  chosen by minimizing real business cost on the validation split — never
  defaulted to 0.5. The cost model (adjustable in `training/config.py`):
  a wasted retention offer (false positive) costs **$50**; a missed churner
  (false negative) costs **$450**. With honest probabilities the theoretical
  best cutoff is 50/(50+450) = 0.10; the empirical sweep and the chosen
  value are both recorded in the model's metadata.
- **REQ-0004 — Trustworthy probabilities.** The cost math above only works
  if "30%" really means 30%, so calibration is measured on validation; if
  it's poor, the model is automatically wrapped in a calibrator
  (`CalibratedClassifierCV`).

### The Pipeline & the saved model

- **REQ-0005 — One Pipeline.** Every preprocessing step (filling missing
  values, encoding categories, scaling) lives inside a single scikit-learn
  `Pipeline` together with the classifier. `predict` accepts raw values
  exactly as the API receives them. No preprocessing code exists anywhere
  else.
- **REQ-0006 — No leakage.** Nothing is ever fitted on validation or test
  data. A test enforces this by spying on every `fit` call during a real
  training run (see `docs/TEST_STRATEGY.md`).
- **REQ-0007 — A self-describing artifact.** Training outputs the Pipeline
  (`model.joblib`) plus `model_meta.json` containing: the version
  (`<semver>+<git sha>`, e.g. `1.0.0+ab12cd3`), when it was trained, a
  checksum of the exact dataset bytes, the chosen threshold and the costs
  behind it, all evaluation scores, and per-feature statistics of the
  training data (used later for drift detection).

### The inference service

- **REQ-0008 — The predict endpoint.** `POST /predict` takes one customer's
  raw attributes and returns `churn_probability`, `churn_predicted`
  (probability ≥ threshold), `threshold`, `model_version`, and a
  `prediction_id`. Full contract in `docs/API_SPEC.md`.
- **REQ-0009 — Ship as a container.** Inference runs as a Lambda container
  image (Docker → ECR). The model files are baked into the image and loaded
  once per container, at startup — so one image is permanently one model.
- **REQ-0010 — Version in every answer.** Every response carries the
  `model_version` read from `model_meta.json` — never a constant in code —
  so any result anyone has ever seen can be traced to the artifact that
  produced it.
- **REQ-0011 — Audit every prediction, without risking the prediction.**
  Each prediction is written to DynamoDB (inputs, outputs, version,
  timestamp — see `docs/DYNAMODB_DESIGN.md`). The write is best-effort: if
  it fails, the caller still gets their prediction and the failure is
  logged.
- **REQ-0012 — Introspection endpoints.** `GET /model` returns the model's
  metadata; `GET /health` returns 200 with the version once the model is
  loaded. A container that cannot load its model must fail at startup, not
  serve.
- **REQ-0013 — Validate before predicting.** Bad input (missing or unknown
  fields, values outside the trained vocabulary, negative numbers) returns
  400 with a list of every problem. The model is never called on
  unvalidated input.

### Monitoring & the human interface

- **REQ-0014 — Log what the model is seeing.** Each request's input values
  are emitted to CloudWatch as structured log lines (Embedded Metric
  Format). Extracted chart-metrics are capped per NFR-0008; the full detail
  rides in the log line itself, queryable later. This is the raw material
  for drift detection.
- **REQ-0015 — A drift report.** A script compares recent live input
  distributions (from the REQ-0014 logs) against the training baselines
  stored in `model_meta.json`, using PSI. Any feature scoring above 0.2 is
  flagged, and the script exits non-zero so it can gate a schedule.
- **REQ-0016 — A face for non-technical users.** A Streamlit web form
  (dropdowns for categories, number fields with sane bounds) calls the
  deployed API and shows the probability, the decision with its reasoning,
  and the model version. It talks to the API only — it never contains the
  model.

## Non-functional requirements

- **NFR-0001 — Coverage gate.** Test coverage ≥ 90% on `src/`
  (`pytest --cov=src --cov-fail-under=90`), enforced in CI.
- **NFR-0002 — No live AWS in tests.** All AWS interaction in tests goes
  through moto (in-memory fake); the model comes from a fixture artifact.
  No credentials, no network.
- **NFR-0003 — Reproducible training.** Same data + same config ⇒ same
  metrics. Fixed seeds, pinned dependencies.
- **NFR-0004 — Least privilege.** The inference function may append to its
  one table and write its own logs/metrics — nothing else. It cannot even
  read the audit log.
- **NFR-0005 — No secrets anywhere.** Not in code, not in the image, not in
  the template. Configuration via environment variables; deploys via OIDC
  (no stored AWS keys).
- **NFR-0006 — Fast enough, small enough.** Warm-request p95 under 300 ms
  (model loaded at startup, not per request); container image under 1 GB
  (no training libraries inside).
- **NFR-0007 — Debuggable logs.** Structured JSON log lines with a request
  ID on every invocation.
- **NFR-0008 — Total AWS cost under $5/month** at demo traffic, treated as
  a hard requirement. The mechanisms:
  - no always-on compute — Lambda + a free Function URL, no API Gateway,
    no VPC/NAT;
  - DynamoDB on-demand billing, records auto-delete after 90 days;
  - ECR keeps only the 2 most recent images (current + rollback);
  - CloudWatch log retention 30 days;
  - **≤ 10 extracted custom metrics** (the always-free tier) — enforced by
    a unit test; categorical detail stays in log lines and is read via
    Logs Insights;
  - abuse backstops: **reserved concurrency 5** on the function (a request
    flood throttles instead of billing) and an **account-level $5/month
    budget** emailing at 80% actual / 100% forecasted spend.

  Measured steady state ≈ $0–1/month.
