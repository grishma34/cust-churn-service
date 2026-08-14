# PLAN.md — Customer Churn Prediction Service build plan

Execute phases in order; each phase ends with the quality gate green
(`ruff` clean + `pytest --cov=src --cov-fail-under=90` — coverage gate applies
from Phase 3 onward, once there is meaningful `src/` code). Tick the matching
boxes in `tasks.md` as you go. Requirement IDs refer to `docs/REQUIREMENTS.md`.

---

## Phase 0 — Repo skeleton & tooling (½ day)

**Goal:** empty but runnable project; CI already enforcing the gate.

1. Directory layout per `PROJECT_STRUCTURE.md`; `pyproject.toml` (ruff),
   `.python-version` (3.14), the three requirements files split per layer
   (training / inference / dev).
2. `data/README.md` with the Telco CSV source URL + sha256; commit the 60-row
   fixture `data/fixtures/telco_60.csv`.
3. `src/shared/`: `errors.py`, `responses.py`, `logging.py`, `schema.py` stub.
4. `tests/conftest.py`: event factory, moto table fixture stub.
5. `.github/workflows/ci.yml`: ruff + pytest (+ `sam validate` once the
   template exists). Seed one real test so CI is green, not vacuous.

**Exit:** CI passes on GitHub; `pytest` runs locally.

## Phase 1 — Training pipeline (1–2 days)

**Goal:** `python -m training.train` produces a leakage-safe fitted Pipeline
with honest metrics (REQ-0001/0002/0004/0005/0006).

1. `training/features.py`: column lists; `build_pipeline()` =
   `ColumnTransformer` (median-impute + scale numerics; most-frequent-impute +
   one-hot categoricals — handles the blank-`TotalCharges` rows) + estimator.
2. `training/train.py`: load CSV, stratified train/val/test split
   (60/20/20, seeded from `config.py`); model selection between
   `LogisticRegression` and `HistGradientBoostingClassifier` by stratified
   5-fold CV ROC AUC on the training split only.
3. Calibration check on the winner (reliability curve); wrap in
   `CalibratedClassifierCV` if needed (REQ-0004).
4. Tests first-class here, not an afterthought: pipeline-shape test,
   raw-input test, the **leakage-guard test**, reproducibility test
   (see `docs/TEST_STRATEGY.md`).

**Exit:** training runs end-to-end on the fixture CSV in tests and on the real
CSV locally; CV ROC AUC reported.

## Phase 2 — Threshold & artifact contract (1 day)

**Goal:** the business-cost threshold and the versioned artifact
(REQ-0003/0007).

1. `training/threshold.py`: sweep t ∈ (0,1) on the **validation** split,
   minimize `50·FP(t) + 450·FN(t)`; emit the cost curve plot; sanity-check
   against the analytic optimum `50/(50+450) = 0.10`.
2. `training/metadata.py`: write `model_meta.json` — `model_version`
   (`<semver>+<git-sha7>`), trained-at, dataset sha256, threshold, costs,
   **test-split** metrics (touched once, here), baseline distributions per
   feature (numeric mean/std/deciles; categorical frequencies) for REQ-0015.
3. Generate `src/shared/schema.py` domains from the training data (script, not
   hand-typed) so API validation and training vocabulary cannot drift.
4. Tests: threshold optimizer on synthetic curves, cost math by hand,
   metadata schema, baselines cover all features.

**Exit:** `artifacts/` holds `model.joblib` + `model_meta.json` + plots; test
ROC AUC ≥ 0.83 recorded (REQ-0002) — if not met, iterate on the model here,
**not** later.

## Phase 3 — Inference service, local (1–2 days)

**Goal:** the full request path working under pytest, no AWS account
(REQ-0008…0014). Coverage gate on from here.

1. `src/model/artifact.py`: load joblib + metadata at import; fail init
   loudly if missing/corrupt.
2. `src/services/prediction_service.py`: validate (REQ-0013) → `predict_proba`
   → decide via metadata threshold → best-effort log (repo + emitter injected).
3. `src/data/prediction_repository.py` per `docs/DYNAMODB_DESIGN.md`
   (PutItem + AP1/AP2/AP3); `src/data/metrics_emitter.py` (EMF, REQ-0014).
4. `src/handlers/predict.py`: route `/predict`, `/model`, `/health` from the
   Function URL event; error decorator; request-ID echo.
5. Tests: validation matrix, decision boundary, best-effort-logging, item
   shape, no-Scan assertion, EMF format, handler contracts, and the
   **end-to-end traceability test** (see `docs/TEST_STRATEGY.md`).

