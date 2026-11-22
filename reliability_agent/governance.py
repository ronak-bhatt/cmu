"""Approval matrix and the recommend-only boundary."""
from __future__ import annotations


class ChangeExecutionForbidden(Exception):
    """The system never modifies infrastructure."""


def forbid_execution(*_a, **_k):
    raise ChangeExecutionForbidden("This system is recommend-only; changes go through normal change control.")


def decide(finding, env: str, unresolved_conflicts: bool, exception_requested: bool = False) -> dict:
    reasons, approvers = [], set()
    if finding.band == "critical":
        reasons.append("critical risk")
        approvers |= {"service_owner", "sre_oncall", "it_ops_manager"}
    elif finding.band == "high":
        reasons.append("high risk")
        approvers |= {"service_owner", "sre_oncall"}
    if env == "production":                      # every finding on a production change needs review
        reasons.append("production-affecting")
        approvers.add("service_owner")
    if finding.category == "compliance" and finding.verdict == "risk":
        reasons.append("security/compliance violation")
        approvers.add("security_owner")
    if exception_requested:
        reasons.append("request to accept or create an exception")
        approvers.add("policy_owner")
    if finding.confidence in ("Low", "Medium"):   # only High confidence earns the lighter tiers
        reasons.append("low confidence or missing evidence" if finding.confidence == "Low"
                       else "medium confidence: evidence not fully corroborated")
        approvers.add("sre_oncall")
    if unresolved_conflicts:
        reasons.append("unresolved conflicting sources")
        approvers.add("sre_oncall")
    if reasons:
        level = "mandatory"
    elif finding.band == "medium" and finding.confidence == "High":
        level, reasons = "acknowledge", ["medium risk, high confidence"]
    else:
        level = "report_only"
    return {"level": level, "reasons": reasons, "approvers": sorted(approvers)}


def review_gate(change_kind: str, reviewed_by: str | None, regression_passed: bool) -> None:
    """Edits to policies, scoring weights or guardrail limits need review + passing regression."""
    if not reviewed_by or not regression_passed:
        raise PermissionError(f"{change_kind} change requires human review and a passing regression suite")
