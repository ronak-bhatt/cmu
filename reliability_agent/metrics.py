"""Runtime monitoring and evaluation metrics (groundedness, calibration, consistency, escalation...)."""
from __future__ import annotations
import statistics
from dataclasses import dataclass
from .config import LIMITS, TARGETS
from .models import Assessment, ChangeEvent


def groundedness(a: Assessment) -> float:
    """Share of findings whose every citation points at a current, active source."""
    active = {s["ref"] for s in a.sources if s["status"] == "active"}
    judged = [f for f in a.findings if f.verdict not in ("unverified", "drift")]   # policy-backed findings
    if not judged:
        return 1.0
    return sum(bool(f.citations) and all(c in active for c in f.citations) for f in judged) / len(judged)


def policy_currency(a: Assessment) -> float:
    pol = [s for s in a.sources if s["source"] in ("policy", "exception")]
    return 1.0 if not pol else sum(s["status"] == "active" for s in pol) / len(pol)


class MetricsCollector:
    def __init__(self):
        self.records: list[dict] = []
        self.feedback: list[dict] = []

    def record(self, a: Assessment, state, duration: float) -> None:
        self.records.append({
            "investigation": a.investigation_id, "latency_s": duration, "tool_calls": state.tool_calls,
            "tool_failures": len(state.tool_failures), "escalated": a.requires_human,
            "safety_events": len(a.safety_events), "groundedness": groundedness(a),
            "policy_currency": policy_currency(a), "score": a.score})

    def record_feedback(self, investigation_id: str, finding_id: str, confirmed: bool, confidence: str) -> None:
        """Engineer feedback is stored for review; it never edits rules or weights automatically."""
        self.feedback.append({"investigation": investigation_id, "finding": finding_id,
                              "confirmed": confirmed, "confidence": confidence})

    def calibration(self) -> dict:
        out = {}
        for level in ("High", "Medium", "Low"):
            rows = [f for f in self.feedback if f["confidence"] == level]
            if rows:
                out[level] = round(sum(f["confirmed"] for f in rows) / len(rows), 3)
        return out

    def alerts(self) -> list[str]:
        """Runtime monitoring: tool failures, call volume, missing citations, stale policy, safety events,
        latency and score drift, checked against the initial targets in config.TARGETS."""
        r, out = self.records, []
        if not r:
            return out
        failures = sum(x["tool_failures"] for x in r)
        if failures:
            out.append(f"tool failures: {failures} across {len(r)} investigations")
        if any(x["tool_calls"] > TARGETS["call_volume_ratio"] * LIMITS.max_tool_calls for x in r):
            out.append("abnormal tool-call volume: an investigation used most of its budget")
        if statistics.mean(x["groundedness"] for x in r) < TARGETS["groundedness"]:
            out.append("missing or non-current citations: groundedness below target")
        if statistics.mean(x["policy_currency"] for x in r) < TARGETS["policy_currency"]:
            out.append("a cited policy was not active")
        if any(x["safety_events"] for x in r):
            out.append("safety events recorded (prompt injection, secret exposure or blocked tool call)")
        if max(x["latency_s"] for x in r) > TARGETS["latency_s"]:
            out.append("investigation latency above target")
        w = TARGETS["drift_window"]
        if len(r) >= 2 * w:
            recent, prior = r[-w:], r[-2 * w:-w]
            shift = abs(statistics.mean(x["score"] for x in recent) - statistics.mean(x["score"] for x in prior))
            if shift > TARGETS["score_drift_points"]:
                out.append(f"score drift: mean score moved {shift:.1f} points between windows")
        return out

    def summary(self) -> dict:
        r = self.records
        if not r:
            return {"investigations": 0}
        failed = [x for x in r if x["tool_failures"]]
        return {
            "investigations": len(r),
            "avg_latency_s": round(statistics.mean(x["latency_s"] for x in r), 3),
            "avg_tool_calls": round(statistics.mean(x["tool_calls"] for x in r), 1),
            "escalation_rate": round(sum(x["escalated"] for x in r) / len(r), 3),
            "fallback_success": (round(sum(x["escalated"] for x in failed) / len(failed), 3) if failed else None),
            "safety_events": sum(x["safety_events"] for x in r),
            "groundedness": round(statistics.mean(x["groundedness"] for x in r), 3),
            "policy_currency": round(statistics.mean(x["policy_currency"] for x in r), 3),
            "override_rate": (round(sum(not f["confirmed"] for f in self.feedback) / len(self.feedback), 3)
                              if self.feedback else None),
            "calibration": self.calibration()}


@dataclass
class EvalCase:
    change: ChangeEvent
    expect_high: bool          # expert label: should this reach High or Critical?
    expect_human: bool         # expert label: should a human be required?


def run_eval(orch, cases: list[EvalCase], repeats: int = 3) -> dict:
    """Offline regression run: recall/precision on High+, escalation accuracy, score consistency."""
    tp = fp = fn = esc_ok = 0
    spread = []
    for case in cases:
        runs = [orch.investigate(case.change) for _ in range(repeats)]
        a = runs[0]
        got_high = any(f.band in ("high", "critical") and f.verdict == "risk" for f in a.findings)
        tp += got_high and case.expect_high
        fp += got_high and not case.expect_high
        fn += (not got_high) and case.expect_high
        esc_ok += a.requires_human == case.expect_human
        spread.append(max(r.score for r in runs) - min(r.score for r in runs))
    return {"recall_high": tp / (tp + fn) if tp + fn else 1.0,
            "precision_high": tp / (tp + fp) if tp + fp else 1.0,
            "escalation_accuracy": esc_ok / len(cases),
            "max_score_spread": max(spread, default=0)}
