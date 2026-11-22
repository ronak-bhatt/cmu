"""Read-only infrastructure adapters. FixtureInfra is used for demos and tests;
KubernetesReadOnly and PrometheusReadOnly show how live adapters plug into the ToolGate."""
from __future__ import annotations
import json, urllib.parse, urllib.request
from typing import Callable


class FixtureInfra:
    def __init__(self, data: dict):
        self.data = data

    def _get(self, section: str, target: str):
        try:
            return self.data[section][target]
        except KeyError:
            raise LookupError(f"no {section} data for {target}")

    def tools(self) -> dict[str, Callable]:
        return {
            "get_live_config": lambda target: self._get("live", target),
            "get_topology": lambda target: self._get("topology", target),
            "get_failover": lambda target: self.data.get("failover", {}).get(target) or {"present": False},
            "get_metrics": lambda target: self._get("metrics", target),
            "get_incidents": lambda target: self.data.get("incidents", {}).get(target, []),
        }


class KubernetesReadOnly:
    """Needs `pip install kubernetes`. Uses only read_* calls (RBAC role should be get/list only)."""

    def __init__(self, namespace: str = "default"):
        from kubernetes import client, config  # lazy import
        config.load_kube_config()
        self.apps, self.ns = client.AppsV1Api(), namespace

    def get_live_config(self, target: str) -> dict:
        d = self.apps.read_namespaced_deployment(target, self.ns)
        return {"spec": {"replicas": d.spec.replicas}}


class PrometheusReadOnly:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def query(self, promql: str) -> float | None:
        url = f"{self.base}/api/v1/query?{urllib.parse.urlencode({'query': promql})}"
        with urllib.request.urlopen(url, timeout=5) as r:  # GET only
            res = json.load(r)["data"]["result"]
        return float(res[0]["value"][1]) if res else None
