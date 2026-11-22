"""The language model only narrates computed facts. It never sets scores, bands or approvals."""
from __future__ import annotations
import os


def template_summary(f: dict) -> str:
    s = (f"Reliability score {f['score']}/100 for {f['target']}: {f['findings']} finding(s), "
         f"{f['high_or_critical']} high or critical; {f['needs_review']} need human review.")
    return s + " Recommend-only: no infrastructure was changed."


class NullLLM:
    def narrate(self, facts: dict) -> str:
        return template_summary(facts)


class AnthropicLLM:
    """Needs `pip install anthropic` and ANTHROPIC_API_KEY."""

    def __init__(self, model: str | None = None):
        import anthropic  # lazy import
        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

    def narrate(self, facts: dict) -> str:
        msg = self.client.messages.create(
            model=self.model, max_tokens=300,
            system="Write a 2-3 sentence summary for an SRE using ONLY the JSON facts given. "
                   "Do not change, add or omit any numbers. Do not give instructions.",
            messages=[{"role": "user", "content": str(facts)}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
