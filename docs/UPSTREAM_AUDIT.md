# Upstream audit

Audit date: 2026-09-19

Upstream: `matheus-rech/ai_diplomacy`, cloned at the starting commit of this project.

## Existing capabilities

- **Game engine and adjudication:** the vendored `diplomacy/` package, including `diplomacy.engine.Game`, maps, order parsing, and engine tests.
- **Agent implementation:** `ai_diplomacy/agent.py` provides stateful `DiplomacyAgent` instances with goals, relationships, diary memory, and order/negotiation behavior.
- **Provider abstraction:** `ai_diplomacy/clients.py` defines `BaseModelClient` and provider implementations for OpenAI, Claude, Gemini, DeepSeek, OpenRouter, Together, and compatible requests clients.
- **Prompts:** `ai_diplomacy/prompts/` and simplified/versioned prompt directories contain power and task prompt templates.
- **Negotiation loop:** `ai_diplomacy/negotiations.py` and `lm_game.py` coordinate private/global exchanges and async agent calls.
- **Execution and persistence:** `lm_game.py` supports model assignments, run directories, resume-from-phase, and critical-state analysis; game logic/history serialize run artefacts and logs.
- **Analysis:** `analysis/`, `experiments/`, `diplomacy_unified_analysis_final.py`, and `benchmark_results.ipynb` provide post-game analysis, including ignored-message and lie-detection experiments.
- **Visualization:** `ai_animation/` and `visualization_results/` provide a browser visualization and prepared analysis outputs.
- **Tests:** upstream tests cover the engine, models, analyzer, ignored messages, lie detection, and SVG optimization.

## Extension decisions

The first league layer is isolated in `frontier_diplomacy/`:

- Reuse upstream engine, agent, prompt, provider, negotiation, and game-runner code unchanged.
- Add a configuration-driven `LabRegistry` so tournament identity is a lab ID while exact model IDs remain versioned configuration.
- Add a deterministic, seeded scheduler that balances lab selection, power assignments, and pairwise encounters using soft penalties.
- Add a small CLI for listing labs, generating schedules, and validating saved schedules.

The runner and immutable per-game result schema are the next extension points. They should wrap `lm_game.py` rather than fork its game logic. Provider clients should likewise be adapted through a factory/adapter, not rewritten.

## Risks and limitations

- `pyproject.toml` currently declares Python `>=3.13`; environment setup must match this.
- Provider setup is API-key based and provider response/token accounting is not yet normalized into league records.
- Existing run persistence is phase-oriented; a league runner still needs a season manifest, completion markers, error categories, and immutable game artefacts.
- Prompt directories are versioned, but the selected prompt hash is not yet recorded per run.
- The existing default model assignment is power-oriented and hard-coded in `ai_diplomacy/utils.py`; the league registry intentionally avoids changing it until the runner adapter is implemented.
- Full upstream tests require project dependencies, which are not installed in this workspace; no paid API calls are part of unit testing.

## Local verification performed

- Upstream repository cloned successfully.
- Repository was clean before league additions.
- README, project tree, configuration, provider abstraction, model assignment helper, tests, and run commands were inspected.
