# DYNAMODB_DESIGN.md — the prediction audit log

## Why this table exists

One reason: **traceability** (REQ-0010/0011). Every prediction the service
has ever made is written here with its inputs, its outputs, and the model
version that produced it — so "a customer disputes this score" or "what did
model X decide last week?" always has an answer.

Aggregate monitoring ("what does traffic look like lately?") deliberately
does NOT live here — that's CloudWatch's job (see `docs/ARCHITECTURE.md`).

## How to read this document

DynamoDB isn't like a SQL database: you don't write ad-hoc queries later.
You decide **up front** exactly which questions the table must answer, then
shape the keys so each question is one fast, cheap lookup. Everything below
follows from the three questions we committed to:

| ID | The question | Who asks it |
|---|---|---|
| AP1 | "Show me prediction `<id>`" | Support, when a score is disputed |
| AP2 | "What did model version X predict?" (newest first) | Model audits, champion/challenger comparisons |
| AP3 | "What was predicted on day Y?" (newest first) | Ops spot-checks, drift investigations |

Two hard rules:

- **No table scans, ever.** A scan reads the whole table to find something —
  fine at 100 rows, ruinous at 100 million. Every read above uses an index
  built for it, and a test fails the build if a `Scan` call ever appears.
- **New question ⇒ update this document first**, then the code.

## The table

One item per prediction. The main key answers AP1; two secondary indexes
(GSIs — think "extra sort orders maintained automatically") answer AP2 and
AP3.

**Main item** (`churn-predictions`, on-demand billing):

| Attribute | Value | Notes |
|---|---|---|
| `PK` | `PRED#<prediction_id>` | The ID is a ULID — sortable by creation time |
| `SK` | `META` | One item per prediction |
| `entityType` | `Prediction` | |
| `modelVersion` | e.g. `1.0.0+ab12cd3` | Comes from the model's own metadata, never from the client |
| `churnProbability`, `churnPredicted`, `threshold` | the decision | Numbers stored as Decimal (DynamoDB rejects floats) |
| `features` | map of all 19 inputs | Exactly what the model saw |
| `createdAt` | ISO-8601 UTC timestamp | |
| `expiresAt` | epoch seconds | **TTL: the record auto-deletes after 90 days** — audit window, not a data warehouse |

**GSI1 — answers AP2** (by model version, newest first):
partition `MODEL#<version>`, sort `TS#<createdAt>#<id>`.

**GSI2 — answers AP3** (by UTC day, newest first):
partition `DAY#<yyyy-mm-dd>`, sort `TS#<createdAt>#<id>`.

Both indexes copy in only the headline fields (`churnProbability`,
`churnPredicted`, `modelVersion`) — enough to render a list cheaply; follow
up with AP1 when you need the full inputs. Note this means list results
carry the table key (`PK`), not a `predictionId` attribute — derive the id
from `PK`.

## How reads and writes actually happen

- **Write** — one conditional `PutItem` per prediction, from
  `src/data/prediction_repository.py` (the only file that talks to DynamoDB).
  The condition (`attribute_not_exists(PK)`) means a duplicate ID would
  error loudly instead of silently overwriting an audit record.
- **Best-effort contract (REQ-0011)** — if the write fails, the caller still
  gets their prediction; the failure is logged. An audit log that could take
  down the service would be worse than a gap in the audit log. Never "fix"
  this by making the write blocking.
- **AP1** — `GetItem` on `PK`/`SK`.
- **AP2 / AP3** — `Query` on the matching index, newest first, with cursor
  pagination for long result sets.

## Who can touch it

The Lambda's permissions allow **append only** — one `PutItem` action on
this one table, nothing else (NFR-0004). It cannot read, update, or delete.
Humans read the log through `scripts/audit_query.py`, which runs under the
operator's own AWS credentials.
