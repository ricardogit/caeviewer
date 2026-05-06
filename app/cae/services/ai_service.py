"""AI analysis service for FEA field data — hotspot detection and structural risk."""
import numpy as np
from typing import List, Union


def analyze_field(
    values: List[Union[float, List[float]]],
    field_type: str = "nodal",
    threshold_ratio: float = 0.9,
) -> dict:
    """
    Analyze a scalar or vector field for structural insights.

    Parameters
    ----------
    values : list of scalars or vectors (magnitude is computed for vectors)
    field_type : "nodal" or "elemental"
    threshold_ratio : fraction of the global max used as hotspot threshold (0–1)

    Returns a dict with hotspot indices, statistics, risk level, and recommendation.
    """
    arr = np.array(values, dtype=np.float64)

    # Vector field → per-node magnitude
    if arr.ndim == 2:
        arr = np.linalg.norm(arr, axis=1)

    n = len(arr)
    if n == 0:
        return {"error": "Empty values array"}

    abs_arr = np.abs(arr)
    global_max = float(abs_arr.max())

    # Hotspot detection: nodes/elements above the threshold magnitude
    threshold = threshold_ratio * global_max
    hotspot_indices = np.where(abs_arr >= threshold)[0].tolist()

    stats = {
        "min":  float(arr.min()),
        "max":  float(arr.max()),
        "mean": float(arr.mean()),
        "std":  float(arr.std()),
        "p95":  float(np.percentile(abs_arr, 95)),
        "p99":  float(np.percentile(abs_arr, 99)),
    }

    concentration = len(hotspot_indices) / n

    if concentration < 0.01:
        risk = "low"
        recommendation = (
            "Stress concentrated in <1% of nodes. Load path is efficient — "
            "no structural changes required."
        )
    elif concentration < 0.05:
        risk = "medium"
        recommendation = (
            "Moderate concentration (1–5% of nodes). Consider adding fillets, "
            "locally increasing cross-section, or redistributing boundary conditions."
        )
    else:
        risk = "high"
        recommendation = (
            "High concentration (>5% of nodes). Structural redesign recommended: "
            "increase section, change material grade, or redistribute load paths."
        )

    return {
        "hotspot_indices":     hotspot_indices,
        "hotspot_count":       len(hotspot_indices),
        "threshold":           float(threshold),
        "threshold_ratio":     threshold_ratio,
        "total_nodes":         n,
        "concentration_ratio": concentration,
        "statistics":          stats,
        "risk_level":          risk,
        "recommendation":      recommendation,
    }
