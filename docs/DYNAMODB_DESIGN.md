# DYNAMODB_DESIGN.md — Prediction audit log

One table, `churn-predictions`, on-demand capacity. It exists for one reason:
**traceability** (REQ-0010/0011) — any prediction anyone has ever seen can be
looked up and attributed to the model version that produced it. Aggregate
monitoring lives in CloudWatch, not here (see `docs/ARCHITECTURE.md`).

Same rules as `serverless-order-api`: every query maps to a documented access
pattern below; **no Scans, ever**; adding a query means updating this doc first.

## Access patterns

| ID | Pattern | Used by |
|---|---|---|
| AP1 | Get one prediction by `prediction_id` | Support: "customer disputes this score" |
| AP2 | List predictions by `model_version`, newest first | Model audit: "what did 1.0.0+ab12cd3 decide?" |
| AP3 | List predictions for a UTC day, newest first | Ops spot-checks; drift investigation drill-down |

## Table schema

Base table:

| Attr | Value | Notes |
|---|---|---|
| `PK` | `PRED#<prediction_id>` | prediction_id is a ULID (time-sortable) |
| `SK` | `META` | single item per prediction |
| `entityType` | `Prediction` | |
| `predictionId` | ULID | |
| `modelVersion` | e.g. `1.0.0+ab12cd3` | from `model_meta.json`, never client-supplied |
| `churnProbability` | number | |
| `churnPredicted` | bool | |
| `threshold` | number | threshold in force at prediction time |
| `features` | map | the validated raw inputs |
| `createdAt` | ISO-8601 UTC | |
| `expiresAt` | epoch seconds | TTL: 90 days |

GSI1 — by model version (AP2):

| Attr | Value |
|---|---|
| `GSI1PK` | `MODEL#<modelVersion>` |
| `GSI1SK` | `TS#<createdAt>#<prediction_id>` |

GSI2 — by day (AP3):

| Attr | Value |
|---|---|
| `GSI2PK` | `DAY#<yyyy-mm-dd>` |
| `GSI2SK` | `TS#<createdAt>#<prediction_id>` |

Both GSIs project `KEYS_ONLY` + `churnProbability`, `churnPredicted`,
`modelVersion` (INCLUDE) — enough to render a list without a second read;
follow with AP1 for full features.

## Query shapes

- **AP1:** `GetItem(PK=PRED#<id>, SK=META)`
- **AP2:** `Query GSI1, GSI1PK = MODEL#<version>, ScanIndexForward=False`,
  cursor pagination via `LastEvaluatedKey`
- **AP3:** `Query GSI2, GSI2PK = DAY#<date>, ScanIndexForward=False`, same
  pagination

## Write path

Single `PutItem` per prediction from the repository layer
(`src/data/prediction_repository.py` — the only module holding boto3 for
DynamoDB). Condition expression `attribute_not_exists(PK)` — a ULID collision
should be impossible, so surfacing it as an error beats silently overwriting
an audit record.

**Best-effort contract (REQ-0011):** the service layer wraps the write in a
try/except; on failure it logs the error with the full item and still returns
the prediction. An audit log that can take down inference would be worse than
a gap in the audit log.

## Retention

TTL on `expiresAt` at 90 days. The table is an operational audit window, not a
data warehouse; anything needed longer-term should be exported, not retained
here.

## Reader access

AP2/AP3 are consumed by `scripts/audit_query.py` (CLI, read-only IAM), not by
the Lambda — the inference function's policy allows `PutItem` only (NFR-0004).
