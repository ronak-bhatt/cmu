"""Planner Agent: understands the change and writes the investigation plan (Plan-and-Execute)."""
from __future__ import annotations
from ..delta import diff
from ..models import ChangeEvent, EvidenceRequest, Task


class PlannerAgent:
    name = "planner"

    def plan(self, change: ChangeEvent) -> list[Task]:
        deltas = diff(change.before, change.after)
        if not deltas:
            return []
        cats = sorted({d.category for d in deltas})
        metrics = " ".join(sorted({d.metric for d in deltas}))
        tasks = [Task("R1", "research", "collect_configs", {}, "current live state"),
                 Task("R2", "research", "compute_deltas", {}, "before/after differences"),
                 Task("R3", "research", "topology", {}, "dependencies and tier"),
                 Task("R4", "research", "failover", {}, "alternative redundancy"),
                 Task("R5", "research", "metrics", {}, "availability and load"),
                 Task("R6", "research", "incidents", {}, "incident history")]
        for cat in cats:
            tasks.append(Task(f"K-{cat}", "knowledge", "retrieve",
                              {"query": f"{cat} requirements {metrics} {change.environment}", "kinds": ["policy"]},
                              f"policies for {cat}"))
        tasks.append(Task("K-exc", "knowledge", "retrieve",
                          {"query": f"approved exception {change.target} {metrics}", "kinds": ["exception"]},
                          "approved exceptions"))
        tasks.append(Task("K-inc", "knowledge", "retrieve",
                          {"query": f"incident root cause {change.target} {metrics}", "kinds": ["incident", "architecture"]},
                          "past incidents and architecture"))
        return tasks

    def replan(self, requests: list[EvidenceRequest]) -> list[Task]:
        """Adapt the plan when the evaluator reports gaps."""
        return [Task(f"X{i}", r.agent, r.action, r.params, r.reason) for i, r in enumerate(requests, 1)]
