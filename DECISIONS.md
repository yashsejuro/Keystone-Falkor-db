# Decisions

- **Repo choice:** pydantic/pydantic. 4216 merged PRs, active human review
  culture, low bot noise.
- **Deterministic scoring.** The reviewer decision is pure Python + Cypher,
  not an LLM. Keeps the backtest reproducible and proves the graph makes
  the decision.
- **No LangGraph.** A 4-step plain-Python loop is easier to reason about
  and to explain to judges. No framework tax.
- **No free-form text-to-Cypher.** Every query is parameterized and
  curated. Prevents hallucinated queries and injection.
- **Actions only on sandbox repo.** Never touches the source repo.
- **No AI agent wrote this code.** Written by hand.