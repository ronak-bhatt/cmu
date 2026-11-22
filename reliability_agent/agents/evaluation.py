"""Reliability Evaluation Agent: resolves conflicts, runs Tree-of-Thought per delta, builds findings."""
from __future__ import annotations
import operator
from dataclasses import dataclass, field, asdict
from ..config import LIMITS, SCORING
from ..delta import get_path
from ..models import Conflict, EvidenceRequest, Finding
from ..scoring import band_for, priority
from ..state import InvestigationState
from ..tot import Ctx, VERDICT, beam_search

OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq, "!=": operator.ne,
       ">": operator.gt, "<": operator.lt}

# Exception conditions that can be checked against live failover data. Any other condition key
# is treated as unmet: an exception is honoured only when every stated condition is verified.
CONDITION_CHECKS = {
    "failover_type": lambda fd, v: fd.get("type") == v,
    "max_rto_minutes": lambda fd, v: fd.get("rto_minutes", 10**9) <= v,
}


@dataclass
class EvaluationResult:
    findings: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    hypotheses: list = field(default_factory=list)
    requests: list = field(default_factory=list)
    context: dict = field(default_factory=dict)      # finding id -> facts for recommendations


def _holds(after, op, value) -> bool:
    try:
        return after is not None and OPS[op](after, value)
    except TypeError:
        return False


