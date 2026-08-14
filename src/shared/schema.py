"""Input schema for POST /predict (docs/API_SPEC.md).

Phase 0 stub: field names and types only — these are structural facts of the
Telco dataset and stable. Categorical DOMAINS are generated from the training
data in Phase 2 (scripts side of training/metadata.py) so API validation and
the Pipeline's vocabulary cannot drift; do not hand-type them here.
"""

NUMERIC_FIELDS: tuple[str, ...] = (
    "tenure",
    "MonthlyCharges",
    "TotalCharges",
)

CATEGORICAL_FIELDS: tuple[str, ...] = (
    "gender",
    "SeniorCitizen",  # 0/1 in the source data; treated as categorical
    "Partner",
    "Dependents",
    "PhoneService",
    "MultipleLines",
    "InternetService",
    "OnlineSecurity",
    "OnlineBackup",
    "DeviceProtection",
    "TechSupport",
    "StreamingTV",
    "StreamingMovies",
    "Contract",
    "PaperlessBilling",
    "PaymentMethod",
)

FEATURE_FIELDS: tuple[str, ...] = NUMERIC_FIELDS + CATEGORICAL_FIELDS

# Generated in Phase 2 from training data; empty means "domain validation not
# yet active" and ValidationError for domains must not be raised from a stub.
CATEGORICAL_DOMAINS: dict[str, tuple[str, ...]] = {}
