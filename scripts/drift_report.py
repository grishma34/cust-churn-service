"""Data-drift report (REQ-0015): compare recent live input distributions
against the training baselines recorded in model_meta.json, via PSI
(Population Stability Index). PSI > 0.2 flags drift; 0.1-0.2 is a warning.

Both numeric and categorical distributions come from ONE Logs Insights query
over the EMF lines the service already emits (REQ-0014) — no extra metrics,
no extra cost beyond pennies of query scan (NFR-0008).

Usage:
    python scripts/drift_report.py [--hours 24] [--meta artifacts/model_meta.json]

Exit codes: 0 clean, 2 drift flagged — cron-able.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

# Baseline quantiles stored per REQ-0007 → 6 bins with known expected mass
_QUANTILE_KEYS = ("p10", "p25", "p50", "p75", "p90")
_EXPECTED_MASS = (0.10, 0.15, 0.25, 0.25, 0.15, 0.10)
_EPS = 1e-4

FLAG_THRESHOLD = 0.2
WARN_THRESHOLD = 0.1


def psi(expected: np.ndarray, actual: np.ndarray) -> float:
    """Sum over bins of (actual - expected) * ln(actual / expected)."""
    expected = np.clip(np.asarray(expected, dtype=float), _EPS, None)
    actual = np.clip(np.asarray(actual, dtype=float), _EPS, None)
    expected = expected / expected.sum()
    actual = actual / actual.sum()
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def numeric_psi(values: list[float], baseline: dict) -> float:
    edges = [baseline["quantiles"][key] for key in _QUANTILE_KEYS]
    counts, _ = np.histogram(np.asarray(values, dtype=float), bins=[-np.inf, *edges, np.inf])
    return psi(np.array(_EXPECTED_MASS), counts)


def categorical_psi(observed_counts: dict[str, int], baseline: dict) -> float:
    baseline_freqs = baseline["frequencies"]
    labels = sorted(set(baseline_freqs) | set(observed_counts))
    expected = np.array([baseline_freqs.get(label, 0.0) for label in labels])
    actual = np.array([observed_counts.get(label, 0) for label in labels], dtype=float)
    return psi(expected, actual)


def build_report(rows: list[dict], baselines: dict) -> list[dict]:
    """rows: one dict per prediction with numeric fields at the top level and
    categoricals under their bare name (as returned by the Insights query)."""
    report = []
    for feature, baseline in baselines.items():
        if baseline["type"] == "numeric":
            values = [float(r[feature]) for r in rows if r.get(feature) not in (None, "")]
            score = numeric_psi(values, baseline) if values else None
            n = len(values)
        else:
            counts: dict[str, int] = {}
            for r in rows:
                value = r.get(feature)
                if value not in (None, ""):
                    counts[str(value)] = counts.get(str(value), 0) + 1
            score = categorical_psi(counts, baseline) if counts else None
            n = sum(counts.values())
        status = (
            "no-data"
            if score is None
            else "DRIFT"
            if score > FLAG_THRESHOLD
            else "warn"
            if score > WARN_THRESHOLD
            else "ok"
        )
        report.append({"feature": feature, "psi": score, "n": n, "status": status})
    return report


def fetch_live_rows(log_group: str, hours: float, baselines: dict) -> list[dict]:
    """One Logs Insights query pulls every feature of every EMF line."""
    import boto3

    logs = boto3.client("logs")
    selects = []
    for feature, baseline in baselines.items():
        if baseline["type"] == "numeric":
            selects.append(feature)
        else:
            selects.append(f"features.{feature} as {feature}")
    query = "filter ispresent(modelVersion) | fields " + ", ".join(selects) + " | limit 10000"
    end = int(time.time())
    start = logs.start_query(
        logGroupName=log_group,
        startTime=end - int(hours * 3600),
        endTime=end,
        queryString=query,
    )["queryId"]
    while True:
        result = logs.get_query_results(queryId=start)
        if result["status"] in ("Complete", "Failed", "Cancelled"):
            break
        time.sleep(1)
    if result["status"] != "Complete":
        raise RuntimeError(f"Logs Insights query {result['status']}")
    return [{cell["field"]: cell["value"] for cell in row} for row in result["results"]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta", type=Path, default=Path("artifacts/model_meta.json"))
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--log-group", default="/aws/lambda/cust-churn-service-inference")
    args = parser.parse_args(argv)

    meta = json.loads(args.meta.read_text())
    print(f"baselines from model {meta['model_version']} (trained {meta['trained_at']})")
    print("note: baselines are deterministic (fixed seed/data), so they are comparable")
    print("across retrains of the same dataset even if the deployed sha differs.\n")

    rows = fetch_live_rows(args.log_group, args.hours, meta["baselines"])
    print(f"live sample: {len(rows)} predictions over the last {args.hours:g}h\n")
    report = build_report(rows, meta["baselines"])

    width = max(len(r["feature"]) for r in report)
    for r in sorted(report, key=lambda r: -(r["psi"] or -1)):
        score = "  -  " if r["psi"] is None else f"{r['psi']:.3f}"
        print(f"  {r['feature']:<{width}}  psi={score}  n={r['n']:<5} {r['status']}")

    flagged = [r for r in report if r["status"] == "DRIFT"]
    print(f"\n{len(flagged)} feature(s) over the {FLAG_THRESHOLD} threshold")
    return 2 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
