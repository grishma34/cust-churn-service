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
(ECE 0.019, no wrap needed). 25 tests, `src/` coverage 100%.

**Phase 2 complete** (2026-08-14). Artifact contract live: `artifacts/`
holds model.joblib + model_meta.json (version `1.0.0+<sha7>`) + 3 evidence
plots. **Test ROC AUC 0.843** (target ≥ 0.83, split touched once);
threshold 0.065 from the $50/$450 cost sweep → 97% churner recall,
$24.52/customer expected cost. 36 tests.

**Phase 3 complete** (2026-08-14). Full request path works under pytest with
no AWS account: handler → validate → Pipeline → threshold decision →
conditional DynamoDB put + EMF line, all against the real fixture artifact
on moto. Coverage gate live in CI at 90%; suite is 109 tests at 100%.

**Phase 4 code-complete, deploy blocked** (2026-08-14). Dockerfile,
template.yaml (lint-clean, property-pinned by tests), template-parsed test
fixture, and the 13-check smoke script are all in. The remaining boxes need
two things this machine doesn't have: **docker** (image build + RIE check)
and **AWS credentials** (`aws login` / `aws configure`). 115 tests, 100%.

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
- [x] `training/threshold.py`: cost sweep (FP $50 / FN $450), cost-curve plot (REQ-0003)
      Real run: chosen t=0.065 (empirical min on validation; analytic optimum
      0.10 marked on the plot alongside the rejected 0.5 default). Fails
      loudly on a one-class validation split.
- [x] `training/metadata.py`: `model_meta.json` with version+git-sha, threshold, metrics, baselines (REQ-0007)
      `1.0.0+<sha7>`; dataset sha256; train-split baselines for all 19
      features (numeric mean/std/quantiles/missing_rate, categorical
      frequencies). A test proves the pickled Pipeline references no
      `training.*` module — it unpickles in the pandas-free image.
- [x] `src/shared/schema.py` domains generated from training data (no drift)
      `scripts/gen_schema_domains.py` rewrites a marked block (43 values,
      ruff-format-idempotent); test asserts domains cover the fixture.
- [x] Test-split evaluated once; ROC AUC ≥ 0.83 recorded (REQ-0002)
      **Test ROC AUC 0.843**, PR AUC 0.634, at t=0.065: tp=364 fp=601 fn=10
      tn=434 (97% churner recall), expected cost $24.52/customer. Single
      call site of `evaluate_final` enforced by AST test.
- [x] Threshold/cost/metadata unit tests
      Cost math hand-checked; known-minimum sweep; calibrated synthetic
      sample lands within 0.03 of the analytic optimum.

## Phase 3 — Inference service (local)
- [x] `src/model/artifact.py`: load at init, fail loudly (REQ-0009 prep)
      Singleton load; ArtifactError on missing/corrupt/wrong-shape; tested
      that a container with a broken artifact dies at import, not at serve.
- [x] `src/services/prediction_service.py`: validate → predict → decide → best-effort log (REQ-0008/0011/0013)
      Repo + emitter injected (no boto3); threshold and version from
      metadata only; audit/metrics failures logged, never surfaced.
- [x] `src/data/prediction_repository.py`: PutItem + AP1/AP2/AP3, no Scan (REQ-0011)
      Conditional PutItem (`attribute_not_exists`), Decimal-safe floats,
      90-day TTL, cursor pagination on both GSIs.
- [x] `src/data/metrics_emitter.py`: EMF input distributions (REQ-0014)
      6 extracted metrics, no dimensions; a test fails the build if the
      metric count exceeds the 10-free cap (NFR-0008). Categoricals ride the
      log line for Logs Insights.
- [x] `src/handlers/predict.py`: `/predict`, `/model`, `/health` + error decorator (REQ-0008/0012)
      Artifact loads at module import; base64 bodies handled; 400/404/405
      envelopes per API_SPEC.
- [x] Validation matrix tests (REQ-0013)
      All 19 missing-field cases parametrized; domain/type/bounds/unknown
      matrix; all problems reported at once; model provably not invoked on
      invalid input (exploding-pipeline spy).
- [x] **No-Scan assertions: botocore call log + static grep**
- [x] **End-to-end traceability test: response == DynamoDB item == model_meta version** (REQ-0010)
      Plus the mutation test: rewrite model_version in the metadata, reload,
      served version follows — no copy of the version exists in src/.
- [x] Coverage ≥ 90% — gate on from here (NFR-0001)
      `--cov-fail-under=90` live in CI; currently 100% (109 tests).

## Phase 4 — Container & AWS infra
- [ ] `Dockerfile` (lambda/python:3.14, src + artifacts only); local RIE curl check (REQ-0009)
      Dockerfile written and guarded by `test_dockerfile_excludes_training`;
      the RIE curl check is blocked: **docker is not installed on this
      machine** (no passwordless sudo to install it).
- [x] `template.yaml`: image Lambda + Function URL + DynamoDB (2 GSIs, TTL) + least-privilege IAM (NFR-0004)
      `sam validate --lint` clean (locally and as a CI job). IAM is a single
      `dynamodb:PutItem` statement, pinned by test. NFR-0008 caps in the
      template: 30-day log retention, on-demand billing; x86_64 (see the
      revision note in `PLAN.md` Phase 4). ECR lifecycle policy (keep 2)
      lands with the pipeline in Phase 5, where the repo is created.
- [x] Test fixture parses table schema from `template.yaml`
      CFN-tag-tolerant loader in conftest; the moto table is now built from
      the template's own AttributeDefinitions/GSIs/TTL.
- [ ] First deploy; `scripts/smoke.sh` green against live URL
      **Revised:** with AWS credentials now present but docker still absent
      locally, the first deploy goes through the Phase 5 pipeline (GitHub
      runners have docker) instead of `sam deploy` from this machine —
      Phase 5's OIDC bootstrap was pulled forward to enable it. The smoke
      run against the live URL still closes this box.
- [ ] Cold start + warm p95 measured vs. NFR-0006; numbers recorded
      Blocked on the deploy above.

## Phase 5 — CI/CD (pulled forward to carry the Phase 4 deploy)
- [x] OIDC provider + deploy role (bootstrap pattern from serverless-order-api)
      `bootstrap/github-oidc.yaml`, cfn-lint clean, deployed as
      `cust-churn-service-bootstrap`. Reuses the account's existing OIDC
      provider and the sibling's subject lessons (environment-based subject,
      numeric ids) verbatim; adds ECR statements for the container image.
      `production` environment locked to `main`; `AWS_DEPLOY_ROLE_ARN` and
      `AWS_REGION` set as repository variables.
- [ ] `deploy.yml`: test → train (hash-verified dataset) → sam build →
      sam deploy → ECR keep-2 lifecycle policy → smoke
      Written; first run pending.
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
