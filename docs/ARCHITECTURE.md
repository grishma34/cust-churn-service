# ARCHITECTURE.md — how the system fits together

## The big picture

The system has two halves that never run at the same time:

1. **Training** happens offline, on a laptop or in the deploy pipeline. It
   reads the customer CSV, learns the model, and writes **two files** —
   `model.joblib` (the model) and `model_meta.json` (facts about it).
2. **Serving** happens on AWS. Those two files are baked into a Docker image
   that runs on Lambda and answers prediction requests.

The two files are the **only** connection between the halves. Training code
and serving code never import each other.

```
              TRAINING (offline, ~3 seconds)
              ────────────────────────────────
  telco.csv ──►  python -m training.train
                        │  writes
                        ▼
     artifacts/model.joblib  +  model_meta.json
                        │  baked into the Docker image at build time
                        ▼
              SERVING (AWS, pay-per-request)
              ────────────────────────────────
  Streamlit UI ──►  Lambda Function URL
  (or curl)         /predict  /model  /health
                        │
         ┌──────────────┼─────────────────┐
         ▼              ▼                 ▼
     response       DynamoDB          CloudWatch
   probability,   audit log: one    input stats from
   yes/no, model  record for every  each request → the
   version        prediction made   drift report reads
                  (auto-deleted     these later
                  after 90 days)    (REQ-0015)
```

## What happens when someone asks for a prediction

1. A client (the Streamlit form, or anyone with curl) sends the customer's
   19 attributes as JSON to `POST /predict`.
2. The handler **validates** the input — every field present, every category
   legal, numbers sane. Bad input gets a 400 listing every problem; the model
   is never called on unvalidated data (REQ-0013).
3. The fitted Pipeline turns the raw values into a churn **probability**.
4. The probability is compared to the **threshold stored in
   `model_meta.json`** (0.065 — chosen from business costs, see below) to get
   the yes/no decision.
5. The prediction is written to the **DynamoDB audit log** and the input
   values are logged for **drift monitoring** — both best-effort: if either
   write fails, the caller still gets their prediction (REQ-0011).
6. The response goes back: probability, decision, threshold, model version,
   and a prediction ID that can be looked up in the audit log forever after.

Warm requests take ~16 ms server-side. The first request after idle takes
~10 s (Lambda cold start) — acceptable for a demo, documented honestly.

## The five decisions that shape everything

### 1. All preprocessing lives inside ONE scikit-learn Pipeline (REQ-0005/0006)

Filling missing values, scaling numbers, and encoding categories are steps
*inside* the saved model object, not separate code.

- **Why it prevents leakage:** the preprocessing is fitted together with the
  model, on training data only — it physically cannot peek at test data.
- **Why it prevents train/serve drift:** production runs the *same fitted
  object* training produced. There is no second copy of the preprocessing
  logic that could slowly fall out of sync.

One consequence: the Pipeline selects columns **by position** (not by pandas
column names), so the serving code can feed it a plain array built from the
JSON request — the inference image doesn't need pandas at all. A test pins
the column order between training and serving.

### 2. The decision threshold comes from business costs (REQ-0003)

A missed churner costs ~$450; a wasted retention offer costs ~$50. Because
one mistake is 9× worse than the other, the right cutoff is far below the
default 0.5: training sweeps every threshold on the validation set, computes
the dollar cost of each, and stores the cheapest (0.065) in
`model_meta.json`. The server **reads** the threshold from that file — it is
never hardcoded.

### 3. Every prediction is traceable to its exact model (REQ-0007/0010)

At training time, the model version is stamped as
`<semver>+<git commit>` (e.g. `1.0.0+8957a3e`) into `model_meta.json`.
Because the files are baked into the image, one image = one model = one
commit. Every API response and every audit-log record carries that version,
so "which model said this?" always has an answer.

- Deploying a new model = new commit → pipeline retrains → new image.
- Rolling back = pointing Lambda at the previous image (the registry keeps
  the last two).

### 4. Serverless everything, because the service is idle most of the time

- **Lambda container image** rather than a zip: scikit-learn + numpy exceed
  Lambda's 250 MB zip limit. The image is 296 MB.
- **Function URL** rather than API Gateway: it's a free, zero-config front
  door, and the demo needs nothing more. The handler doesn't care what the
  front door is, so upgrading to API Gateway (for auth/rate limits) later
  changes no application code.
- **Model loads once per container**, at startup — not per request. A
  container that can't load its model fails at startup rather than serving
  errors (REQ-0012).
- Abuse cap: at most **5 concurrent executions**, so a request flood
  throttles instead of running up a bill (NFR-0008).

### 5. Two observability stores, on purpose

| Question | Answered by |
|---|---|
| "What happened with *this* prediction?" | **DynamoDB audit log** — full record per prediction, fetched by ID (see `docs/DYNAMODB_DESIGN.md`; no table scans, 90-day auto-delete) |
| "What do predictions look like *lately*?" | **CloudWatch** — each request logs its input values; `scripts/drift_report.py` compares recent distributions against the training baselines stored in `model_meta.json` (PSI > 0.2 = drift) |

Cost note: only 6 CloudWatch metrics are extracted (under the 10 free);
everything else rides in log lines, which cost pennies. A unit test fails
the build if the metric count ever exceeds 10.

## The Streamlit app is deliberately dumb

The web form holds **no model and no AWS credentials** — it only calls the
public API, like any other client. That means exactly one copy of the model
exists in the world (the one in Lambda), so the demo can never show
different answers than production (REQ-0016). A test forbids the app from
importing sklearn, boto3, or anything from `src/`.

## Which code lives where

```
training/       # offline only: build, evaluate, package the model
src/
  handlers/     # Lambda entry point: parse request → call service → respond
  services/     # the prediction logic: validate → predict → decide → log
  data/         # ALL AWS SDK calls: DynamoDB writes, metric emission
  model/        # loads model.joblib + model_meta.json at startup
  shared/       # input schema, errors, responses, logging
streamlit_app/  # the web form (HTTP client only)
scripts/        # operator tools: drift report, audit queries, smoke test
template.yaml   # every AWS resource, as code
```

Two boundary rules, both test-enforced:

- `training/` and `src/` never import each other — the artifact files are
  their only interface, and training-only libraries (pandas, matplotlib)
  never enter the inference image.
- boto3 (the AWS SDK) appears only in `src/data/`, so the business logic is
  testable with plain fakes.

## Cost ceiling: < $5/month (NFR-0008)

Nothing runs while nobody's asking: Lambda bills per request, DynamoDB per
operation (with 90-day auto-delete), the Function URL is free, and Streamlit
hosting is free. The caps that keep it that way: ≤ 10 extracted CloudWatch
metrics (test-enforced), 30-day log retention, a keep-2-images registry
policy, reserved concurrency of 5, and an account-level $5 budget alarm.
Measured steady state: **under $1/month**.
