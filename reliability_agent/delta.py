"""Configuration diffing and category mapping (the Compare step)."""
from __future__ import annotations
from typing import Any, Optional
from .models import Delta

# Order matters: first match wins.
CATEGORY_KEYWORDS = [
    ("resilience", ("autoscal", "max_replicas", "limits", "requests", "pod_disruption")),
    ("availability", ("replicas", "zones", "multi_az", "min_instances")),
    ("recoverability", ("backup", "retention", "snapshot", "pitr")),
    ("compliance", ("encrypt", "public", "tls", "cidr", "ingress")),
    ("observability", ("monitoring", "alert", "logging")),
]


def categorize(path: str) -> Optional[str]:
    low = path.lower()
    for category, keys in CATEGORY_KEYWORDS:
        if any(k in low for k in keys):
            return category
    return None  # not reliability-relevant (e.g. image tag): ignored


def flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in (d or {}).items():
        p = f"{prefix}.{k}" if prefix else str(k)
        out.update(flatten(v, p) if isinstance(v, dict) else {p: v})
    return out


def get_path(d: dict, path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def diff(before: dict, after: dict) -> list[Delta]:
    b, a = flatten(before), flatten(after)
    deltas = []
    for path in sorted(set(b) | set(a)):
        if b.get(path) != a.get(path):
            cat = categorize(path)
            if cat:
                deltas.append(Delta(path, b.get(path), a.get(path), cat))
    return deltas
