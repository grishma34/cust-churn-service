# Customer Churn Prediction Service

Python · scikit-learn · Streamlit · AWS Lambda · Docker

Predicts customer churn for a subscription telco business so a retention team
can intervene — trained offline as a single scikit-learn Pipeline, served from
a Lambda container image, tested by non-technical users through Streamlit, and
monitored for data drift after release.

## Live demo

- **Streamlit UI:** https://cust-churn-service-4n4yy8wr2pcouij7s5nzmh.streamlit.app
- **API:** https://zbvlinpfnupzjrsrxfhjcchp440rcttr.lambda-url.ap-southeast-2.on.aws
  — `GET /health` returns the deployed model version; endpoints in
  [`docs/API_SPEC.md`](docs/API_SPEC.md)

## In four bullets

- Trained and evaluated a churn classifier on **7,043** records, reaching
  **0.843** ROC AUC on a held-out test set. Chose the decision threshold
  (**0.065**) from what a false positive and a false negative actually cost
  the business ($50 wasted retention offer vs. $450 lost customer) instead of
  defaulting to 0.5 — catching **97% of churners** at an expected cost of
  **$24.52 per customer**.
- Kept preprocessing and the model together in a single scikit-learn
  Pipeline, which prevents data leakage during training and stops training
  and serving from drifting apart — both enforced by tests: a spy on
  `Pipeline.fit` proves no validation or test row is ever fitted, and serving
  code contains no `fit` call at all.
- Deployed inference as a Lambda container image that returns the model
  version (semver + git SHA) with every prediction, so any result can be
  traced back to the exact model and commit that produced it; every
  prediction is also written to a DynamoDB audit log carrying the same
  version.
- Built a Streamlit interface so non-technical users could test predictions
  themselves, and logged input distributions to CloudWatch to watch for data
  drift after release — a PSI-based drift report flags features that shift
  beyond 0.2 against training baselines stored with the model.

## The claims, and what makes them true

| Claim | Real number | Proof |
|---|---|---|
| Churn classifier on **7,043** records | Test ROC AUC **0.843**, PR AUC 0.634 — held-out split evaluated exactly once (AST-enforced single call site) | `model_meta.json`; `tests/training/test_leakage.py` |
| Threshold from **business cost**, not 0.5 | **t = 0.065** from minimizing `$50·FP + $450·FN` on validation (analytic optimum 0.10) → 97% churner recall, $24.52 expected cost/customer | Cost-curve plot; `tests/training/test_threshold.py` |
| **No leakage / no train-serve skew** | One `Pipeline` holds all preprocessing; a spy on `Pipeline.fit` proves no validation/test row is ever fitted; serving code contains no `fit(` | Leakage-guard tests; `docs/ARCHITECTURE.md` |
| Every prediction **traceable to its model** | `model_version = <semver>+<git sha>` in every response and every DynamoDB audit item — the live audit log shows versions rolling as the pipeline deploys | End-to-end traceability test; `scripts/audit_query.py` |
| **Drift watched** after release | PSI vs. training baselines from one Logs Insights query over EMF lines; first live run correctly flagged 18/19 features (traffic was synthetic smoke payloads — a monoculture IS drift) | `scripts/drift_report.py`; `tests/unit/scripts/` |

Operations: warm p95 **265 ms** end-to-end (server median 16 ms), cold start
~10 s, image 296 MB. Total AWS cost ≈ **$0–1/month** (NFR-0008: ≤ 10 CloudWatch
metrics, keep-2 ECR lifecycle, 30-day log retention, on-demand DynamoDB + TTL,
free Function URL). Quality gate: **126 tests, 100% coverage on `src/`**,
enforced at 90% in CI.

## Architecture (short version)

```
train.py ──► model.joblib + model_meta.json ──► Docker image ──► Lambda (Function URL)
                                                                   ├─► DynamoDB  (per-prediction audit log)
Streamlit ──► POST /predict ──────────────────────────────────────►├─► CloudWatch (EMF → PSI drift report)
```

Every merge to `main` retrains on the hash-verified dataset, stamps the model
with the deploying commit's sha, builds the image, deploys via OIDC (no stored
AWS keys), applies the ECR lifecycle policy, and runs a 13-check smoke test
against production — unattended.

Full rationale in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); data model in
[`docs/DYNAMODB_DESIGN.md`](docs/DYNAMODB_DESIGN.md); what proves what in
[`docs/TEST_STRATEGY.md`](docs/TEST_STRATEGY.md).

## Run it

```bash
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# quality gate
ruff check src training tests scripts
pytest --cov=src --cov-report=term-missing --cov-fail-under=90

# train (dataset: see data/README.md — ~3 s)
python -m training.train --data data/telco.csv

# UI against the live API
streamlit run streamlit_app/app.py

# operations
python scripts/drift_report.py --hours 24     # PSI vs. training baselines
python scripts/audit_query.py by-day 2026-08-14
```

## Repository guide

Start with `PLAN.md` (build order) and `docs/REQUIREMENTS.md` (REQ-#### IDs).
`claude.md` holds the guardrails; `tasks.md` is the completed checklist with
evidence per box. Layout is mapped in `PROJECT_STRUCTURE.md`.
