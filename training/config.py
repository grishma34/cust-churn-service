"""All training knobs in one place (claude.md: determinism — `random_state`
from here, never inline)."""

RANDOM_SEED = 42

# Stratified 60/20/20 split (PLAN.md Phase 1). Fractions of the FULL dataset.
TEST_FRACTION = 0.20
VAL_FRACTION = 0.20

CV_FOLDS = 5

# Business cost model (REQ-0003): a missed churner costs ~9x a wasted
# retention offer. Threshold selection (Phase 2) minimizes expected cost.
COST_FALSE_POSITIVE = 50.0
COST_FALSE_NEGATIVE = 450.0

# Calibration gate (REQ-0004): if expected calibration error on the validation
# split exceeds this, the winning estimator is wrapped in CalibratedClassifierCV.
CALIBRATION_MAX_ECE = 0.05
CALIBRATION_BINS = 10
