"""HTTP API for the Vue dashboard.  Run:  uvicorn --factory reliability_agent.api:create_app --port 8000"""
from __future__ import annotations
import dataclasses


def create_app(orchestrator=None):
    from fastapi import FastAPI, HTTPException         # lazy: only needed when serving
    from .demo_data import SCENARIOS, demo_orchestrator
    from .guardrails import GuardrailViolation
    from .models import ChangeEvent

    orch = orchestrator or demo_orchestrator()
    app = FastAPI(title="Infrastructure Reliability Agent")

    @app.get("/api/scenarios")
    def scenarios():
        return {k: dataclasses.asdict(v) for k, v in SCENARIOS.items()}

    @app.post("/api/investigations")
    def investigate(body: dict):
        try:
            assessment = orch.investigate(ChangeEvent(**body))
        except (TypeError, GuardrailViolation) as exc:
            raise HTTPException(422, f"Invalid change: {exc}")
        return assessment.to_dict()                    # already persisted by the orchestrator's repository

    @app.post("/api/investigations/{inv_id}/feedback")
    def feedback(inv_id: str, body: dict):
        a = orch.repo.get(inv_id)
        finding = next((f for f in (a["findings"] if a else []) if f["id"] == body.get("finding_id")), None)
        if not finding:
            raise HTTPException(404, "unknown investigation or finding")
        # Stored for reviewed, version-controlled updates. Never edits rules or weights directly.
        orch.record_feedback(inv_id, finding["id"], bool(body.get("confirmed")), finding["confidence"])
        return {"recorded": True}

    @app.get("/api/metrics")
    def metrics():
        return {**orch.metrics.summary(), "alerts": orch.metrics.alerts()}

    return app