class EvaluationAgent:
    name = "evaluation"

    def evaluate(self, state: InvestigationState, final: bool = False) -> EvaluationResult:
        res = EvaluationResult()
        ch = state.change
        live = state.find("live", "config:")
        topo = next(iter(state.find("live", "topology:")), None)
        fo = next(iter(state.find("live", "failover:")), None)
        met = next(iter(state.find("monitoring", "metrics:")), None)
        tier = (topo.data.get("tier") if topo else None) or ch.tier
        dependents = topo.data.get("dependents", 0) if topo else 0
        wide = tier == 1 or dependents >= SCORING.wide_dependents
        base_impact = (SCORING.impact_prod + (SCORING.impact_prod_wide_bonus if wide else 0)
                       if ch.environment == "production" else SCORING.impact_nonprod)
        missing = [n for n, ev in (("live configuration", live), ("topology", topo),
                                   ("failover data", fo), ("monitoring data", met)) if not ev]

        def ask(req: EvidenceRequest) -> bool:           # request once; never loop on the same gap
            if req.key in state.requested or final:
                return False
            res.requests.append(req)
            return True

        if not live:
            ask(EvidenceRequest("research", "collect_configs", {}, "live configuration missing"))
        if not topo:
            ask(EvidenceRequest("research", "topology", {}, "topology missing"))
        if not fo:
            ask(EvidenceRequest("research", "failover", {}, "failover data missing"))
        if not met:
            ask(EvidenceRequest("research", "metrics", {}, "monitoring data missing"))

        for delta in state.deltas:
            self._check_drift(state, live, delta, res, base_impact)
            rules = [(d, d.metadata["rule"]) for d in state.docs.values()
                     if d.kind == "policy" and d.metadata.get("rule", {}).get("metric") == delta.metric]
            cands = [(d, r) for d, r in rules if self._applies(r, ch, tier)]
            if not rules:                                 # no governing policy found at all
                if ask(EvidenceRequest("knowledge", "retrieve",
                                       {"query": f"{delta.metric} requirement policy", "kinds": ["policy"]},
                                       f"no policy found for {delta.metric}")):
                    continue
                res.findings.append(self._unverified(state, delta, res))
                continue
            if not cands:                                 # policies exist but do not govern this scope
                state.log(self.name, "out_of_policy_scope", path=delta.path)
                continue

            doc, rule = self._resolve(cands, res.conflicts)
            violation = not _holds(delta.after, rule["op"], rule["value"])
            incident_ids = [e.ref for e in state.find("incident")
                            if {delta.metric, delta.category} & set(e.data.get("tags", []))
                            and e.data.get("service", ch.target) == ch.target]
            if not violation:
                if incident_ids:
                    res.conflicts.append(Conflict("historical",
                        f"incident precedent {incident_ids} exists but {delta.path} satisfies {doc.doc_id}",
                        doc.doc_id, "policy sets severity; incidents adjust likelihood only",
                        loser="incident precedent"))
                continue

            mit = rule.get("mitigation")
            fdata = fo.data if fo else {}
            present = bool(fdata.get("present"))
            mitigated = bool(mit and present and fdata.get("verified")
                             and fdata.get("type") in mit.get("failover_type", [])
                             and fdata.get("rto_minutes", 10**9) <= mit.get("max_rto_minutes", 0))
            exc_id, exc_state = self._exception(state, delta, fdata, present, doc, res)
            mdata = met.data if met else {}
            load_high = (mdata.get("cpu_p95", 0) >= SCORING.load_cpu_p95
                         or mdata.get("availability_30d", 100) < mdata.get("slo", 0))
            refs = {"failover": fo.ref if fo else None, "metrics": met.ref if met else None,
                    "topology": topo.ref if topo else None}
            ctx = Ctx(delta, ch.environment, tier, dependents, rule, doc.doc_id, True, bool(mit),
                      present, mitigated, exc_id, exc_state, incident_ids, load_high, refs)
            tree = beam_search(ctx, state.next_id)
            res.hypotheses += [{**asdict(n), "delta": delta.path} for n in tree.nodes]
            if not tree.sufficient:
                ask(EvidenceRequest("research", "failover", {}, "hypotheses indistinguishable; refresh evidence"))
            res.findings.append(self._finding(state, ctx, tree, res, base_impact, live, topo, fo, met, missing))
        return res

    # -- conflict handling -------------------------------------------------------------------
    @staticmethod
    def _applies(rule: dict, ch, tier: int) -> bool:
        return (ch.environment in rule.get("env", [ch.environment]) and tier in rule.get("tier", [tier])
                and rule.get("service", ch.target) == ch.target)

    @staticmethod
    def _specificity(rule: dict) -> int:
        return sum(k in rule for k in ("service", "tier"))

    def _resolve(self, cands, conflicts):
        ordered = sorted(cands, key=lambda x: (self._specificity(x[1]), x[0].effective), reverse=True)
        top = ordered[0]
        rivals = [c for c in ordered[1:] if (c[1]["op"], c[1]["value"]) != (top[1]["op"], top[1]["value"])]
        if not rivals:
            return top
        rival = rivals[0]
        tie = (self._specificity(rival[1]) == self._specificity(top[1]) and rival[0].effective == top[0].effective)
        if tie:   # no precedence rule decides: take the stricter value provisionally, flag for humans
            strict = max((top, rival), key=lambda x: x[1]["value"] if x[1]["op"] == ">=" else -x[1]["value"])
            other = rival if strict is top else top
            conflicts.append(Conflict("normative", f"{top[0].doc_id} and {rival[0].doc_id} disagree",
                                      strict[0].doc_id, "no precedence rule applies", resolved=False,
                                      loser=other[0].doc_id))
            return strict
        conflicts.append(Conflict("normative", f"{top[0].doc_id} vs {rival[0].doc_id}", top[0].doc_id,
                                  "more specific scope wins, then newer effective date", loser=rival[0].doc_id))
        return top

    @staticmethod
    def _check_drift(state, live, delta, res, base_impact) -> None:
        """Factual conflict: live state wins, and the drift itself is reported as a finding."""
        if not live:
            return
        actual = get_path(live[0].data.get("config", {}), delta.path)
        if actual is None or actual == "[REDACTED]" or actual == delta.before:
            return
        shown_live = "[REDACTED]" if delta.secret else actual
        shown_before = "[REDACTED]" if delta.secret else delta.before
        res.conflicts.append(Conflict("factual",
            f"live {delta.path}={shown_live} but the change assumes {shown_before}",
            "live state", "live data is authoritative for current state", loser="change baseline"))
        sev, like = SCORING.drift
        p = priority(sev, like, base_impact)
        f = Finding(state.next_id("F"), f"Configuration drift on {delta.path}: live state differs from the change baseline",
                    delta.category, delta.path, "drift", sev, like, base_impact, "High", p, band_for(p),
                    "live state is authoritative; the baseline this change was written against is stale",
                    [live[0].ref], [live[0].id])
        res.findings.append(f)
        res.context[f.id] = {"metric": delta.metric, "live": shown_live, "baseline": shown_before}

    @staticmethod
    def _conditions_met(cond: dict, fdata: dict, present: bool) -> bool:
        """Every stated condition must be verified against live data; unknown conditions fail closed."""
        if not cond:
            return True
        if not (present and fdata.get("verified")):
            return False
        return all(k in CONDITION_CHECKS and CONDITION_CHECKS[k](fdata, v) for k, v in cond.items())

    def _exception(self, state, delta, fdata, present, doc, res):
        def scope(d):
            return d.metadata.get("service") == state.change.target and d.metadata.get("metric") == delta.metric
        active = [d for d in state.docs.values() if d.kind == "exception" and scope(d)
                  and d.metadata.get("status") == "approved"]
        if active:
            d = active[0]
            ok = self._conditions_met(d.metadata.get("condition", {}), fdata, present)
            st = "valid" if ok else "unmet"
            res.conflicts.append(Conflict("contextual", f"{doc.doc_id} violated but exception {d.doc_id} exists ({st})",
                                          d.doc_id if ok else doc.doc_id,
                                          "an exception holds only while active and its conditions are verified live",
                                          loser=doc.doc_id if ok else d.doc_id))
            return d.doc_id, st
        if any(d.kind == "exception" and scope(d) and why == "expired" for d, why in state.excluded):
            return None, "expired"
        return None, None

    # -- findings ------------------------------------------------------------------------------
    def _unverified(self, state, delta, res) -> Finding:
        sev, like, imp = SCORING.unverified
        p = priority(sev, like, imp)
        f = Finding(state.next_id("F"), f"No governing policy found for {delta.path}", delta.category, delta.path,
                    "unverified", sev, like, imp, "Low", p, band_for(p),
                    "insufficient evidence to judge this change", [], [],)
        res.context[f.id] = {"metric": delta.metric}
        return f

    def _finding(self, state, ctx, tree, res, base_impact, live, topo, fo, met, missing) -> Finding:
        best, refs = tree.best, tree.refinements
        verdict = VERDICT[best.kind]
        sev = ctx.rule.get("severity", SCORING.default_severity)
        if verdict == "risk":
            like = min(SCORING.likelihood_max, SCORING.likelihood_base
                       + SCORING.likelihood_incident_bonus * ("incident" in refs)
                       + SCORING.likelihood_load_bonus * ("load" in refs))
            impact = SCORING.impact_nonprod if "contained" in refs else base_impact
        else:
            like, impact = SCORING.mitigated_likelihood, min(base_impact, SCORING.mitigated_impact_cap)
        p = priority(sev, like, impact)
        exc = ctx.exception_id if ctx.exception_state == "valid" else None   # an unmet exception supports nothing
        citations = [ctx.rule_doc] + ([exc] if exc else []) + (ctx.incident_ids if "incident" in refs else [])
        used = [e for e in (*live, topo, fo, met) if e] + [e for e in state.evidence.values() if e.ref in citations]
        unresolved = any(not c.resolved for c in res.conflicts)
        points = sum([bool(live), True, not unresolved, tree.sufficient, bool(met)]) - len(state.tool_failures)
        conf = "High" if points >= 4 else "Medium" if points == 3 else "Low"
        if unresolved or missing:                         # sources disagree, or evidence is missing: never confident
            conf = "Low"
        f = Finding(state.next_id("F"),
                    f"{ctx.delta.display} ({'violates' if verdict == 'risk' else 'covered under'} {ctx.rule_doc})",
                    ctx.delta.category, ctx.delta.path, verdict, sev, like, impact, conf, p, band_for(p),
                    best.statement, citations, sorted({e.id for e in used}))
        res.context[f.id] = {"metric": ctx.delta.metric, "rule": ctx.rule, "rule_doc": ctx.rule_doc,
                             "exception": exc, "mitigated": ctx.mitigated}
        return f
