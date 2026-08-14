"""Input schema for POST /predict (docs/API_SPEC.md).

Field names and types are structural facts of the Telco dataset and stable.
CATEGORICAL_DOMAINS is GENERATED from the dataset by
`scripts/gen_schema_domains.py` — never hand-edit the marked block; regenerate
it, so API validation and the Pipeline's vocabulary cannot drift (REQ-0013).
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

# BEGIN GENERATED DOMAINS — scripts/gen_schema_domains.py; do not hand-edit
CATEGORICAL_DOMAINS: dict[str, tuple[str | int, ...]] = {
    "gender": (
        "Female",
        "Male",
    ),
    "SeniorCitizen": (
        0,
        1,
    ),
    "Partner": (
        "No",
        "Yes",
    ),
    "Dependents": (
        "No",
        "Yes",
    ),
    "PhoneService": (
        "No",
        "Yes",
    ),
    "MultipleLines": (
        "No",
        "No phone service",
        "Yes",
    ),
    "InternetService": (
        "DSL",
        "Fiber optic",
        "No",
    ),
    "OnlineSecurity": (
        "No",
        "No internet service",
        "Yes",
    ),
    "OnlineBackup": (
        "No",
        "No internet service",
        "Yes",
    ),
    "DeviceProtection": (
        "No",
        "No internet service",
        "Yes",
    ),
    "TechSupport": (
        "No",
        "No internet service",
        "Yes",
    ),
    "StreamingTV": (
        "No",
        "No internet service",
        "Yes",
    ),
    "StreamingMovies": (
        "No",
        "No internet service",
        "Yes",
    ),
    "Contract": (
        "Month-to-month",
        "One year",
        "Two year",
    ),
    "PaperlessBilling": (
        "No",
        "Yes",
    ),
    "PaymentMethod": (
        "Bank transfer (automatic)",
        "Credit card (automatic)",
        "Electronic check",
        "Mailed check",
    ),
}
# END GENERATED DOMAINS
