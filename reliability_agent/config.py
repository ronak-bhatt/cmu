"""Central, version-controlled settings. Changing weights, thresholds, or limits
is a governed change (see governance.review_gate) and must pass regression tests."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    branching_factor: int = 3     # ToT: children per node
    max_depth: int = 3            # ToT: reasoning steps from the root
    beam_width: int = 3           # ToT: nodes kept per level
    max_nodes: int = 13           # ToT: hard cap on candidate nodes (incl. root)
    max_extra_cycles: int = 2     # evaluator may request more evidence this often
    max_tool_calls: int = 40      # per investigation
    top_k: int = 8                # retrieved chunks per query
    prune_below: float = 0.15     # hypotheses scoring below this are pruned
    margin_required: float = 0.25 # lead over the opposing verdict for "sufficient evidence"


LIMITS = Limits()
SCORING_VERSION = "1.1.0"      # 1.1.0: drift findings, scoring constants moved into ScoringRules


@dataclass(frozen=True)
class ScoringRules:
    """Every number that feeds severity x likelihood x impact lives here (governed, versioned)."""
    default_severity: int = 3            # when the governing policy sets none
    likelihood_base: int = 3             # a confirmed risk starts here
    likelihood_incident_bonus: int = 1   # historical incident precedent (advisory, adjusts likelihood only)
    likelihood_load_bonus: int = 1       # monitoring shows little headroom
    likelihood_max: int = 5
    mitigated_likelihood: int = 1        # verified failover or valid exception
    mitigated_impact_cap: int = 2
    impact_nonprod: int = 1
    impact_prod: int = 3                 # one production service
    impact_prod_wide_bonus: int = 1      # tier 1 or many dependents
    wide_dependents: int = 3
    load_cpu_p95: float = 0.75
    unverified: tuple = (3, 3, 2)        # severity, likelihood, impact when no governing policy is found
    drift: tuple = (2, 3)                # severity, likelihood of a drift finding (impact = blast radius)


SCORING = ScoringRules()

# Initial targets from the safety plan; tuned through reviewed changes only.
TARGETS = {"recall_high": 0.95, "groundedness": 0.98, "policy_currency": 1.0, "calibration_high": 0.95,
           "score_spread": 3, "safety_violations": 0, "fallback_success": 0.95, "latency_s": 600,
           "call_volume_ratio": 0.8, "score_drift_points": 10, "drift_window": 10}

CATEGORY_WEIGHTS = {"availability": 30, "resilience": 25, "recoverability": 20,
                    "compliance": 15, "observability": 10}
BAND_DEDUCTION = {"critical": 25, "high": 15, "medium": 7, "low": 2}
BAND_THRESHOLDS = ((80, "critical"), (40, "high"), (15, "medium"), (0, "low"))
BAND_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
CONFIDENCE_RANK = {"High": 3, "Medium": 2, "Low": 1}

ALLOWED_KINDS = {"kubernetes", "terraform"}
ALLOWED_ENVS = {"production", "staging", "development"}
READ_ONLY_TOOLS = frozenset({"get_live_config", "get_topology", "get_failover",
                             "get_metrics", "get_incidents"})
EMBED_DIM = 256  # must match vector(N) in schema.sql when using a different embedder
