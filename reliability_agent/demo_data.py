"""Seed knowledge base, fixture infrastructure and sample changes for demos and tests."""
from __future__ import annotations
from .models import ChangeEvent, Doc
from .rag import InMemoryVectorStore, ingest
from .tools import FixtureInfra

TODAY = "2026-11-15"


def build_docs() -> list[Doc]:
    return [
        Doc("POL-AVAIL-001", "Availability standard v1: all production applications must run at least 3 replicas.",
            "policy", "wiki", "1", "deprecated", "2024-01-01",
            metadata={"rule": {"metric": "replicas", "op": ">=", "value": 3, "env": ["production"], "severity": 4}}),
        Doc("POL-AVAIL-002", "Availability standard v2: tier 1 production services must run at least 3 replicas "
            "unless a verified managed failover meeting an RTO of 15 minutes or an approved exception exists.",
            "policy", "git", "2", "active", "2026-01-01",
            metadata={"rule": {"metric": "replicas", "op": ">=", "value": 3, "env": ["production"], "tier": [1],
                               "severity": 4, "mitigation": {"failover_type": ["managed"], "max_rto_minutes": 15}}}),
        Doc("POL-AVAIL-004", "General production availability: production services must run at least 2 replicas.",
            "policy", "git", "1", "active", "2025-06-01",
            metadata={"rule": {"metric": "replicas", "op": ">=", "value": 2, "env": ["production"], "severity": 3}}),
        Doc("POL-BKP-001", "Recoverability: production databases must keep backups for at least 7 days (retention_days).",
            "policy", "git", "3", "active", "2025-09-01",
            metadata={"rule": {"metric": "retention_days", "op": ">=", "value": 7, "env": ["production"], "severity": 4}}),
        Doc("POL-SEC-003", "Compliance: production storage must be encrypted (encrypted true). No exceptions.",
            "policy", "git", "2", "active", "2025-01-01",
            metadata={"rule": {"metric": "encrypted", "op": "==", "value": True, "env": ["production"], "severity": 5}}),
        Doc("EXC-017", "Approved exception EXC-017: ledger-proxy may run 1 replica in production while a managed "
            "failover with RTO under 10 minutes stays in place.", "exception", "itsm", "1", "active", "2026-02-01",
            expires="2027-06-30", metadata={"service": "ledger-proxy", "metric": "replicas", "status": "approved",
                                            "condition": {"failover_type": "managed", "max_rto_minutes": 10}}),
        Doc("EXC-009", "Approved exception EXC-009: reports-api may run 1 replica in production.", "exception",
            "itsm", "1", "active", "2025-01-01", expires="2026-03-01",
            metadata={"service": "reports-api", "metric": "replicas", "status": "approved", "condition": {}}),
        Doc("INC-2025-114", "Incident INC-2025-114: checkout-api outage after replicas were reduced to one during a "
            "node drain; root cause single replica; 47 minutes of downtime.", "incident", "itsm", "1", "active",
            "2025-11-02", metadata={"service": "checkout-api", "tags": ["replicas", "availability"]}),
        Doc("ARCH-021", "Architecture: checkout-api is tier 1, depends on payments and inventory, spans three zones.",
            "architecture", "wiki", "1", "active", "2025-03-01", metadata={"service": "checkout-api"}),
    ]


def build_store(extra: list[Doc] | None = None) -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    for d in build_docs() + (extra or []):
        ingest(store, d)
    return store


def build_infra() -> FixtureInfra:
    topo = {"checkout-api": {"dependents": 4, "tier": 1}, "ledger-proxy": {"dependents": 3, "tier": 1},
            "orders-db": {"dependents": 5, "tier": 1}, "reports-api": {"dependents": 0, "tier": 3}}
    return FixtureInfra({
        "live": {"checkout-api": {"spec": {"replicas": 3}}, "ledger-proxy": {"spec": {"replicas": 3}},
                 "reports-api": {"spec": {"replicas": 3}},
                 "orders-db": {"backup": {"retention_days": 14}, "storage": {"encrypted": True, "kms_key": "k-1"}}},
        "topology": topo,
        "failover": {"ledger-proxy": {"present": True, "type": "managed", "rto_minutes": 5, "verified": True}},
        "metrics": {"checkout-api": {"availability_30d": 99.95, "slo": 99.9, "cpu_p95": 0.6},
                    "ledger-proxy": {"availability_30d": 99.99, "slo": 99.9, "cpu_p95": 0.4},
                    "reports-api": {"availability_30d": 99.5, "slo": 99.0, "cpu_p95": 0.3},
                    "orders-db": {"availability_30d": 99.99, "slo": 99.9, "cpu_p95": 0.5}},
        "incidents": {"checkout-api": [{"id": "INC-2025-114", "tags": ["replicas", "availability"],
                                        "summary": "Outage after replica reduction during node drain"}]}})


def scale(cid: str, target: str, env: str, tier: int, to: int, frm: int = 3, **kw) -> ChangeEvent:
    return ChangeEvent(cid, "kubernetes", target, env, {"spec": {"replicas": frm}}, {"spec": {"replicas": to}},
                       tier, **kw)


SCENARIOS = {
    "spof": scale("CHG-1", "checkout-api", "production", 1, 1, description="cost reduction"),
    "exception": scale("CHG-2", "ledger-proxy", "production", 1, 1, description="cost reduction"),
    "staging": scale("CHG-3", "reports-api", "staging", 3, 1),
    "encryption": ChangeEvent("CHG-4", "terraform", "orders-db", "production",
                              {"storage": {"encrypted": True}}, {"storage": {"encrypted": False}}, 1),
    "backups": ChangeEvent("CHG-5", "terraform", "orders-db", "production",
                           {"backup": {"retention_days": 14}}, {"backup": {"retention_days": 3}}, 1),
}


def demo_orchestrator(**kw):
    from .orchestrator import Orchestrator
    return Orchestrator(build_infra().tools(), build_store(), today=TODAY, **kw)
