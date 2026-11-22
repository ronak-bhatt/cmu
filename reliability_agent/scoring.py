"""Deterministic, versioned scoring. The model never sets a score."""
from __future__ import annotations
from .config import BAND_THRESHOLDS, BAND_DEDUCTION, CATEGORY_WEIGHTS


def priority(severity: int, likelihood: int, impact: int) -> int:
    return severity * likelihood * impact          # 1..125


def band_for(p: int) -> str:
    for threshold, band in BAND_THRESHOLDS:
        if p >= threshold:
            return band
    return "low"


def reliability_score(findings) -> tuple[int, dict]:
    """Start at 100; deduct by band inside each category, capped at the category weight."""
    deducted = {c: 0 for c in CATEGORY_WEIGHTS}
    for f in findings:
        if f.category in deducted:
            deducted[f.category] += BAND_DEDUCTION[f.band]
    detail, total = {}, 0
    for cat, weight in CATEGORY_WEIGHTS.items():
        d = min(weight, deducted[cat])
        detail[cat] = {"weight": weight, "deducted": d, "remaining": weight - d}
        total += d
    return max(0, 100 - total), detail
