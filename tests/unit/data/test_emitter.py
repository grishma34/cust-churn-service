"""EMF emitter tests (REQ-0014) — including THE cost guard: never more than
10 extracted metrics and no dimensions (NFR-0008)."""

import json

import pytest

from data.metrics_emitter import MetricsEmitter


@pytest.fixture
def emitted(valid_payload):
    lines = []
    MetricsEmitter(namespace="test-ns", writer=lines.append).emit(
        valid_payload, probability=0.72, predicted=True, model_version="1.0.0+abc1234"
    )
    [line] = lines
    return json.loads(line)


def test_valid_emf_structure(emitted):
    [spec] = emitted["_aws"]["CloudWatchMetrics"]
    assert spec["Namespace"] == "test-ns"
    assert isinstance(emitted["_aws"]["Timestamp"], int)
    metric_names = {m["Name"] for m in spec["Metrics"]}
    # every declared metric has its value at the document root (EMF contract)
    for name in metric_names:
        assert name in emitted


def test_cost_cap_max_10_metrics_and_no_dimensions(emitted):
    """$0.30/metric/month past the free 10; a dimension value multiplies the
    billable count. This test failing means the AWS bill grows (NFR-0008)."""
    [spec] = emitted["_aws"]["CloudWatchMetrics"]
    assert len(spec["Metrics"]) <= 10
    assert spec["Dimensions"] == [[]]


def test_numeric_features_are_metrics_categoricals_are_properties(emitted):
    [spec] = emitted["_aws"]["CloudWatchMetrics"]
    metric_names = {m["Name"] for m in spec["Metrics"]}
    assert {"tenure", "MonthlyCharges", "TotalCharges"} <= metric_names
    assert {"ChurnProbability", "PredictionCount", "ChurnPredictedCount"} <= metric_names
    # categoricals ride as plain properties for Logs Insights, not metrics
    assert emitted["features"]["Contract"] == "Month-to-month"
    assert "Contract" not in metric_names
    assert emitted["modelVersion"] == "1.0.0+abc1234"
    assert emitted["PredictionCount"] == 1
    assert emitted["ChurnPredictedCount"] == 1


def test_null_totalcharges_emits_no_metric_point(valid_payload):
    lines = []
    MetricsEmitter(namespace="test-ns", writer=lines.append).emit(
        valid_payload | {"TotalCharges": None},
        probability=0.3,
        predicted=False,
        model_version="v",
    )
    emitted = json.loads(lines[0])
    [spec] = emitted["_aws"]["CloudWatchMetrics"]
    assert "TotalCharges" not in {m["Name"] for m in spec["Metrics"]}
    assert emitted["ChurnPredictedCount"] == 0
