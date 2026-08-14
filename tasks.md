# tasks.md — executable checklist

Work top-to-bottom. Tick a box only when the quality gate passes
(`ruff` clean, `pytest --cov=src --cov-fail-under=90` from Phase 3 onward).
Details per phase live in `PLAN.md`; requirement IDs in `docs/REQUIREMENTS.md`.

## Status

**Phase 0 complete** (2026-08-14). Public repo at
`grishma34/cust-churn-service`; CI green on `main` (run 31765270584): ruff
clean, 11 seed tests, 100% coverage. Toolchain settled on Python **3.14**
(matches the installed interpreter, the sibling project, and the Lambda
`python:3.14` base image — docs updated from the originally drafted 3.13).
NFR-0008 (< $5/month cloud cost) added mid-phase with its design consequences
(≤ 10 EMF metrics, ECR lifecycle policy, 30-day log retention).

**Phase 1 complete** (2026-08-14). Training runs end-to-end on the real CSV
in ~3 s: LogisticRegression selected over HistGradientBoosting by 5-fold CV
ROC AUC (0.848 vs 0.830), validation ROC AUC 0.836, well-calibrated
(ECE 0.019, no wrap needed). 25 tests, `src/` coverage 100%. Next:
Phase 2 — threshold & artifact contract.

## Phase 0 — Skeleton & tooling
- [x] Directory layout per `PROJECT_STRUCTURE.md` + `pyproject.toml` (ruff) + split requirements files
      All pins exact; `test_requirements_pins.py` enforces pinning and the
      sklearn/joblib pin match between `src/` and `training/` (skew risk).
- [x] `data/README.md` (Telco CSV source + sha256) + committed 60-row fixture
      Fixture generated from the real CSV by `scripts/make_fixture.py`
      (seeded, stratified: 16/60 churners, 2 blank-`TotalCharges` rows).
- [x] `src/shared/`: errors, responses, logging, schema stub
- [x] `tests/conftest.py`: event factory, moto table fixture stub
      Table fixture already implements the full `docs/DYNAMODB_DESIGN.md`
      schema (2 GSIs + TTL); Phase 4 swaps it to parse `template.yaml`.
- [x] `.github/workflows/ci.yml` green on GitHub with one real seed test
      Verified: run 31765270584 on `main`, lint + 11 seed tests green
      (error→HTTP mapping, schema↔API-spec↔fixture drift guards,
      requirements pins), coverage artifact uploaded.

## Phase 1 — Training pipeline
- [x] `training/features.py`: `build_pipeline()` — ColumnTransformer + estimator in one Pipeline (REQ-0005)
      Positional column selection (no pandas in the inference image); sklearn
      built-ins only so the artifact unpickles without the `training` package.
      Column order pinned to `src/shared/schema.py` by test.
- [x] `training/train.py`: stratified 60/20/20 split, 5-fold CV model selection (REQ-0001/0002)
      Real run: **logistic_regression wins** (CV ROC AUC 0.848 vs 0.830 for
      hist_gradient_boosting); validation ROC AUC 0.836. Test split created
      but untouched — a test enforces that until Phase 2.
- [x] Calibration check; `CalibratedClassifierCV` if needed (REQ-0004)
      ECE gate (> 0.05 wraps in isotonic CalibratedClassifierCV). Real run:
      ECE 0.019 — LR already well calibrated, no wrap. Gate exercised both
      ways by tests.
- [x] **Leakage-guard test: nothing fit outside the training split** (REQ-0006)
      Dynamic: Pipeline.fit spy across the full entrypoint asserts zero
      val/test rows in any fit (incl. every CV clone). Static: no `fit(` in
      `src/`; training never imports serving.
- [x] Raw-input test: fitted Pipeline predicts on unprocessed rows
      Serving-shaped input: object array, JSON types, `None` TotalCharges —
      plus the fixture's blank-TotalCharges rows through fit and predict.
- [x] Reproducibility test: two runs, identical metrics (NFR-0003)

## Phase 2 — Threshold & artifact
- [ ] `training/threshold.py`: cost sweep (FP $50 / FN $450), cost-curve plot (REQ-0003)
- [ ] `training/metadata.py`: `model_meta.json` with version+git-sha, threshold, metrics, baselines (REQ-0007)
- [ ] `src/shared/schema.py` domains generated from training data (no drift)
- [ ] Test-split evaluated once; ROC AUC ≥ 0.83 recorded (REQ-0002)
- [ ] Threshold/cost/metadata unit tests

## Phase 3 — Inference service (local)
- [ ] `src/model/artifact.py`: load at init, fail loudly (REQ-0009 prep)
- [ ] `src/services/prediction_service.py`: validate → predict → decide → best-effort log (REQ-0008/0011/0013)
- [ ] `src/data/prediction_repository.py`: PutItem + AP1/AP2/AP3, no Scan (REQ-0011)
- [ ] `src/data/metrics_emitter.py`: EMF input distributions (REQ-0014)
- [ ] `src/handlers/predict.py`: `/predict`, `/model`, `/health` + error decorator (REQ-0008/0012)
- [ ] Validation matrix tests (REQ-0013)
- [ ] **No-Scan assertions: botocore call log + static grep**
- [ ] **End-to-end traceability test: response == DynamoDB item == model_meta version** (REQ-0010)
- [ ] Coverage ≥ 90% — gate on from here (NFR-0001)

## Phase 4 — Container & AWS infra
- [ ] `Dockerfile` (lambda/python:3.14, src + artifacts only); local RIE curl check (REQ-0009)
- [ ] `template.yaml`: image Lambda + Function URL + DynamoDB (2 GSIs, TTL) + least-privilege IAM (NFR-0004)
- [ ] Test fixture parses table schema from `template.yaml`
- [ ] Manual dev deploy; `scripts/smoke.sh` green against live URL
- [ ] Cold start + warm p95 measured vs. NFR-0006; numbers recorded

## Phase 5 — CI/CD
- [ ] OIDC provider + deploy role (bootstrap pattern from serverless-order-api)
- [ ] `deploy.yml`: test → build → ECR push → sam deploy → smoke
- [ ] Branch protection: PR + green CI required
- [ ] A trivial merged PR reaches production unattended

## Phase 6 — Streamlit UI
- [ ] `streamlit_app/app.py`: schema-driven form → API → result display (REQ-0016)
- [ ] Deployed to Streamlit Community Cloud; URL in README
- [ ] Drift-guard test: form fields/domains == `schema.py`

## Phase 7 — Drift & polish
- [ ] `scripts/drift_report.py`: PSI vs. baselines, >0.2 flags (REQ-0015); run once on real traffic
- [ ] `scripts/audit_query.py` (AP2/AP3)
- [ ] README: diagram, live URLs, real numbers in the resume bullets, claim-to-test table
- [ ] Tag `v1.0.0`
