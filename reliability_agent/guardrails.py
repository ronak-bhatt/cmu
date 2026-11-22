"""Input checks, secret redaction, prompt-injection screening, source verification,
and the read-only tool gate."""
from __future__ import annotations
import json, re
from typing import Any, Callable
from .config import ALLOWED_KINDS, ALLOWED_ENVS, READ_ONLY_TOOLS, LIMITS
from .models import ChangeEvent, Doc
from .state import InvestigationState


class GuardrailViolation(ValueError): ...
class ToolNotAllowed(PermissionError): ...
class BudgetExceeded(RuntimeError): ...
class ToolFailure(RuntimeError): ...


SECRET_KEY = re.compile(r"(pass(word)?|secret|token|api[_-]?key|private[_-]?key|credential)", re.I)
SECRET_VALUES = [re.compile(r"AKIA[0-9A-Z]{16}"), re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")]
INJECTION = [re.compile(p, re.I) for p in (
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)",
    r"disregard (the )?(policy|policies|rules|instructions)",
    r"you are now", r"system prompt",
    r"(approve|mark) (this|it) (as )?(safe|low[- ]risk)",
    r"do not (flag|report)")]
WRITE_VERBS = ("create", "update", "delete", "patch", "apply", "scale", "put", "post",
               "write", "restart", "rollout", "set_", "remove")


def validate_change(c: ChangeEvent) -> None:
    if not c.id or not c.target:
        raise GuardrailViolation("change needs an id and a target")
    if c.kind not in ALLOWED_KINDS:
        raise GuardrailViolation(f"unsupported change kind '{c.kind}'")
    if c.environment not in ALLOWED_ENVS:
        raise GuardrailViolation(f"unknown environment '{c.environment}'")
    if not isinstance(c.before, dict) or not isinstance(c.after, dict):
        raise GuardrailViolation("before/after must be configuration objects")


def redact(obj: Any) -> Any:
    """Remove secrets before anything enters model context, logs or reports."""
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if SECRET_KEY.search(str(k)) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str) and any(p.search(obj) for p in SECRET_VALUES):
        return "[REDACTED]"
    return obj


def is_secret(path: str, *values) -> bool:
    """True when a config path or value looks like a credential (used to mask report text)."""
    return bool(SECRET_KEY.search(path)) or any(
        isinstance(v, str) and any(p.search(v) for p in SECRET_VALUES) for v in values)


def looks_like_injection(text: str) -> bool:
    return any(p.search(text or "") for p in INJECTION)


def usable(doc: Doc, today: str) -> tuple[bool, str]:
    """Source verification: only active, in-force, unexpired documents may support a decision."""
    if doc.status != "active":
        return False, f"status={doc.status}"
    if doc.effective > today:
        return False, "not yet effective"
    if doc.expires and doc.expires < today:
        return False, "expired"
    return True, "ok"


class ToolGate:
    """The only path to infrastructure. Allow-listed, read-only, budgeted, cached."""

    def __init__(self, tools: dict[str, Callable], state: InvestigationState,
                 allowlist=READ_ONLY_TOOLS, max_calls: int = LIMITS.max_tool_calls):
        self.tools, self.state, self.allowlist, self.max_calls = tools, state, allowlist, max_calls

    def call(self, name: str, **kwargs):
        s = self.state
        if name not in self.allowlist or name.lower().startswith(WRITE_VERBS):
            s.safety(f"blocked tool call '{name}'")
            raise ToolNotAllowed(name)
        key = (name, json.dumps(kwargs, sort_keys=True, default=str))
        with s._lock:
            if key in s.cache:
                return s.cache[key]
            if s.tool_calls >= self.max_calls:
                raise BudgetExceeded(f"tool budget of {self.max_calls} calls exhausted")
            s.tool_calls += 1
        try:
            result = self.tools[name](**kwargs)
            s.log("tool_gate", "tool_call", tool=name, args=kwargs)
        except Exception as exc:  # fallback path: record the gap, never guess
            s.tool_failures.append(name)
            s.log("tool_gate", "tool_failure", tool=name, error=str(exc))
            raise ToolFailure(f"{name}: {exc}") from exc
        with s._lock:
            s.cache[key] = result
        return result
