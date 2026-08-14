"""Column definitions and the ONE Pipeline (REQ-0005).

Everything the model needs at serve time lives inside the object returned by
`build_pipeline()`: imputation, scaling, one-hot encoding, classifier. The
serving layer calls `pipeline.predict_proba` on raw values and nothing else.

Two constraints shape the implementation:

- The artifact must deserialize in the inference image, which has sklearn and
  numpy but NOT pandas and NOT this package (claude.md rule 4). Therefore the
  Pipeline contains only sklearn built-ins (no custom transformers, nothing to
  import from `training` at unpickle time), and the ColumnTransformer selects
  columns by POSITION, not name — input is a plain object-dtype ndarray whose
  columns follow FEATURE_COLUMNS order. tests/training/test_pipeline.py pins
  this order to src/shared/schema.py so training and serving cannot drift.
- HistGradientBoosting needs dense input, so the encoder emits dense output.
"""

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

NUMERIC_COLUMNS: tuple[str, ...] = (
    "tenure",
    "MonthlyCharges",
    "TotalCharges",
)

CATEGORICAL_COLUMNS: tuple[str, ...] = (
    "gender",
    "SeniorCitizen",
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

FEATURE_COLUMNS: tuple[str, ...] = NUMERIC_COLUMNS + CATEGORICAL_COLUMNS

TARGET_COLUMN = "Churn"
POSITIVE_LABEL = "Yes"

_NUMERIC_POSITIONS = list(range(len(NUMERIC_COLUMNS)))
_CATEGORICAL_POSITIONS = list(range(len(NUMERIC_COLUMNS), len(FEATURE_COLUMNS)))


def build_pipeline(estimator) -> Pipeline:
    """Preprocessing + estimator as a single fittable/serializable unit."""
    preprocess = ColumnTransformer(
        transformers=[
            (
                "numeric",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                _NUMERIC_POSITIONS,
            ),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        # handle_unknown="ignore": an unseen category encodes as
                        # all-zeros instead of crashing serving; API-side domain
                        # validation (REQ-0013) is the real gate.
                        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                _CATEGORICAL_POSITIONS,
            ),
        ]
    )
    return Pipeline([("preprocess", preprocess), ("classifier", estimator)])
