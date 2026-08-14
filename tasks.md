# tasks.md — the completed checklist

Every box below was ticked only when the quality gate passed, and each
carries its evidence — a number, a run ID, or a test name. The whole project
was built on **2026-08-14**, docs-first, in phase order. Details of each
phase live in `PLAN.md`; requirement IDs in `docs/REQUIREMENTS.md`.

**Final state:** v1.0.0 tagged and live. API + Streamlit UI public, 126
tests at 100% coverage, unattended deploys proven by push (run 31768725751)
and by PR (#1), branch protection on, abuse caps in place.

## Phase 0 — Skeleton & tooling
- [x] Folder layout, linter config, three pinned requirements lists
      — pin-match between training and serving enforced by test.
- [x] Dataset documented with sha256; 60-row stratified fixture committed
      (16 churners, 2 blank-`TotalCharges` rows for the imputation path).
- [x] Shared modules: errors, responses, logging, schema stub.
- [x] Test scaffolding: event factory, fake-AWS table fixture.
- [x] CI green on GitHub with real seed tests — run 31765270584.

## Phase 1 — Training pipeline
- [x] `build_pipeline()`: all preprocessing + classifier in ONE Pipeline,
      positional column selection (no pandas needed at serving), column
      order test-pinned to the API schema. (REQ-0005)
- [x] Seeded 60/20/20 stratified split; 5-fold CV model selection —
      **logistic regression won**, 0.848 vs 0.830 for gradient boosting.
- [x] Calibration gate: ECE 0.019, already well-calibrated, no wrap needed.
      (REQ-0004)
- [x] **Leakage guard**: a spy on `Pipeline.fit` across the full training
      run proves zero validation/test rows ever fitted; no `fit(` exists in
      serving code. (REQ-0006)
- [x] Raw-input test: the fitted Pipeline predicts on serving-shaped rows,
      including `None` TotalCharges.
- [x] Reproducibility: two runs, identical metrics. (NFR-0003)

## Phase 2 — Threshold & artifact
- [x] Cost sweep on validation: threshold **0.065** (analytic optimum 0.10;
      the rejected 0.5 default marked on the committed cost-curve plot).
      Fails loudly on a one-class split. (REQ-0003)
- [x] Test split scored exactly once — **ROC AUC 0.843**, PR AUC 0.634;
      at the threshold: 364/374 churners caught (97% recall), 10 missed,
      $24.52 expected cost per customer. Single-call-site rule enforced by
      an AST test. (REQ-0002)
- [x] `model_meta.json`: version `<semver>+<git sha>`, dataset sha256,
      costs, scores, 19 per-feature baselines; the pickled model proven
      free of any `training.*` reference. (REQ-0007)
- [x] API category vocabularies generated from the dataset (43 values),
      not hand-typed; regeneration is format-stable.
- [x] Threshold/cost/metadata unit tests, incl. hand-checked cost math.

## Phase 3 — Inference service (local)
- [x] Artifact loader: loads once at startup, dies loudly on any broken
      artifact — tested via import failure. (REQ-0012)
- [x] Prediction service: validate → predict → decide (threshold from
      metadata only) → best-effort audit + metrics; failures of either
      never fail the prediction. (REQ-0008/0011/0013)
- [x] DynamoDB repository: conditional writes, three access patterns,
      cursor pagination, Decimal-safe numbers, 90-day TTL.
- [x] Metrics emitter: 6 extracted metrics, zero dimensions — a test fails
      the build past 10 (the cost cap, NFR-0008). (REQ-0014)
- [x] Handler: `/predict` `/model` `/health`, base64 bodies, full error
      envelopes.
- [x] Validation matrix: every missing field, bad category, bad number —
      all reported at once; model provably not called on bad input.
- [x] **No-Scan proof**: recorder on every DynamoDB call + static search.
- [x] **Traceability proof**: response == audit record == metadata version,
      and a mutated metadata file changes the served version. (REQ-0010)
- [x] Coverage gate on: 90% enforced in CI (actual: 100%).

## Phase 4 — Container & AWS infrastructure
- [x] Dockerfile: Lambda Python 3.14 base, serving code + the two model
      files only — no training libraries (test-enforced). Local run check
      superseded by the live smoke test (no Docker on the dev machine —
      see the Phase 4 revision notes in `PLAN.md`).
- [x] `template.yaml`: image Lambda + Function URL + table (2 indexes,
      TTL) + 30-day logs; IAM = exactly one `PutItem` action, test-pinned.
      x86_64 (revised from arm64). Lint-clean locally and in CI.
- [x] Test fixture builds its fake table FROM the template — no drift.
- [x] First deploy + smoke: **13/13 checks green** against the live URL,
      including the audit-log closure. Run 31768725751 — first attempt.
- [x] Latency measured: warm p95 265 ms end-to-end / 16 ms server median;
      cold start ~10 s; image 296 MB. (NFR-0006)

## Phase 5 — CI/CD
- [x] OIDC bootstrap stack (`cust-churn-service-bootstrap`): deploy role
      with repo-pinned numeric-ID trust, reused from the sibling project's
      lessons — assumed successfully on the first attempt. `production`
      environment locked to `main`.
- [x] `deploy.yml`: gate → checksum-verified dataset → retrain (model
      stamped with the deploying commit) → image build/push → deploy →
      keep-2 image policy → live smoke. ~7 minutes, unattended.
- [x] Branch protection: `quality-gate` + `template` required, strict,
      admins enforced; no required reviews (single-maintainer repo — an
      approval requirement would deadlock). Direct pushes to main are now
      impossible.
- [x] **A trivial PR reached production unattended** — PR #1, which was
      also the fix for the one CI failure of the project: the freshly
      enabled gate caught its own author on formatting. Merge 50073d2,
      deploy run 31770964618, live `/health` served `1.0.0+50073d2`.

## Phase 6 — Streamlit UI
- [x] `streamlit_app/app.py`: tabbed form for all 19 fields, model banner
      from `GET /model`, decision explained against the cost threshold,
      per-field error rendering, "new customer" null-TotalCharges path
      (verified live: 76.5% for a tenure-0 month-to-month fiber profile).
- [x] Thin-client boundary test-enforced: no sklearn, no boto3, no `src/`
      imports; form vocabularies byte-identical to the API schema.
- [x] Deployed on Streamlit Community Cloud (URL in the README), public
      access verified.

## Phase 7 — Drift & polish
- [x] `scripts/drift_report.py`: PSI per feature vs stored baselines from
      one Logs Insights query; first live run **correctly flagged 18/19
      features** — traffic was repeated synthetic smoke payloads, and a
      monoculture IS drift. Exits non-zero on drift, so it can gate a
      schedule. (REQ-0015)
- [x] `scripts/audit_query.py`: get / by-model / by-day under operator
      credentials; live output shows model versions rolling across deploys.
- [x] README: measured numbers in the resume bullets + claim-to-proof
      table + live URLs.
- [x] Tag `v1.0.0` — after PR #1's deploy went green.

## Post-v1.0.0 hardening (public-endpoint abuse caps, NFR-0008)
- [x] Reserved concurrency 5 on the function (PR #3): floods throttle to
      429s instead of billing; verified live on the Lambda.
- [x] Account-level $5/month AWS Budget (bootstrap stack): email at 80%
      actual / 100% forecasted spend.
- [x] Docs rewritten in plain language (PRs #4, #5) — same facts, readable
      without prior AWS/ML vocabulary.
