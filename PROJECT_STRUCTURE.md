# PROJECT_STRUCTURE.md — repository layout

The canonical map of the repo. If a file doesn't fit one of these homes,
that's a design smell — reconcile here first.

```
cust-churn-service/
├── readme.md                  # what/why, live demo, metrics, how to run
├── claude.md                  # AI agent operating instructions + guardrails
├── PLAN.md                    # phased build plan (execute in order)
├── PROJECT_STRUCTURE.md       # this file
├── tasks.md                   # executable checklist, ticked as phases land
├── pyproject.toml             # ruff config, project metadata
├── .python-version            # 3.14 — must match the Lambda base image
├── .gitignore
│
├── docs/
│   ├── REQUIREMENTS.md        # REQ-#### / NFR-#### — what the system must do
│   ├── ARCHITECTURE.md        # the four load-bearing decisions + layering
│   ├── API_SPEC.md            # /predict, /model, /health contracts
│   ├── DYNAMODB_DESIGN.md     # prediction audit log: 3 APs, no scans
│   └── TEST_STRATEGY.md       # what proves the resume claims
│
├── data/                      # gitignored except README + fixture
│   ├── README.md              # where to download the Telco CSV + its sha256
│   └── fixtures/telco_60.csv  # 60-row sample for tests (committed)
│
├── training/                  # OFFLINE ONLY — never imported by src/
│   ├── __init__.py
│   ├── config.py              # seeds, costs (C_FP=50, C_FN=450), split ratios
│   ├── features.py            # column lists + build_pipeline() (REQ-0005)
│   ├── train.py               # entrypoint: fit, CV, calibrate, evaluate
│   ├── threshold.py           # cost curve sweep, threshold selection (REQ-0003)
│   ├── metadata.py            # model_meta.json writer incl. baselines (REQ-0007)
│   ├── plots.py               # cost/reliability/ROC evidence plots
│   └── requirements.txt       # pandas, scikit-learn, matplotlib (training-only)
│
├── artifacts/                 # gitignored — output of training/train.py
│   ├── model.joblib           # the ONE Pipeline
│   ├── model_meta.json        # version, threshold, costs, metrics, baselines
│   └── plots/                 # cost curve, reliability curve, ROC
│
├── src/                       # everything in the inference image
│   ├── handlers/
│   │   └── predict.py         # Function URL router: /predict, /model, /health
│   ├── services/
│   │   └── prediction_service.py  # validate → predict → decide → log; no boto3
│   ├── data/
│   │   ├── prediction_repository.py  # DynamoDB PutItem + AP queries (boto3)
│   │   └── metrics_emitter.py        # CloudWatch EMF (REQ-0014)
│   ├── model/
│   │   └── artifact.py        # load model.joblib + model_meta.json at init
│   ├── shared/
│   │   ├── schema.py          # input field domains (generated from training data)
│   │   ├── errors.py          # ValidationError, ArtifactError, ...
│   │   ├── responses.py       # response builder + error→HTTP decorator
│   │   └── logging.py         # JSON logger with request ID
│   └── requirements.txt       # scikit-learn, joblib, boto3 — inference-only
│
├── streamlit_app/
│   ├── app.py                 # form → POST /predict → show result (REQ-0016)
│   └── requirements.txt       # streamlit, requests — no boto3, no sklearn
│
├── scripts/
│   ├── make_fixture.py        # regenerates data/fixtures/telco_60.csv (seeded)
│   ├── gen_schema_domains.py  # regenerates CATEGORICAL_DOMAINS in schema.py
│   ├── drift_report.py        # PSI vs. baselines in model_meta.json (REQ-0015)
│   ├── audit_query.py         # AP2/AP3 CLI over the predictions table
│   └── smoke.sh               # post-deploy checklist against the live URL
│
├── tests/
│   ├── conftest.py            # fixture artifact, moto table, event factory
│   ├── training/              # pipeline, threshold, metadata, reproducibility
│   └── unit/                  # mirrors src/: handlers/ services/ data/ model/
│
├── Dockerfile                 # lambda/python:3.14 base; copies src/ + artifacts/
├── template.yaml              # SAM: Lambda (ImageUri), Function URL, DynamoDB
├── samconfig.toml
├── requirements-dev.txt       # pytest, pytest-cov, moto, ruff
└── .github/workflows/
    ├── ci.yml                 # ruff + pytest + coverage gate + sam validate
    └── deploy.yml             # merge to main: build image → ECR → sam deploy
```

## Boundary rules the layout encodes

- **`training/` ↔ `src/`**: no imports in either direction. Their only
  interface is the artifact contract (`model.joblib` + `model_meta.json`).
  Training deps stay out of the inference image (NFR-0006).
- **boto3 lives only in `src/data/`** — services and handlers are testable
  without mocks.
- **`streamlit_app/` knows only the HTTP API** — no model, no AWS SDK.
- **`artifacts/` and `data/` are gitignored** (except fixtures): models ship
  via the ECR image, data via documented download — the repo stays small and
  the image digest, not git, is the model registry.
