"""Audit-log reader: the operator-side consumer of AP1/AP2/AP3
(docs/DYNAMODB_DESIGN.md). Runs under the operator's own credentials — the
Lambda's role deliberately cannot read the table (NFR-0004).

Usage:
    python scripts/audit_query.py get 01JXXXXXXXXXXXXXXXXXXXXXXX
    python scripts/audit_query.py by-model 1.0.0+ccb8bab [--limit 20]
    python scripts/audit_query.py by-day 2026-08-14 [--limit 20]
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data.prediction_repository import PredictionRepository  # noqa: E402

STACK_NAME = "cust-churn-service"


def _table_name() -> str:
    if "TABLE_NAME" in os.environ:
        return os.environ["TABLE_NAME"]
    import boto3

    outputs = boto3.client("cloudformation").describe_stacks(StackName=STACK_NAME)["Stacks"][0][
        "Outputs"
    ]
    return next(o["OutputValue"] for o in outputs if o["OutputKey"] == "TableName")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["get", "by-model", "by-day"])
    parser.add_argument("key", help="prediction id / model version / YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    repo = PredictionRepository(table_name=_table_name())
    if args.command == "get":
        item = repo.get_prediction(args.key)
        if item is None:
            print("not found", file=sys.stderr)
            return 1
        print(json.dumps(item, indent=2, default=str))
        return 0

    if args.command == "by-model":
        items, cursor = repo.list_by_model_version(args.key, limit=args.limit)
    else:
        items, cursor = repo.list_by_day(args.key, limit=args.limit)
    for item in items:
        print(json.dumps(item, default=str))
    if cursor:
        print(f"# more results available (showed {len(items)})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
