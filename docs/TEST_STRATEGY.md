# TEST_STRATEGY.md — what the tests prove, and how

## The gate

Every change must pass, locally and in CI, before it can merge:

```
ruff check + ruff format --check        # style — run BOTH, they're separate
pytest --cov=src --cov-fail-under=90    # all tests + coverage ≥ 90% on serving code
```

Two ground rules shape everything below:

- **No live AWS in tests, ever** (NFR-0002). AWS is impersonated in-memory
  by `moto`; the fake DynamoDB table is even built from the real
  `template.yaml`, so tests and infrastructure can't drift apart.
- **No mocked models where a real one fits.** The test suite trains a real
  (tiny) model once per run — the production training code on the committed
  60-row sample (~3 s). A hand-mocked model would pass even if preprocessing
  were missing from the saved artifact, which is exactly the bug we most
  want to catch.

## The two tests that ARE the resume claims

The project's headline claims are "no data leakage" and "every prediction is
traceable." Each gets a test that would fail if the claim were false:

**1. The leakage guard (REQ-0006).** A spy wraps scikit-learn's
`Pipeline.fit` and records every batch of rows the model ever trains on.
Then the *entire real training process* runs — model selection,
cross-validation, calibration — and the test checks the recorded rows
against the validation and test splits. If even one held-out row was ever
fitted, it fails. Backed by two static checks: serving code (`src/`)
contains no `fit(` call at all, and the training code's only path to the
test split is the single final-evaluation function (enforced by reading the
code's structure — one definition, one call site).

**2. The traceability test (REQ-0010/0011).** Calls the real request handler
against the fake AWS, then asserts three copies of the model version are
identical: the HTTP response, the DynamoDB audit record, and the
`model_meta.json` file. Then the killer step: *edit* the metadata file's
version, reload, and assert the served version follows — proving the version
is genuinely read from the artifact, not hardcoded anywhere.

## What each layer's tests cover

**Training** (`tests/training/`) — the Pipeline really contains the
preprocessing and accepts raw serving-shaped input (including `None`
TotalCharges); the threshold optimizer finds a known minimum and lands near
the analytic optimum on calibrated data; cost math is hand-checked against a
paper confusion matrix; a one-class validation split fails loudly instead of
silently returning 0.5; two runs produce identical results (NFR-0003); the
metadata file has every required field and baselines for all 19 features;
the pickled model references nothing from the `training` package (so it can
load in the pandas-free image).

**Service** (`tests/unit/services/`) — the full validation matrix, one case
per way input can be wrong, all reported at once (REQ-0013); the decision
flips exactly at the metadata threshold; audit-log or metrics failures never
fail the prediction (REQ-0011); invalid input provably never reaches the
model (an exploding fake would detonate).

**Data** (`tests/unit/data/`) — the written item matches this design doc
byte for byte (keys, indexes, TTL, Decimals); all three access patterns
return the right items newest-first, with pagination round-trips; duplicate
IDs are rejected; **the no-Scan test**: a recorder hooks every DynamoDB call
made during the tests and fails if `Scan` ever appears, backed by a static
search of the source.

**Handlers** (`tests/unit/handlers/`) — full response contract for every
endpoint, 400/404/405 envelopes, base64 bodies, request-ID echo, and:
a container with a broken artifact must die at startup, never serve.

**Infrastructure** (`tests/unit/infra/`) — the template's IAM grants exactly
`dynamodb:PutItem` and nothing more (NFR-0004); log retention ≤ 30 days and
concurrency cap ≤ 10 (NFR-0008); the Dockerfile copies no training code;
CI still runs `sam validate`.

**Cost guards** (`tests/unit/data/test_emitter.py`) — the emitted metrics
document declares ≤ 10 metrics and zero dimensions. This test failing means
the AWS bill grows.

**Drift math** (`tests/unit/scripts/`) — identical distributions score ≈ 0
PSI; genuinely shifted ones cross the 0.2 flag; features absent from live
traffic report "no data" rather than crashing.

**Cross-component drift guards** — wherever two parts must agree but can't
share code, a test compares them: training's column order vs the API schema;
the API_SPEC's request example vs the schema; the Streamlit form's dropdowns
vs the schema (read from the app's source, so tests don't need streamlit
installed); the moto table vs `template.yaml`.

## What is deliberately NOT a unit test

- **Model quality** (ROC AUC ≥ 0.83, REQ-0002) is an offline evaluation
  recorded in `model_meta.json` and the README — CI checks the recorded
  numbers exist and are well-formed, not that training reruns.
- **The live system** is verified by `scripts/smoke.sh`: 13 checks against
  the real deployed URL after every deploy — health, metadata, a real
  prediction, all error codes, and the audit-log closure (the prediction it
  just made exists in DynamoDB with the same model version). It exits
  non-zero on any failure, so it gates the pipeline.
