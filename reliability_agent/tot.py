"""Bounded Tree-of-Thought: beam search over risk hypotheses for one configuration delta."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional
from .config import LIMITS, Limits
from .models import Delta, Hypothesis

VERDICT = {"risk": "risk", "mitigated": "acceptable", "exception": "acceptable"}


@dataclass
class Ctx:
    """Facts gathered for one delta; every hypothesis is scored against these."""
    delta: Delta
    env: str
    tier: int
    dependents: int
    rule: dict
    rule_doc: str
    violation: bool
    mitigation_allowed: bool
    failover_present: bool
    mitigated: bool                   # failover verified and meets the policy's mitigation terms
    exception_id: Optional[str]
    exception_state: Optional[str]    # valid | expired | unmet | None
    incident_ids: list
    load_high: bool
    refs: dict = field(default_factory=dict)   # evidence refs: failover, metrics, topology

    @property
    def prod(self) -> bool:
        return self.env == "production"


@dataclass
class TreeResult:
    nodes: list
    best: Optional[Hypothesis]
    margin: float
    refinements: set
    sufficient: bool


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _root_score(kind: str, c: Ctx) -> float:
    if kind == "risk":
        s = 0.2 + (0.5 if c.violation else 0.0)
        s += 0.15 if not (c.failover_present and c.mitigation_allowed) else 0.0
        s += 0.15 if c.exception_state != "valid" else 0.0
        s -= 0.5 if c.mitigated else 0.0
        s -= 0.5 if c.exception_state == "valid" else 0.0
        return _clamp(s)
    if kind == "mitigated":
        if not (c.mitigation_allowed and c.failover_present):
            return 0.0
        return 0.85 if c.mitigated else 0.3
    return {"valid": 0.9, "expired": 0.2, "unmet": 0.25}.get(c.exception_state, 0.0)


def _support(kind: str, c: Ctx) -> list:
    """Evidence refs that back a node, so every branch of the tree can be audited."""
    r = c.refs
    table = {"risk": [c.rule_doc], "risk/incident": list(c.incident_ids), "risk/load": [r.get("metrics")],
             "risk/contained": [r.get("topology")],
             "mitigated": [c.rule_doc, r.get("failover")], "mitigated/verified": [r.get("failover")],
             "mitigated/unverified": [r.get("failover")],
             "exception": [c.exception_id], "exception/valid": [c.exception_id],
             "exception/invalid": [c.exception_id]}
    return [x for x in table.get(kind, []) if x]


def _expand(parent: Hypothesis, c: Ctx):
    p = c.delta.path
    if parent.depth == 0:
        yield "risk", f"{p}: change creates a risk with no adequate mitigation", None
        yield "mitigated", f"{p}: an alternative mechanism provides equivalent protection", None
        yield "exception", f"{p}: an approved exception permits this configuration", None
    elif parent.kind == "risk":
        yield "risk/incident", "historical incidents show precedent for this failure", 0.9 if c.incident_ids else 0.1
        yield "risk/load", "current load leaves little headroom", 0.9 if c.load_high else 0.1
        yield "risk/contained", "blast radius is limited (non-production)", 0.9 if not c.prod else 0.1
    elif parent.kind == "mitigated":
        yield "mitigated/verified", "failover verified against recovery objectives", 0.9 if c.mitigated else 0.2
        yield "mitigated/unverified", "failover present but unverified", 0.9 if (c.failover_present and not c.mitigated) else 0.0
    elif parent.kind == "exception":
        yield "exception/valid", "exception is active and its conditions are met", 0.9 if c.exception_state == "valid" else 0.0
        yield "exception/invalid", "exception expired or its conditions are unmet", 0.9 if c.exception_state in ("expired", "unmet") else 0.0


def beam_search(c: Ctx, new_id: Callable[[str], str], limits: Limits = LIMITS) -> TreeResult:
    root = Hypothesis(new_id("H"), None, "root", c.delta.display, 0, 1.0)
    nodes, frontier = [root], [root]
    for depth in range(1, limits.max_depth + 1):
        cands = []
        for parent in frontier:
            for kind, text, factor in list(_expand(parent, c))[: limits.branching_factor]:
                if len(nodes) + len(cands) >= limits.max_nodes:
                    break
                score = _root_score(kind, c) if depth == 1 else parent.score * factor
                cands.append(Hypothesis(new_id("H"), parent.id, kind, text, depth, round(score, 3),
                                        evidence=_support(kind, c)))
        if not cands:
            break
        cands.sort(key=lambda h: -h.score)
        keep = [h for h in cands if h.score >= limits.prune_below][: limits.beam_width]
        for h in cands:
            h.status = "open" if h in keep else "pruned"
        nodes += cands
        frontier = keep
        if not keep:
            break
    top = [n for n in nodes if n.depth == 1]
    live = [n for n in top if n.status == "open"]
    best = max(live, key=lambda n: n.score) if live else None
    other = max((n.score for n in top if best and VERDICT[n.kind] != VERDICT[best.kind]), default=0.0)
    margin = round(best.score - other, 3) if best else 0.0
    refinements = {n.kind.split("/")[1] for n in nodes
                   if best and n.parent == best.id and n.status == "open" and "/" in n.kind}
    return TreeResult(nodes, best, margin, refinements,
                      best is not None and margin >= limits.margin_required)
