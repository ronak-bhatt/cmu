# Infrastructure Reliability Agent

Working implementation of the capstone design: five cooperating agents with Plan-and-Execute, RAG,
bounded Tree-of-Thought, deterministic scoring, a governance layer, and a Vue dashboard.
The system is **recommend-only**: it holds read-only tool access and cannot change infrastructure.

## Run
```
python run_demo.py                          # five sample scenarios, no dependencies needed
python -m unittest discover -s tests -t .   # 33 tests
pip install -r requirements.txt
uvicorn --factory reliability_agent.api:create_app --port 8000
cd frontend && npm install && npm run dev   # dashboard on http://localhost:5173
```

## How the design maps to code
| Design element | Code |
|---|---|
| Planner Agent (Plan-and-Execute, replanning) | `agents/planner.py` |
| Infrastructure Research Agent | `agents/research.py`, `tools.py` |
| Knowledge Retrieval Agent (RAG) | `agents/knowledge.py`, `rag.py`, `schema.sql` |
| Reliability Evaluation Agent (conflicts + Tree-of-Thought) | `agents/evaluation.py`, `tot.py` |
| Assessment and Reporting Agent | `agents/reporting.py`, `scoring.py` |
| Hybrid coordination (parallel, iterative, bounded loops) | `orchestrator.py` |
| Approval matrix and recommend-only boundary | `governance.py` |
| Guardrails (input, redaction, injection, source verification, tool gate) | `guardrails.py` |
| Evaluation metrics, targets and runtime alerts | `metrics.py`, `config.TARGETS` |
| Shared investigation state (short-term memory) | `state.py` |
| Persistence: investigations, reasoning trees, audit trail, engineer feedback | `storage.py` (`InMemoryRepository`, `PgRepository`), `schema.sql` |
| Long-term memory | `knowledge_chunks` (policies, incidents, exceptions); `investigations` (past assessments); `engineer_feedback` (reviewed feedback) |

## Behaviour worth knowing
- **Conflicts:** live data wins on current state (and the drift is reported as its own finding); active approved policy wins on requirements; incidents only
  adjust likelihood. Policy vs policy: more specific scope wins, then newer effective date. If no rule decides,
  the stricter value is used provisionally, confidence becomes Low, and a human is required.
- **Exceptions** are honoured only while active, unexpired and every stated condition is verified against live failover data (type, RTO, verified). An unknown condition fails closed, and an unmet exception is not cited as support.
- **Fallback:** any tool failure or missing core evidence (live config, topology, failover, monitoring) lowers confidence to Low and sends the assessment to a human, even when there are no findings.
- **Secrets:** values on credential-like paths are masked in findings, trails and logs, and the exposure is raised as a safety event that escalates.
- **Exception requests** (`ChangeEvent.exception_requested`) need the policy owner.
- **Scoring:** priority = severity x likelihood x impact (1..125); bands Critical >= 80, High >= 40, Medium >= 15.
  Reliability score = 100 minus capped deductions per category (weights and every likelihood/impact constant in `config.py`, `SCORING_VERSION` 1.1.0).
  Confidence is reported separately and never multiplied into the score.
- **Tree-of-Thought limits:** branching 3, depth 3, beam 3, and a hard cap of 13 nodes. With a cap of 13,
  three levels cannot all fan out (1 + 3 + 9 = 13), so in practice the tree reaches depth 2; the depth limit is a ceiling.
- **Confidence tiers:** only High confidence earns the lighter tiers (Medium risk acknowledged, Low risk report-only).
  Medium or Low confidence makes review mandatory at any band.
- **Production approval:** every finding on a production change needs mandatory review by the service owner, including
  Low findings covered by a verified failover or an active exception. Acknowledgment and report-only tiers apply outside production.
- **The language model never sets scores.** `llm.py` only narrates computed facts, and the narration is
  discarded if it does not contain the computed score.
- **Verification** (`Orchestrator.verify`) only reports a risk as resolved if the re-assessment re-examined that setting; others are listed as `not_rechecked`.
- **Feedback** is stored for human review; it never edits rules, weights or policies automatically
  (`governance.review_gate` enforces review plus a passing regression run for such changes).

## Not exercised here
`PgVectorStore`, `PgRepository`, `KubernetesReadOnly`, `PrometheusReadOnly`, `AnthropicLLM`, the FastAPI app and the Vue build
need packages or services that were not available when this was written, so they are untested.
The demo uses fixture infrastructure and a hashing embedder; use a real embedding model in production
and keep `EMBED_DIM` in sync with `schema.sql`.
