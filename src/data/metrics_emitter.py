"""CloudWatch input-distribution telemetry via Embedded Metric Format
(REQ-0014), within the NFR-0008 cost cap.

Extracted-metric tally — MUST stay ≤ 10 (the always-free tier), and there are
NO dimensions (each dimension value would multiply the billable metric count):

    1. tenure               4. ChurnProbability
    2. MonthlyCharges       5. PredictionCount
    3. TotalCharges         6. ChurnPredictedCount

Everything else (all categorical features, model version) rides on the same
log line as plain properties — free to store, queryable with Logs Insights,
and the drift report's source for categorical distributions (REQ-0015).

EMF needs no SDK: a JSON line on stdout is enough — the Lambda log pipeline
extracts the metrics. That's why this module holds no boto3 despite living in
src/data/.
"""

import json
import os
import time
from collections.abc import Callable
from typing import Any

from shared.schema import NUMERIC_FIELDS

DEFAULT_NAMESPACE = "cust-churn-service"


class MetricsEmitter:
    def __init__(self, namespace: str | None = None, writer: Callable[[str], None] = print):
        self._namespace = namespace or os.environ.get("METRICS_NAMESPACE", DEFAULT_NAMESPACE)
        self._writer = writer

    def emit(
        self,
        features: dict[str, Any],
        probability: float,
        predicted: bool,
        model_version: str,
    ) -> None:
        values: dict[str, Any] = {
            "ChurnProbability": probability,
            "PredictionCount": 1,
            "ChurnPredictedCount": 1 if predicted else 0,
        }
        for field in NUMERIC_FIELDS:
            if features.get(field) is not None:  # null TotalCharges: no metric point
                values[field] = float(features[field])

        document = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self._namespace,
                        "Dimensions": [[]],
                        "Metrics": [{"Name": name, "Unit": "None"} for name in values],
                    }
                ],
            },
            **values,
            "modelVersion": model_version,
            "features": {k: v for k, v in features.items() if k not in NUMERIC_FIELDS},
        }
        self._writer(json.dumps(document, default=str))
