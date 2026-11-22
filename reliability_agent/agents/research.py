"""Infrastructure Research Agent: gathers live configuration, topology, failover, metrics, incidents."""
from __future__ import annotations
from ..delta import diff
from ..guardrails import (ToolFailure, ToolNotAllowed, BudgetExceeded, redact, looks_like_injection)
from ..models import AgentMessage, Task
from ..state import InvestigationState


class ResearchAgent:
    name = "research"

    def run(self, task: Task, state: InvestigationState, gate) -> None:
        handler = getattr(self, f"_{task.action}")
        try:
            handler(state, gate)
            status = "done"
        except (ToolFailure, ToolNotAllowed, BudgetExceeded) as exc:
            status = "failed"
            state.log(self.name, "task_failed", task=task.id, error=str(exc))
        state.send(AgentMessage(state.id, self.name, "evaluation", task.action, status))

    def _collect_configs(self, state, gate):
        t = state.change.target
        live = gate.call("get_live_config", target=t)
        state.add_evidence("live", f"config:{t}", "live configuration", {"config": redact(live)})

    def _compute_deltas(self, state, gate):
        state.deltas = diff(state.change.before, state.change.after)
        for d in state.deltas:
            if d.secret:
                state.safety(f"possible secret exposure in {d.path}; values withheld from the report")
        state.log(self.name, "deltas", paths=[d.path for d in state.deltas])

    def _topology(self, state, gate):
        t = state.change.target
        state.add_evidence("live", f"topology:{t}", "dependencies and tier", redact(gate.call("get_topology", target=t)))

    def _failover(self, state, gate):
        t = state.change.target
        state.add_evidence("live", f"failover:{t}", "failover mechanism", redact(gate.call("get_failover", target=t)))

    def _metrics(self, state, gate):
        t = state.change.target
        state.add_evidence("monitoring", f"metrics:{t}", "availability and load", redact(gate.call("get_metrics", target=t)))

    def _incidents(self, state, gate):
        for inc in gate.call("get_incidents", target=state.change.target):
            if looks_like_injection(inc.get("summary", "")):
                state.safety(f"possible prompt injection in incident {inc.get('id')}; quarantined")
                continue
            state.add_evidence("incident", inc["id"], inc.get("summary", "")[:140],
                               {"tags": inc.get("tags", []), "service": state.change.target})