**Exit:** every REQ 0008–0014 has a passing test; coverage ≥ 90%.

## Phase 4 — Container & AWS infra (1–2 days)

**Goal:** live Function URL answering predictions (REQ-0009).

1. `Dockerfile`: `public.ecr.aws/lambda/python:3.14`, install
   `src/requirements.txt`, copy `src/` + `artifacts/`; local check with the
   Lambda runtime interface emulator (`docker run` + curl) before any deploy.
2. `template.yaml`: ECR-image Lambda (`PackageType: Image`, memory sized
   in-phase — start 1024 MB, measure), Function URL (auth NONE for the
   demo), DynamoDB table + 2 GSIs + TTL from `docs/DYNAMODB_DESIGN.md`,
   **Revised in Phase 4:** originally arm64; switched to x86_64 because both
   the dev machine and GitHub runners are x86_64 — cross-building arm64
   images needs qemu/buildx for no cost benefit at free-tier volume.
   explicit least-privilege policy: `dynamodb:PutItem` on the table,
   CloudWatch logs/EMF only (NFR-0004). Cost caps per NFR-0008: log group
   with 30-day retention in the template, ECR lifecycle policy keeping 2
   images, and a documented tally of extracted metrics staying ≤ 10.
3. Test fixture parses the table schema from `template.yaml` (no drift).
4. First manual deploy (`sam deploy --guided`); run `scripts/smoke.sh`:
   health → /model → predict → AP1 lookup of the logged item → metric visible.
5. Measure cold start and warm p95 against NFR-0006; record numbers.

**Exit:** smoke checklist green against the live URL; latency numbers recorded.

## Phase 5 — CI/CD (½–1 day)

**Goal:** merge to main ⇒ image built, pushed, deployed — no manual step.

1. OIDC provider + deploy role (reuse the `serverless-order-api` bootstrap
   pattern, including its hard-won trust-subject lessons: environment-based
   subject, numeric IDs, read the presented subject from CloudTrail when it
   fails).
2. `deploy.yml`: tests → `docker build` → push to ECR → `sam deploy
   --image-repository` → smoke script against prod.
3. Branch protection on `main`: PR + green CI required.

**Exit:** a trivial merged PR reaches production unattended.

## Phase 6 — Streamlit UI (1 day)

**Goal:** a non-technical user can test predictions (REQ-0016).

1. `streamlit_app/app.py`: form controls generated from
   `src/shared/schema.py` domains (dropdowns for categoricals, number inputs
   with bounds); POST to the Function URL (from `st.secrets`/env); render
   probability gauge, decision, threshold, model version; surface 400 details
   readably.
2. Deploy to Streamlit Community Cloud; link in README.
3. Test: the form's field set and domains match `schema.py` exactly (same
   drift-guard idea as the order API's frontend test).

**Exit:** public UI produces the same answers as `curl` against the API.

## Phase 7 — Drift monitoring & polish (1 day)

1. `scripts/drift_report.py`: pull recent CloudWatch stats, PSI vs.
   `model_meta.json` baselines, flag PSI > 0.2 (REQ-0015); run once against
   real traffic and record output.
2. `scripts/audit_query.py` (AP2/AP3 CLI).
3. README: architecture diagram, live URLs, the resume bullets restated with
   their now-true numbers (record count, actual ROC AUC, threshold, costs),
   claim-to-test table, run instructions.
4. Tag `v1.0.0`.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Test ROC AUC misses 0.83 | Caught in Phase 2 (test split evaluated there); iterate on features/model before any serving code exists |
| sklearn version skew train ↔ serve | Same pinned version in both requirements files; a test asserts the pins match; artifact loads under `src/` deps in CI |
| Container image bloat / slow cold start | Training deps excluded from image by rule 4; cold start measured in Phase 4 before CI/CD lands |
| Blank `TotalCharges` strings break the Pipeline at serve time | Blank→NaN parse at the I/O boundary on both sides (read_csv na_values / JSON null); imputation inside the Pipeline; fixture CSV includes such rows |
| Function URL is public (auth NONE) | Demo scope: no PII in requests, DynamoDB TTL 90d, note in README; API Gateway + auth is the documented upgrade path |
| EMF metric cardinality (19 features) blows the $5/month cap (NFR-0008) | ≤ 10 extracted metrics; categorical distributions read from EMF log lines via Logs Insights, not per-dimension metrics |

## Sizing

~7–9 working days. Phases 1–3 are the substance; don't start Phase 4 until the
leakage-guard and traceability tests exist — they're the point of the project.
