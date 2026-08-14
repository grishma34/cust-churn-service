"""Regenerate CATEGORICAL_DOMAINS in src/shared/schema.py from the dataset.

Deterministic (sorted values), stdlib only. Run after any dataset change:

    python scripts/gen_schema_domains.py --data data/telco.csv

The domains are a data dictionary for API validation (REQ-0013), generated
rather than hand-typed so the API's vocabulary can never drift from what the
Pipeline was trained on.
"""

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "src" / "shared" / "schema.py"
BEGIN = "# BEGIN GENERATED DOMAINS"
END = "# END GENERATED DOMAINS"

# SeniorCitizen arrives as a JSON number (see docs/API_SPEC.md example), so
# its domain is kept as ints; every other categorical is a string.
INT_VALUED_FIELDS = {"SeniorCitizen"}


def collect_domains(csv_path: Path, fields: tuple[str, ...]) -> dict[str, list]:
    domains: dict[str, set] = {field: set() for field in fields}
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            for field in fields:
                value = row[field]
                domains[field].add(int(value) if field in INT_VALUED_FIELDS else value)
    return {field: sorted(values) for field, values in domains.items()}


def render_block(domains: dict[str, list]) -> str:
    """One value per line with trailing commas — a shape `ruff format` keeps
    as-is (magic trailing comma), so regeneration is idempotent."""
    lines = [
        f"{BEGIN} — scripts/gen_schema_domains.py; do not hand-edit",
        "CATEGORICAL_DOMAINS: dict[str, tuple[str | int, ...]] = {",
    ]
    for field, values in domains.items():
        lines.append(f'    "{field}": (')
        for value in values:
            rendered = f'"{value}"' if isinstance(value, str) else str(value)
            lines.append(f"        {rendered},")
        lines.append("    ),")
    lines += ["}", END]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "telco.csv")
    args = parser.parse_args()

    # Import lazily so this script stays runnable from a bare checkout
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from shared.schema import CATEGORICAL_FIELDS

    domains = collect_domains(args.data, CATEGORICAL_FIELDS)
    source = SCHEMA_PATH.read_text()
    pattern = re.compile(re.escape(BEGIN) + ".*?" + re.escape(END), re.DOTALL)
    assert pattern.search(source), "schema.py generated-domain markers missing"
    SCHEMA_PATH.write_text(pattern.sub(render_block(domains), source))
    print(f"wrote {sum(len(v) for v in domains.values())} domain values -> {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
