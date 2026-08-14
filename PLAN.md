# PLAN.md — the build plan

This is the plan the project was built from, kept as a record now that it's
done. Each phase had a goal and an exit test; a phase wasn't finished until
the quality gate was green (`ruff` clean + tests + coverage). Progress was
ticked off in `tasks.md`, which also records the evidence. Notes marked
**Revised** show where reality differed from the plan — they're left in on
purpose.

Requirement IDs (REQ-####) refer to `docs/REQUIREMENTS.md`.

---

## Phase 0 — Skeleton & tooling

**Goal:** an empty but runnable project, with CI already enforcing quality.

Set up the folder layout, linter config, and the three pinned dependency
lists (training / serving / dev — kept separate so training libraries never
reach the deployed image). Document the dataset download with a checksum and
commit a 60-row sample for tests. Write the first shared modules (errors,
responses, logging) and a GitHub Actions workflow, seeded with real tests so
a green run means something.

**Exit:** CI green on GitHub; tests run locally.

## Phase 1 — The training pipeline

**Goal:** one command that trains a leakage-safe model with honest numbers.

Build the single scikit-learn Pipeline (impute → scale numerics, impute →
one-hot categoricals, then the classifier). Split the data 60/20/20 with a
fixed seed. Compare logistic regression against gradient-boosted trees by
5-fold cross-validation on training data only; check the winner's
calibration and auto-wrap it in a calibrator if needed. Write the leakage
guard, raw-input, and reproducibility tests alongside — they're the point,
not an afterthought.

**Exit:** training runs end-to-end on both the test fixture and the real
CSV, reporting cross-validation ROC AUC.

## Phase 2 — Threshold & the model artifact

**Goal:** the business-cost threshold, and a saved model that describes itself.

Sweep every threshold on the validation split and keep the one that
minimizes `$50·FP + $450·FN`, sanity-checked against the analytic optimum
(0.10). Evaluate the held-out test split — the one and only time it is ever
scored. Package everything into `model.joblib` + `model_meta.json` (version
= semver + git commit, dataset checksum, threshold, costs, scores, and
per-feature training statistics for later drift checks). Generate the API's
category vocabularies from the dataset rather than typing them by hand.

**Exit:** artifact on disk with test ROC AUC ≥ 0.83 recorded. (Actual: 0.843.)

## Phase 3 — The inference service, locally

**Goal:** the full request path working under pytest, with no AWS account.
The 90% coverage gate switches on here.

Artifact loader (fails at startup if the model is broken), the prediction
service (validate → predict → decide → best-effort audit write + metrics),
the DynamoDB repository (three access patterns, no scans), the metrics
emitter (capped at 6 metrics for cost), and the Lambda handler for
`/predict`, `/model`, `/health`. The two headline tests land here: the
end-to-end traceability test and the no-Scan assertion.

**Exit:** every serving requirement has a passing test; coverage ≥ 90%.

## Phase 4 — Container & AWS infrastructure

**Goal:** the service live on a real URL.

Write the Dockerfile (Lambda Python base + serving code + the two model
files, nothing else) and `template.yaml` (the Lambda, its Function URL, the
DynamoDB table, a 30-day-retention log group, and IAM that allows exactly
one action). Make the test fixture build its fake table from the template so
infrastructure and tests can't drift. Deploy, run the smoke checklist,
measure latency.

**Revised (architecture):** planned arm64, shipped x86_64 — both the dev
machine and the CI runners are x86_64, and cross-building buys nothing at
free-tier volume.

**Revised (how the deploy happened):** the plan said "manual first deploy
from the laptop," but the laptop had no Docker. Instead Phase 5 was pulled
forward and the first deploy ran through the CI pipeline, immediately
verified by the 13-check smoke test — stronger evidence than a local poke.

**Exit:** smoke checklist green against the live URL; latency recorded
(warm p95 265 ms, cold ~10 s, image 296 MB).

## Phase 5 — CI/CD

**Goal:** merging to main reaches production with no manual step and no
stored AWS keys.

A one-time bootstrap stack creates the deploy role GitHub assumes via OIDC
(reusing the sibling project's hard-won trust-subject configuration — it
worked on the first attempt here). The deploy workflow: run the gate again →
download and checksum-verify the dataset → retrain (stamping the model with
the deploying commit) → build and push the image → deploy → apply the keep-2
image cleanup policy → smoke-test production. Branch protection came last,
deliberately — see Phase 7.

**Exit:** a merge reaches production unattended. (First green: run
31768725751.)

## Phase 6 — The Streamlit interface

**Goal:** a non-technical person can test predictions in a browser.

A form built from the same category vocabularies the API validates against
(a test keeps them identical), calling the public API and nothing else — the
app contains no model and no AWS credentials, so the demo can never disagree
with production. Deployed on Streamlit Community Cloud, free.

**Exit:** the public UI gives the same answers as `curl`.

## Phase 7 — Drift monitoring & polish

**Goal:** close the loop and prove everything.

The drift report (PSI per feature against the stored training baselines, fed
by one log query — flags anything over 0.2), the audit-log query tool, a
README restating the resume bullets with measured numbers, the `v1.0.0` tag,
and finally branch protection — sequenced last because it forces all further
work through pull requests, and proven by a deliberately trivial PR that had
to pass the checks and then rode the pipeline to production.

**Exit:** every box in `tasks.md` ticked with evidence.

---

## Risks we planned for — and how they turned out

| Worry | What actually happened |
|---|---|
| Test ROC AUC misses 0.83 | Never materialized: 0.843 on the first real run |
| scikit-learn version differs between training and serving | Prevented structurally: identical pins, enforced by a test |
| Container too big / cold starts too slow | 296 MB (cap 1 GB); cold ~10 s — acceptable for a demo, recorded honestly |
| Blank `TotalCharges` breaks serving | Handled: blank→missing at the I/O boundary on both sides, imputed inside the Pipeline; the fixture includes such rows |
| Public URL abused | Post-v1.0.0 hardening: concurrency cap of 5 (floods throttle) + $5/month budget alarm |
| CloudWatch metric costs blow the $5 budget | Caught at design time: 6 extracted metrics, the rest in log lines; a test enforces the cap |

## Sizing

Planned: 7–9 working days. Actual: **one day** (2026-08-14), docs-first —
the plan, requirements, and designs were written before any code, which is
much of why the build itself went fast.
