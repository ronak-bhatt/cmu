"""python run_demo.py  -> runs the sample scenarios and prints each assessment."""
import json
from reliability_agent.demo_data import SCENARIOS, demo_orchestrator

orch = demo_orchestrator()
for name, change in SCENARIOS.items():
    a = orch.investigate(change)
    print(f"\n=== {name}: {a.target} ({change.environment}) -> score {a.score}/100, "
          f"human review: {a.requires_human}")
    for f in a.findings:
        print(f"  [{f.band.upper()} p={f.priority} conf={f.confidence} {f.approval['level']}] {f.title}")
        print(f"     -> {f.recommendation}")
    for c in a.conflicts:
        print(f"  conflict ({c['kind']}, resolved={c['resolved']}): {c['detail']} -> {c['winner']}")
    for e in a.excluded_sources:
        print(f"  excluded source: {e['ref']} ({e['reason']})")
    print("  " + a.summary)
print("\nmetrics:", json.dumps(orch.metrics.summary(), indent=2))
