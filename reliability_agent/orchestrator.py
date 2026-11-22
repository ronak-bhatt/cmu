"""Hybrid coordination: Planner -> (Research || Knowledge) -> Evaluation <-> evidence loop -> Reporting."""
from __future__ import annotations
import dataclasses, json, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional
from .agents import PlannerAgent, ResearchAgent, KnowledgeAgent, EvaluationAgent, ReportingAgent
from .agents.evaluation import EvaluationResult
from .config import LIMITS
from .governance import forbid_execution
from .guardrails import ToolGate, validate_change, looks_like_injection
from .metrics import MetricsCollector
from .models import Assessment, ChangeEvent, AgentMessage
from .state import InvestigationState
from .storage import InMemoryRepository
from .delta import diff


class Orchestrator:
    def __init__(self, tools: dict, store, today: Optional[str] = None, llm=None,
                 audit_path: Optional[str] = None, metrics: Optional[MetricsCollector] = None, repo=None):
        self.tools, self.today = tools, today or date.today().isoformat()
        self.audit_path = audit_path
        self.metrics = metrics or MetricsCollector()
        self.repo = repo if repo is not None else InMemoryRepository()
        self.planner, self.research = PlannerAgent(), ResearchAgent()
        self.knowledge, self.evaluator = KnowledgeAgent(store), EvaluationAgent()
        self.reporter = ReportingAgent(llm)

    apply_change = staticmethod(forbid_execution)      # tripwire: the system never executes changes

    def investigate(self, change: ChangeEvent) -> Assessment:
        t0 = time.monotonic()
        validate_change(change)                                          # input check
        state = InvestigationState(change, self.today)
        if looks_like_injection(change.description):
            state.safety("possible prompt injection in change description; description ignored")
            change = dataclasses.replace(change, description="")
            state.change = change
        gate = ToolGate(self.tools, state)

        plan = self.planner.plan(change)
        state.log("planner", "plan", tasks=[t.id for t in plan])
        self._execute(plan, state, gate)                                  # research and knowledge in parallel

        result = EvaluationResult()
        for cycle in range(LIMITS.max_extra_cycles + 1):
            final = cycle == LIMITS.max_extra_cycles
            result = self.evaluator.evaluate(state, final)
            new = [r for r in result.requests if r.key not in state.requested]
            if not new or final:
                break
            state.requested |= {r.key for r in new}
            state.log("evaluation", "requested_evidence", reasons=[r.reason for r in new])
            self._execute(self.planner.replan(new), state, gate)

        assessment = self.reporter.report(state, result)
        state.send(AgentMessage(state.id, "reporting", "human", "assessment",
                                "needs_review" if assessment.requires_human else "complete"))
        self.metrics.record(assessment, state, time.monotonic() - t0)
        self.repo.save(assessment, state)                                # findings, approvals, trail, audit
        if self.audit_path:
            with open(self.audit_path, "a") as fh:
                fh.write(json.dumps({"investigation": state.id, "audit": state.audit,
                                     "messages": [dataclasses.asdict(m) for m in state.messages]}) + "\n")
        return assessment

    def _execute(self, tasks, state, gate) -> None:
        groups = {"research": (self.research, []), "knowledge": (self.knowledge, [])}
        for t in tasks:
            groups[t.agent][1].append(t)

        def run(agent, items):
            for t in items:
                agent.run(t, state, gate)

        with ThreadPoolExecutor(max_workers=2) as pool:
            for fut in [pool.submit(run, a, ts) for a, ts in groups.values()]:
                fut.result()

    def record_feedback(self, investigation_id: str, finding_id: str, confirmed: bool, confidence: str) -> None:
        """Engineer feedback is stored for review (metrics and database); it never edits rules or weights."""
        self.metrics.record_feedback(investigation_id, finding_id, confirmed, confidence)
        self.repo.add_feedback(investigation_id, finding_id, confirmed, confidence)

    def verify(self, prior: Assessment, applied: ChangeEvent) -> dict:
        """After an approved change is applied by engineers, re-assess and report whether risks resolved.
        A risk counts as resolved only if the re-assessment actually re-examined that setting."""
        new = self.investigate(applied)
        old = {f.delta_path for f in prior.findings if f.verdict == "risk"}
        rechecked = {d.path for d in diff(applied.before, applied.after)}
        left = sorted(f.delta_path for f in new.findings if f.verdict == "risk" and f.delta_path in old)
        return {"resolved": sorted((old & rechecked) - set(left)), "remaining": left,
                "not_rechecked": sorted(old - rechecked),
                "score_before": prior.score, "score_after": new.score}
