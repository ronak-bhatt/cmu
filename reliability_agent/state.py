"""Shared investigation state: the short-term memory every agent reads and writes."""
from __future__ import annotations
import threading, time
from typing import Optional
from .models import ChangeEvent, Delta, Doc, Evidence, AgentMessage


class InvestigationState:
    def __init__(self, change: ChangeEvent, today: str):
        self.change, self.today = change, today
        self.id = f"INV-{change.id}"
        self._lock = threading.RLock()
        self._counters: dict[str, int] = {}
        self.evidence: dict[tuple, Evidence] = {}
        self.deltas: list[Delta] = []
        self.docs: dict[str, Doc] = {}            # usable (active, current) docs
        self.excluded: list[tuple[Doc, str]] = [] # (doc, reason) filtered out by guardrails
        self.conflicts: list = []
        self.hypotheses: list = []
        self.safety_events: list[str] = []
        self.messages: list[AgentMessage] = []
        self.audit: list[dict] = []
        self.cache: dict = {}
        self.tool_calls = 0
        self.tool_failures: list[str] = []
        self.requested: set[str] = set()
        self.started = time.monotonic()

    def next_id(self, prefix: str) -> str:
        with self._lock:
            self._counters[prefix] = self._counters.get(prefix, 0) + 1
            return f"{prefix}{self._counters[prefix]}"

    def add_evidence(self, source: str, ref: str, summary: str, data: Optional[dict] = None) -> Evidence:
        with self._lock:
            key = (source, ref)
            if key not in self.evidence:
                self.evidence[key] = Evidence(self.next_id("E"), source, ref, summary, data or {})
            return self.evidence[key]

    def find(self, source: str, ref_prefix: str = "") -> list[Evidence]:
        return [e for (s, r), e in self.evidence.items() if s == source and r.startswith(ref_prefix)]

    def log(self, actor: str, event: str, **detail) -> None:
        with self._lock:
            self.audit.append({"t": round(time.monotonic() - self.started, 3), "actor": actor,
                               "event": event, **detail})

    def safety(self, message: str) -> None:
        with self._lock:
            self.safety_events.append(message)
        self.log("guardrails", "safety_event", message=message)

    def send(self, msg: AgentMessage) -> None:
        with self._lock:
            self.messages.append(msg)
