# Customer Churn Prediction Service

Python · scikit-learn · Streamlit · AWS Lambda · Docker

Predicts customer churn for a subscription telco business so a retention team
can intervene — trained offline as a single scikit-learn Pipeline, served from
a Lambda container image, tested by non-technical users through Streamlit, and
monitored for data drift after release.

> **Status:** design complete, implementation not started — see `tasks.md`.
> Numbers below marked ⏳ get filled in from real runs (Phases 2, 4, 7).

## The claims, and what makes them true

| Claim | Mechanism | Proof |
|---|---|---|
| Classifier on **7,043** records, ⏳ ROC AUC | Stratified CV selection, held-out test split touched once | `model_meta.json` metrics; REQ-0002 |
| Threshold from **business cost**, not 0.5 | Minimize `$50·FP + $450·FN` on validation ⇒ t ≈ 0.10 | Cost-curve plot; `tests/training/test_threshold.py` |
| **No leakage / no train-serve skew** | Preprocessing + model in one `Pipeline`, fitted only on train | Leakage-guard test (`docs/TEST_STRATEGY.md`) |
| Every prediction **traceable to its model** | `model_version` from artifact metadata in every response + DynamoDB item | End-to-end traceability test |
| **Drift watched** after release | Input distributions → CloudWatch EMF; PSI vs. training baselines | `scripts/drift_report.py` |

## Architecture (short version)

```
train.py ──► model.joblib + model_meta.json ──► Docker image ──► Lambda (Function URL)
                                                                   ├─► DynamoDB  (per-prediction audit log)
Streamlit ──► POST /predict ──────────────────────────────────────►├─► CloudWatch (input distributions → PSI)
```

Full rationale in `docs/ARCHITECTURE.md`; endpoints in `docs/API_SPEC.md`;
audit-log data model in `docs/DYNAMODB_DESIGN.md`.

## Live demo

- Streamlit UI: https://cust-churn-service-4n4yy8wr2pcouij7s5nzmh.streamlit.app
- API: https://zbvlinpfnupzjrsrxfhjcchp440rcttr.lambda-url.ap-southeast-2.on.aws
  — `GET /health` returns the deployed model version

## Run it

```bash
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# quality gate
ruff check src training tests scripts
pytest --cov=src --cov-report=term-missing --cov-fail-under=90

# train (dataset: see data/README.md)
python -m training.train --data data/telco.csv

# serve locally (Lambda runtime emulator)
docker build -t cust-churn-service . && docker run -p 9000:8080 cust-churn-service

# UI
streamlit run streamlit_app/app.py
```

## Repository guide

Start with `PLAN.md` (build order) and `docs/REQUIREMENTS.md` (what "done"
means, as REQ-#### IDs). `claude.md` holds the guardrails; `tasks.md` is the
live checklist. Layout is mapped in `PROJECT_STRUCTURE.md`.
