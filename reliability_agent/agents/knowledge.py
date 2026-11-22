"""Knowledge Retrieval Agent: RAG over policies, exceptions, incidents and architecture notes."""
from __future__ import annotations
from ..config import LIMITS
from ..guardrails import usable, looks_like_injection
from ..models import AgentMessage, Task
from ..state import InvestigationState


class KnowledgeAgent:
    name = "knowledge"

    def __init__(self, store):
        self.store = store

    def run(self, task: Task, state: InvestigationState, gate=None) -> None:
        docs = self.store.search(task.params["query"], LIMITS.top_k, {"kind": task.params["kinds"]})
        refs = []
        for d in docs:
            if d.doc_id in state.docs or any(x.id == d.id for x, _ in state.excluded):
                continue
            ok, why = usable(d, state.today)
            if not ok:                                   # deprecated, draft, not yet effective, expired
                state.excluded.append((d, why))
                continue
            if looks_like_injection(d.text):             # retrieved text is data, never instructions
                state.safety(f"possible prompt injection in document {d.doc_id}; quarantined")
                state.excluded.append((d, "quarantined"))
                continue
            state.docs[d.doc_id] = d
            data = {**d.metadata, "version": d.version, "effective": d.effective}
            state.add_evidence(d.kind, d.doc_id, d.text[:140], data)
            refs.append(d.doc_id)
        state.log(self.name, "retrieval", task=task.id, query=task.params["query"], used=refs,
                  excluded=[x.doc_id for x, _ in state.excluded])
        state.send(AgentMessage(state.id, self.name, "evaluation", task.id, "done", evidence_refs=refs))
