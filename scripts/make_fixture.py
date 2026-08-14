"""Regenerate data/fixtures/telco_60.csv from data/telco.csv.

Deterministic (fixed seed): stratified 60-row sample at the dataset's churn
rate, force-including 2 blank-TotalCharges rows so the fixture exercises the
string-coercion path (see data/README.md). Stdlib only — runnable without the
training venv.
"""

import csv
import random
from pathlib import Path

SEED = 42
N_ROWS = 60
N_CHURN = 16  # ≈ the dataset's 26.5% churn rate
N_BLANK_TOTALCHARGES = 2

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "telco.csv"
TARGET = ROOT / "data" / "fixtures" / "telco_60.csv"


def main() -> None:
    with SOURCE.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    blank = [r for r in rows if r["TotalCharges"].strip() == ""]
    churn = [r for r in rows if r["Churn"] == "Yes"]
    stay = [r for r in rows if r["Churn"] == "No" and r["TotalCharges"].strip() != ""]

    rng = random.Random(SEED)
    picked = rng.sample(blank, N_BLANK_TOTALCHARGES)  # blank rows are all Churn == "No"
    picked += rng.sample(churn, N_CHURN)
    picked += rng.sample(stay, N_ROWS - len(picked))
    picked.sort(key=lambda r: r["customerID"])  # stable output ordering

    with TARGET.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(picked)
    print(f"wrote {len(picked)} rows -> {TARGET}")


if __name__ == "__main__":
    main()
