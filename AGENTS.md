# Repository instructions

This repository evolves the existing learning project into a small, explainable AI Career Intelligence Agent. Preserve the learning examples; do not replace them with a generated framework.

## Current boundary

- The repository currently contains a legacy learning baseline. Phase 1 application work is pending.
- Put the new Python application in `app/` and its tests in `tests/` when Phase 1 resumes.
- Keep legacy examples in `examples/learning_agent/`. They are historical teaching code, not modules for the new runtime.
- Do not implement the frontend, FastAPI, job analysis or a multi-agent swarm while completing Phase 1.

## LLM and tools

- Place model calls in `app/services/llm.py` and a small provider adapter module if needed.
- Planner, Executor and Verifier must not instantiate vendor SDK clients.
- Use DeepSeek first, with a fake implementation for deterministic offline tests.
- Configuration: `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`.
- Use Pydantic as the internal schema contract. Validate model output and enforce bounded repair/retry with explicit errors.
- Tool definitions are provider neutral. An adapter translates them if native model tool calling is used.
- Never log keys, raw SDK exceptions or personal profile/conversation content.

## Tests and teaching

- Legacy tests: run `python -m unittest discover -s tests -v` from `examples/learning_agent/`.
- Never import interactive legacy scripts during test discovery.
- Distinguish offline tests, synthetic demos and real-provider verification in reports.
- Each completed phase should have a short learning handoff covering only 3–5 important concepts.

## Version control

- Inspect the diff and run appropriate tests before each version is committed and pushed.
- Preserve the existing remote history. Never force push or discard user changes.
- Never commit `.env`, conversation memory, private profiles, local environments or execution logs.
