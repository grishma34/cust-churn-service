"""Evidence plots for the artifact (PLAN.md Phase 2): cost curve, reliability
curve, test ROC. Written next to the model so every artifact carries its own
evaluation record."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from training import config  # noqa: E402


def write_plots(result, threshold_result, roc_points, output_dir: Path) -> list[Path]:
    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    written = []

    # Cost curve (validation): the argument for not defaulting to 0.5
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(threshold_result.grid, threshold_result.costs, lw=1.5)
    ax.axvline(threshold_result.threshold, color="tab:green", ls="--", label="chosen t")
    ax.axvline(
        threshold_result.analytic_optimum, color="tab:orange", ls=":", label="analytic optimum"
    )
    ax.axvline(0.5, color="tab:red", ls=":", alpha=0.6, label="default 0.5")
    ax.set_xlabel("decision threshold")
    ax.set_ylabel(
        f"expected cost on validation "
        f"(${config.COST_FALSE_POSITIVE:.0f}·FP + ${config.COST_FALSE_NEGATIVE:.0f}·FN)"
    )
    ax.legend()
    written.append(plots_dir / "cost_curve.png")
    fig.savefig(written[-1], dpi=120, bbox_inches="tight")
    plt.close(fig)

    # Reliability curve (validation): why the cost threshold is trustworthy
    proba = result.pipeline.predict_proba(result.splits.X_val)[:, 1]
    y_val = result.splits.y_val
    bins = np.clip((proba * config.CALIBRATION_BINS).astype(int), 0, config.CALIBRATION_BINS - 1)
    mean_pred, frac_pos = [], []
    for b in range(config.CALIBRATION_BINS):
        mask = bins == b
        if mask.any():
            mean_pred.append(proba[mask].mean())
            frac_pos.append(y_val[mask].mean())
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "k:", alpha=0.5)
    ax.plot(mean_pred, frac_pos, "o-")
    ax.set_xlabel("mean predicted probability")
    ax.set_ylabel("observed churn rate")
    ax.set_title(f"reliability (val), ECE={result.val_metrics['ece']:.3f}")
    written.append(plots_dir / "reliability_curve.png")
    fig.savefig(written[-1], dpi=120, bbox_inches="tight")
    plt.close(fig)

    # ROC (test) — drawn from the one-and-only test evaluation's stored points
    fpr, tpr = roc_points
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "k:", alpha=0.5)
    ax.plot(fpr, tpr)
    ax.set_xlabel("false positive rate")
    ax.set_ylabel("true positive rate")
    ax.set_title("ROC (test split)")
    written.append(plots_dir / "roc_curve.png")
    fig.savefig(written[-1], dpi=120, bbox_inches="tight")
    plt.close(fig)

    return written
