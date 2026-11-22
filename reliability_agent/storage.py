"""Persistence for investigations, reasoning trees, audit trail and engineer feedback.
InMemoryRepository runs anywhere; PgRepository writes the PostgreSQL tables in schema.sql.
Feedback is stored for human review only: it never edits rules, weights or policies."""
from __future__ import annotations
import dataclasses, json
from typing import Optional


class InMemoryRepository:
    def __init__(self):
        self.investigations: dict[str, dict] = {}
        self.audit: list[dict] = []
        self.feedback: list[dict] = []

    def save(self, assessment, state) -> None:
        self.investigations[assessment.investigation_id] = assessment.to_dict()
        for entry in state.audit:
            self.audit.append({"investigation_id": assessment.investigation_id, **entry})
        for m in state.messages:
            self.audit.append({"investigation_id": assessment.investigation_id, "actor": m.sender,
                               "event": "message", **dataclasses.asdict(m)})

    def get(self, investigation_id: str) -> Optional[dict]:
        return self.investigations.get(investigation_id)

    def add_feedback(self, investigation_id: str, finding_id: str, confirmed: bool, confidence: str) -> None:
        self.feedback.append({"investigation_id": investigation_id, "finding_id": finding_id,
                              "confirmed": confirmed, "confidence": confidence, "reviewed": False})


class PgRepository:
    """Requires `pip install psycopg[binary]` and schema.sql. Untested here (no database available)."""

    def __init__(self, dsn: str):
        import psycopg  # lazy import
        self.conn = psycopg.connect(dsn, autocommit=True)

    def save(self, assessment, state) -> None:
        a, iid = assessment, assessment.investigation_id
        with self.conn.transaction():
            self.conn.execute(
                """INSERT INTO investigations (id, change_id, target, score, requires_human, scoring_version, assessment)
                   VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
                   ON CONFLICT (id) DO UPDATE SET change_id=EXCLUDED.change_id, target=EXCLUDED.target,
                     score=EXCLUDED.score, requires_human=EXCLUDED.requires_human,
                     scoring_version=EXCLUDED.scoring_version, assessment=EXCLUDED.assessment, created_at=now()""",
                (iid, a.change_id, a.target, a.score, a.requires_human, a.scoring_version,
                 json.dumps(a.to_dict(), default=str)))
            self.conn.execute("DELETE FROM hypotheses WHERE investigation_id = %s", (iid,))
            for h in a.hypotheses:
                self.conn.execute(
                    """INSERT INTO hypotheses (investigation_id, id, parent, kind, statement, depth, score, status,
                                               delta, evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (iid, h["id"], h["parent"], h["kind"], h["statement"], h["depth"], h["score"], h["status"],
                     h.get("delta"), json.dumps(h.get("evidence", []))))
            for entry in state.audit:
                event = entry.get("event", "")
                detail = {k: v for k, v in entry.items() if k not in ("actor", "event")}
                self.conn.execute("INSERT INTO audit_log (investigation_id, actor, event, detail) VALUES (%s,%s,%s,%s::jsonb)",
                                  (iid, entry.get("actor"), event, json.dumps(detail, default=str)))

    def get(self, investigation_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT assessment FROM investigations WHERE id = %s", (investigation_id,)).fetchone()
        return row[0] if row else None

    def add_feedback(self, investigation_id: str, finding_id: str, confirmed: bool, confidence: str) -> None:
        self.conn.execute("INSERT INTO engineer_feedback (investigation_id, finding_id, confirmed, confidence) "
                          "VALUES (%s,%s,%s,%s)", (investigation_id, finding_id, confirmed, confidence))
