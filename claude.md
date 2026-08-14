# CLAUDE.md — Customer Churn Prediction Service

Operating instructions for AI agents (Claude Code) working in this repository.

## What this project is

A churn-prediction service, trained offline and served on AWS:

- **Model:** scikit-learn classifier on the IBM Telco Customer Churn dataset
  (7,043 records); preprocessing + estimator in **one** `Pipeline` object
- **Threshold:** chosen from business costs (FP $50 / FN $450), not 0.5
- **Serving:** Lambda **container image** (Docker → ECR), Function URL;
  every response carries `model_version` from the artifact metadata
- **Audit:** every prediction written to DynamoDB (no-scan single-table design)
- **Monitoring:** input distributions to CloudWatch via EMF; PSI drift report
- **UI:** Streamlit thin client — calls the API, holds no model
- **IaC:** AWS SAM (`template.yaml`); **CI/CD:** GitHub Actions on merge to main
- **Tests:** pytest + moto, coverage gate **90%**, never against live AWS

## Source of truth documents

| Question | Read this first |
|---|---|
| What are we building, in what order? | `PLAN.md` |
| What must the system do? | `docs/REQUIREMENTS.md` (REQ-#### / NFR-####) |
| How is it structured, and why? | `docs/ARCHITECTURE.md` |
| Where does every file go? | `PROJECT_STRUCTURE.md` |
| What are the endpoints? | `docs/API_SPEC.md` |
| How is the audit log modeled? | `docs/DYNAMODB_DESIGN.md` |
| How do we test? | `docs/TEST_STRATEGY.md` |
| What's left to do? | `tasks.md` |

When code and docs disagree, stop and reconcile — update the doc in the same
commit as the code change.

## Hard rules (guardrails)

1. **One Pipeline.** All preprocessing lives inside the scikit-learn
   `Pipeline`. Never write transform logic in `src/` — if serving needs a new
   transformation, it goes into `training/features.py` and ships in the next
   artifact. (REQ-0005)
2. **Never fit outside the training split.** No `fit`/`fit_transform` on
   validation or test data, and none at all anywhere in `src/` — serving code
   may only `predict`/`predict_proba`. The leakage-guard test enforces this;
   don't weaken it. (REQ-0006)
3. **The threshold and model version come from `model_meta.json`.** Never
   hardcode either in `src/`, tests excepted via fixtures. (REQ-0003/0010)
4. **`training/` and `src/` never import each other.** Their only interface is
   the artifact contract. Training-only deps (pandas, matplotlib) must not
   appear in `src/requirements.txt` or the Dockerfile.
5. **Never use `Scan`** on DynamoDB. Every query maps to an access pattern in
   `docs/DYNAMODB_DESIGN.md`; new query ⇒ update that doc first.
6. **A failed audit write must not fail a prediction.** Best-effort PutItem,
   error logged. Never "fix" this by making the write blocking. (REQ-0011)
7. **No live AWS in tests.** moto only; no credentials, no network. The real
   dataset is not required for tests — the 60-row fixture is. (NFR-0002)
8. **Coverage never drops below 90%** on `src/`:
   `pytest --cov=src --cov-fail-under=90`.
9. **No hand-created infrastructure.** If it isn't in `template.yaml` (or the
   documented bootstrap), it doesn't exist. No console click-ops.
10. **No secrets and no dataset files in git.** Data via `data/README.md`
    download instructions; config via env vars / SAM parameters.

## Conventions

- Python 3.14 everywhere (`.python-version` matches the
  `public.ecr.aws/lambda/python:3.14` base image). Type hints; `ruff` for
  lint + format, line length 100.
- Handler signature `def handler(event, context) -> dict`, responses via
  `shared/responses.py`; typed exceptions from services, one decorator maps
  them to HTTP.
- Prediction IDs are ULIDs. DynamoDB items carry `PK`, `SK`, `entityType`,
  ISO-8601 `createdAt`.
- Model versions: `<semver>+<git-sha7>`, bumped by the training run.
- Determinism: `random_state` from `training/config.py`, never inline.
- Commits: `feat:`, `fix:`, `test:`, `docs:`, `infra:`, `model:` prefixes;
  one logical change per commit.

## Commands

```bash
# setup
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# quality gate (run before declaring any task done)
ruff check src training tests scripts && ruff format --check src training tests scripts
pytest --cov=src --cov-report=term-missing --cov-fail-under=90

# training (writes artifacts/)
python -m training.train --data data/telco.csv

# image + infra
docker build -t cust-churn-service .
sam validate --lint && sam build && sam deploy --guided   # first deploy only

# ui (against the deployed URL)
streamlit run streamlit_app/app.py
```

## Definition of done (per task in tasks.md)

- Code + tests written; quality gate passes locally
- Relevant doc updated if behavior/design changed
- `tasks.md` checkbox ticked in the same commit
