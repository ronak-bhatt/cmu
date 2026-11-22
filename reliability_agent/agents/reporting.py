"""Assessment and Reporting Agent: ranks findings, scores, recommends, applies the approval matrix."""
from __future__ import annotations
from dataclasses import asdict
from ..config import CONFIDENCE_RANK, SCORING_VERSION
from ..governance import decide
from ..guardrails import looks_like_injection
from ..llm import NullLLM, template_summary
from ..models import Assessment
from ..scoring import reliability_score
from ..state import InvestigationState

CHECKS = {"availability": "verify node and zone failure tolerance",
          "resilience": "load-test the new limits before rollout",
          "recoverability": "run a restore test after the change",
          "compliance": "route to the security owner before any rollout",
          "observability": "confirm alerts still fire for this service"}


class ReportingAgent:
    name = "reporting"

    def __init__(self, llm=None):
        self.llm = llm or NullLLM()

    @staticmethod
    def _recommend(f, ctx: dict) -> str:
        if f.verdict == "unverified":
            return "No governing policy was found; an engineer should confirm the requirement before approval."
        if f.verdict == "drift":
            return (f"Live {ctx['metric']} is {ctx['live']} but the change assumes {ctx['baseline']}. "
                    f"Reconcile the baseline with live state and re-submit the change for assessment.")
        rule = ctx["rule"]
        if f.verdict == "acceptable":
            via = f"exception {ctx['exception']}" if ctx["exception"] else "the verified failover"
            return f"No change needed. Covered by {via}; keep it under periodic review."
        return (f"Restore {ctx['metric']} to satisfy {ctx['rule_doc']} (required {rule['op']} {rule['value']}); "
                f"{CHECKS.get(f.category, 'verify before approval')}.")

    def report(self, state: InvestigationState, result) -> Assessment:
        env = state.change.environment
        unresolved = any(not c.resolved for c in result.conflicts)
        findings = result.findings
        for f in findings:
            f.recommendation = self._recommend(f, result.context.get(f.id, {}))
            f.approval = decide(f, env, unresolved, state.change.exception_requested)
            state.log(self.name, "approval_decision", finding=f.id, **f.approval)
        findings.sort(key=lambda f: (-f.priority, -CONFIDENCE_RANK[f.confidence], f.id))
        score, cats = reliability_score(findings)

        reasons = sorted({f"{f.id}: {r}" for f in findings if f.approval["level"] == "mandatory"
                          for r in f.approval["reasons"]})
        reasons += [f"safety event: {m}" for m in state.safety_events]
        if state.tool_failures:                       # fallback: a gap in evidence goes to a human, never a guess
            reasons.append(f"tool failure ({', '.join(sorted(set(state.tool_failures)))}): "
                           f"evidence incomplete, human review required")
        if state.change.exception_requested:
            reasons.append("exception requested: policy owner approval required")
        facts = {"score": score, "target": state.change.target, "findings": len(findings),
                 "high_or_critical": sum(f.band in ("high", "critical") for f in findings),
                 "needs_review": sum(f.approval["level"] == "mandatory" for f in findings)}
        try:
            text = self.llm.narrate(facts)
            if str(score) not in text or looks_like_injection(text):   # output constraint
                raise ValueError("narration does not match computed facts")
        except Exception:
            text = template_summary(facts)

        state.log(self.name, "score", score=score, scoring_version=SCORING_VERSION,
                  findings=[f.id for f in findings], requires_human=bool(reasons))
        sources = [{"ref": d.doc_id, "source": d.kind, "status": d.status, "version": d.version,
                    "effective": d.effective} for d in state.docs.values()]
        excluded = [{"ref": d.doc_id, "reason": why} for d, why in state.excluded]
        return Assessment(state.id, state.change.id, state.change.target, score, cats, findings,
                          [asdict(c) for c in result.conflicts], result.hypotheses, sources, excluded,
                          list(state.safety_events), bool(reasons), reasons, text, SCORING_VERSION)
