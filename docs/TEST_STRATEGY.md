# TEST_STRATEGY.md — Customer Churn Prediction Service

Gate (from Phase 2 onward): `ruff` clean +
`pytest --cov=src --cov-fail-under=90` (NFR-0001). No live AWS anywhere in the
test suite (NFR-0002): DynamoDB and CloudWatch via moto, the model via a tiny
fixture artifact.

## The two tests that ARE the project

The resume claims are "no leakage" and "traceable predictions." Each gets a
test that would fail if the claim were false:

1. **Leakage guard (REQ-0006).** `test_nothing_fit_outside_train_split`:
   wrap the test split in a proxy DataFrame that raises if any Pipeline step
   calls `fit`/`fit_transform` on it; run the full training entrypoint on a
   small fixture dataset; assert the proxy never fired and metrics were still
   produced. Plus a static check: `grep` asserts `fit(` appears nowhere in
   `src/` (serving code may only `predict`/`predict_proba`/`transform`).
2. **Traceability (REQ-0010/0011).** `test_prediction_traceable_end_to_end`:
   invoke the handler on moto, then assert the HTTP response's
   `model_version`, the DynamoDB item's `modelVersion`, and
   `model_meta.json`'s `model_version` are all the same string — and that the
   value was read from the artifact, not a constant (mutate the fixture
   metadata, re-invoke, assert the response follows).

## Fixture model artifact

`tests/conftest.py` builds a real (tiny) artifact once per session: a Pipeline
(the production `build_pipeline()` with a fast estimator) fitted on a 60-row
fixture CSV, plus a `model_meta.json` written by the production metadata
writer. Handler tests load this artifact — so serialization,
metadata schema, and raw-input prediction are exercised for real, cheaply.
No mocked Pipeline objects: a mock would pass even if preprocessing were
missing from the artifact.

## Layers

### training/ (unit, no AWS)

- `build_pipeline()` returns a Pipeline whose **first** steps are the
  ColumnTransformer — i.e., preprocessing is inside the artifact (REQ-0005);
  it accepts raw-typed input (strings for categoricals) without error.
- Threshold selection: on a synthetic cost curve with a known minimum, the
  optimizer finds it; degenerate cases (all-one-class validation split) fail
  loudly rather than returning 0.5.
- Cost math: `expected_cost(threshold)` hand-checked against a 4-cell
  confusion matrix computed on paper.
- Metadata writer: output validates against the `model_meta.json` schema;
  `model_version` embeds the git SHA; baseline distributions cover every
  feature.
- Reproducibility (NFR-0003): train twice on the fixture data, assert
  identical test metrics.
- CV integrity: model selection uses `Pipeline` inside `cross_val_score`
  (leakage-safe by construction), asserted by inspecting the training code's
  call, not by re-running CV.

### src/services (unit, no AWS, fake repo)

- Validation matrix (REQ-0013), parametrized: each missing field, each
  out-of-domain categorical, negative numerics, unknown field ⇒ typed
  validation error listing the offending fields.
- Decision rule: probability just below / at / above threshold ⇒
  `churn_predicted` False / True / True (threshold read from metadata).
- Best-effort logging (REQ-0011): repo raising ⇒ prediction still returned,
  error logged once.

### src/data (moto)

- `PutItem` writes the exact item shape from `docs/DYNAMODB_DESIGN.md`
  (keys, GSI attrs, TTL).
- AP1/AP2/AP3 queries return expected items, newest first; pagination
  round-trip across 3 pages.
- **No-Scan assertion**: botocore event hook records every DynamoDB operation
  during the suite; `Scan` appearing fails the build. Static grep as backup.
- EMF emitter: emitted JSON parses as valid Embedded Metric Format; numeric
  features appear as metrics, categoricals as dimensions (REQ-0014).

### src/handlers (moto + fixture artifact)

- 200 happy path with full response contract (REQ-0008), including
  `X-Request-Id` echo.
- 400 envelope shape on invalid input; model provably not invoked (spy).
- `GET /model`, `GET /health` (REQ-0012); artifact-load failure at init
  raises rather than serving.
- Traceability test (above).

### Drift script (unit)

- PSI: identical distributions ⇒ ~0; shifted distribution ⇒ > 0.2 flag fires
  (REQ-0015). CloudWatch `GetMetricStatistics` stubbed with canned values.

## Out of scope for automation

- Real model quality (ROC AUC ≥ 0.83, REQ-0002) is an offline evaluation
  recorded in `model_meta.json` and the README, not a unit test — CI asserts
  the *reported* metrics exist and are well-formed, not that training runs.
- Post-deploy smoke: `scripts/smoke.sh` hits the live Function URL —
  health, /model, one predict, then verifies the DynamoDB item exists (AP1)
  and the metric landed. Manual, checklist recorded like
  `serverless-order-api`'s `SMOKE_EVIDENCE.md`.
