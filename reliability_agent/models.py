from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class ChangeEvent:
    id: str
    kind: str                      # kubernetes | terraform
    target: str                    # service / resource name
    environment: str
    before: dict
    after: dict
    tier: int = 3                  # 1 = business critical
    description: str = ""
    requested_by: str = "unknown"
    exception_requested: bool = False   # a request to accept or create an exception


@dataclass
class Delta:
    path: str
    before: Any
    after: Any
    category: str

    @property
    def metric(self) -> str:
        return self.path.split(".")[-1]

    @property
    def secret(self) -> bool:
        from .guardrails import is_secret          # lazy: guardrails imports models
        return is_secret(self.path, self.before, self.after)

    @property
    def display(self) -> str:
        """Report-safe rendering: secret values never reach findings, trails or logs."""
        return f"{self.path}: [REDACTED]" if self.secret else f"{self.path}: {self.before} -> {self.after}"


@dataclass
class Doc:
    """A retrievable knowledge chunk: policy, exception, incident or architecture note."""
    id: str
    text: str
    kind: str                      # policy | exception | incident | architecture
    source: str = "wiki"
    version: str = "1"
    status: str = "active"         # active | deprecated | draft
    effective: str = "1970-01-01"
    expires: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    @property
    def doc_id(self) -> str:
        return self.metadata.get("doc_id", self.id)


@dataclass
class Evidence:
    id: str
    source: str                    # live | monitoring | policy | exception | incident | architecture
    ref: str
    summary: str
    data: dict = field(default_factory=dict)


@dataclass
class Hypothesis:
    id: str
    parent: Optional[str]
    kind: str
    statement: str
    depth: int
    score: float
    status: str = "open"           # open | pruned
    evidence: list = field(default_factory=list)   # refs that support this node


@dataclass
class Conflict:
    kind: str                      # factual | normative | contextual | historical
    detail: str
    winner: str
    rule: str
    resolved: bool = True
    loser: str = ""            # the source that lost, so every resolution is auditable


@dataclass
class Finding:
    id: str
    title: str
    category: str
    delta_path: str
    verdict: str                   # risk | acceptable | unverified | drift
    severity: int
    likelihood: int
    impact: int
    confidence: str
    priority: int
    band: str
    hypothesis: str
    citations: list = field(default_factory=list)
    evidence_ids: list = field(default_factory=list)
    recommendation: str = ""
    approval: dict = field(default_factory=dict)


@dataclass
class Task:
    id: str
    agent: str                     # research | knowledge
    action: str
    params: dict = field(default_factory=dict)
    reason: str = ""


@dataclass
class EvidenceRequest:
    agent: str
    action: str
    params: dict
    reason: str

    @property
    def key(self) -> str:
        return f"{self.agent}:{self.action}:{sorted(self.params.items())}"


@dataclass
class AgentMessage:
    investigation_id: str
    sender: str
    recipient: str
    task: str
    status: str
    confidence: str = "n/a"
    evidence_refs: list = field(default_factory=list)


@dataclass
class Assessment:
    investigation_id: str
    change_id: str
    target: str
    score: int
    category_scores: dict
    findings: list
    conflicts: list
    hypotheses: list
    sources: list
    excluded_sources: list
    safety_events: list
    requires_human: bool
    escalation_reasons: list
    summary: str
    scoring_version: str
    autonomy: str = "recommend_only"

    def to_dict(self) -> dict:
        return asdict(self)
