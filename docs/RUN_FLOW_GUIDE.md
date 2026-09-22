# How this repository actually runs a game

Code audit: September 22, 2026. Paths below are relative to the repository root.
This describes the current code, including the narrow bug fixes made during the
efficiency audit. It is not a claim that all of PLAN.md has been implemented.

## 1. The three systems to distinguish

```text
configuration / scheduling / accounting       frontend or CLI
                 frontier_diplomacy/                 |
                            | <----------------------+
                            v
                       lm_game.py
                       /        \
        ai_diplomacy/              diplomacy/engine/
        prompts, agents, APIs     deterministic rules and adjudication
                       \        /
                        saved artifacts
                              |
                analysis / replay / standings
```

The model APIs choose messages and orders. They do NOT decide whose moves
succeed. The local Python engine adjudicates the submitted orders. The older
human-play Python server on port 8432 and React site on port 3000 are not needed
to run these benchmark games.

| Area | Responsibility | Starting files |
| --- | --- | --- |
| Experiment management | Model registry, country assignments, budgets, launches | `frontier_diplomacy/registry.py`, `scheduler.py`, `experiment.py`, `service.py` |
| Worker launch | Translate experiment into a subprocess command, save metadata and exit status | `frontier_diplomacy/runner.py` |
| Actual game loop | Initialize, negotiate, order, adjudicate, reflect, save | `lm_game.py` |
| Agent behavior | Goals, relationships, private notes, prompt construction, responses | `ai_diplomacy/agent.py`, `clients.py`, `prompt_constructor.py` |
| Rules | Board, legal orders, simultaneous resolution, phase advancement, victory | `diplomacy/engine/game.py`, `map.py`, `power.py` |
| Usage and costs | Request reservations, raw usage, pricing, ledger | `frontier_diplomacy/telemetry.py`, `accounting.py` |
| New management UI | React setup/list view and local API | `dashboard/src/main.tsx`, `frontier_diplomacy/server.py` |
| Old human-play UI | Interactive human client/server, not benchmark orchestration | `diplomacy/web/`, `diplomacy/server/` |
| Replay | Animation of saved game data | `ai_animation/`, `visualization_results/` |
| Post-hoc analysis | Orders, conversations, phase statistics, standings | `analysis/`, `experiment_runner/analysis/`, `frontier_diplomacy/analytics.py` |

`experiment_runner.py` is an older experiment launcher, not the new budgeted
service. Likewise, a direct unconfigured legacy CLI launch does not necessarily
have the new experiment's ledger context. Use the budgeted path for paid work.

## 2. Which prompts are active?

The current runner defaults to simple prompts, so read
`ai_diplomacy/prompts_simple/` first. There are similarly named legacy files in
`ai_diplomacy/prompts/`; editing those does not change a default simple run.
Per-power prompt-directory overrides can also change the active files.

For `prompt_profile=neutral-v1`, `agent.py` uses
`prompts_simple/neutral_system_prompt.txt` instead of the country-flavor system
prompt. The API client sends that as system instructions. The blank generic
`system_prompt.txt` is not the effective neutral system prompt. The initialization
template was also blank; the audit fixed that separate defect.

There are two layers in a request:

1. System instructions: identity as a power, Diplomacy objectives and conduct.
2. Stage-specific user prompt: board/context plus instructions for that task.

Several clients additionally prepend a random block from
`ai_diplomacy/utils.py:generate_random_seed`. This is unrelated to the engine's
game seed. It adds input tokens and changes the beginning of otherwise reusable
requests. Removing it is a proposed optimization, not yet done in the baseline.

## 3. A complete first year, in execution order

```text
Initialize seven agents (once)
  S1901M: press rounds -> optional plan -> negotiation diary
           -> consolidation check -> orders -> engine -> reflection -> save
  S1901R: retreat orders -> engine -> save               [only if needed]
  F1901M: press rounds -> optional plan -> negotiation diary
           -> orders -> engine -> reflection -> save
  F1901R: retreat orders -> engine -> save               [only if needed]
  W1901A: build/disband orders -> engine                 [only if needed]
  End of year: private draw ballots if allowed -> save
  S1902M: continue, or stop at the one-year limit
```

The engine can skip phases that have no actions. The draw trigger now detects
the transition to next Spring, so it also works when Winter is skipped. A solo
already recognized by the engine takes precedence. A year limit without a solo
or unanimous draw is an unresolved year-limit result, not a draw victory.

### A. Initialization: one request per power

Entry: `ai_diplomacy/game_logic.py:initialize_new_game`, then
`ai_diplomacy/initialization.py:initialize_agent_state_ext`.

Templates:

- `prompts_simple/initial_state_prompt.txt`
- `prompts_simple/context_prompt.txt`
- The effective neutral system prompt described above.

Each model chooses its own initial goals and relationship labels. Initialization
includes the board and private state but does not include the legal-order list.
The parser expects `initial_goals` and `initial_relationships` JSON fields.
These are harness-maintained private state, not hidden reasoning. Previously the
empty task template could produce parseable text that applied no initial state.

### B. Press: three sequential rounds in this audit

Entry: `ai_diplomacy/negotiations.py:conduct_negotiations`; request builder:
`ai_diplomacy/clients.py:build_conversation_prompt`.

Templates:

- `prompts_simple/context_prompt.txt`
- `prompts_simple/conversation_instructions.txt`

A round requests a response from every active power. The harness waits for the
round's responses before delivering accepted messages. Thus another model's
fast response cannot give a slower model advance knowledge within the same
round. One response can contain several private/global messages. The current
`conversation_instructions.txt` requires one or more messages and *prefers*
several, even though the parser can handle an empty list; this prompt should be
changed in a future treatment if voluntary silence is desired. Three rounds
means three model calls per active power, not three total messages.

Context includes public board information, own goals/relationships/diary and
permitted current-phase messages. The request builder repeats up to three recent
messages as high-priority follow-ups, although they can already occur in the
main context. The negotiations code validates recipients; a malformed private
recipient must not become a global broadcast.

Visibility is assembled using `ai_diplomacy/game_history.py` history helpers and
`ai_diplomacy/prompt_constructor.py`. Global messages and private conversations
involving the player are allowed; other players' private conversations are not.
Operator logs deliberately contain all powers' traffic and are not player context.

Concurrency has two levels: round tasks are gathered together, but
`ai_diplomacy/utils.py:_provider_semaphore` permits only one OpenRouter request
at a time by default. Llama, DeepSeek and Kimi therefore queue behind each other.

### C. Optional strategic plan

Entry: `ai_diplomacy/planning.py:planning_phase`, `clients.py:get_plan`.
Template: `prompts_simple/planning_instructions.txt` plus the shared context.

This is after press and before orders. Plans are stored in game history, but
the current order prompt constructor does not consume the stored plan. The
audit leaves planning off. Enabling it currently adds a paid stage without the
promised explicit plan-to-orders connection; repair that before evaluating it.

### D. Negotiation diary

Entry: `agent.py:generate_negotiation_diary_entry`.
Template: `prompts_simple/negotiation_diary_prompt.txt`.

Each active power makes another request to summarize its negotiations and
intentions into private notes. This stage matters more than its name suggests:
in simple mode, the later order prompt omits raw press and relies on memory.
It is not merely optional operator commentary.

### E. Older-memory consolidation

Entry: `ai_diplomacy/diary_logic.py:run_diary_consolidation`.
Template: `prompts_simple/diary_consolidation_prompt.txt`.

This check runs each Spring, after press/planning/negotiation diary and before
orders. With only one year of entries it makes no consolidation call. Later it
keeps the latest year's notes verbatim and summarizes older entries using that
power's own model. Raw entries remain in `full_private_diary`; the selected
context is `private_diary`.

Important gap: it re-summarizes the older raw archive rather than incrementally
merging only newly aged-out notes. Also, consolidation happens after press,
so press and orders do not necessarily see exactly the same memory selection.

### F. Orders

Entry: `ai_diplomacy/utils.py:get_valid_orders`, `clients.py:get_orders`,
`prompt_constructor.py:construct_order_generation_prompt`.

Templates:

- `prompts_simple/context_prompt.txt`
- `prompts_simple/order_instructions_movement_phase.txt`
- `prompts_simple/order_instructions_retreat_phase.txt`
- `prompts_simple/order_instructions_adjustment_phase.txt`

The phase determines which order instruction file is used. The legal-action
context is constructed in `ai_diplomacy/possible_order_context.py` from engine
possibilities. That file also adds distances and tactical descriptions; these
are extra harness help rather than rules the engine requires in a prompt.

The current simple order prompt has `include_messages=False` and order-history
inclusion hardcoded off. Other context builders request one previous movement
phase, not the two promised in the larger plan. The order prompt embeds the
system prompt again even though the client also sends it as a system message.
The loaded few-shot example is not used by this constructor.

Response parsing is local JSON/regex extraction. An optional legacy formatter
path can make a separate model call when unformatted prompts are enabled; it
is not the default audit treatment and must remain disabled for no-repair
benchmarking. Missing/invalid orders ultimately receive engine default behavior.

Validation currently submits individual candidate orders to the shared game,
then clears them. It is not yet whole-set validation against isolated snapshots.
The main loop waits for the order tasks and commits the returned lists before
one call to `game.process()`. This is a correctness gap to address before a
large comparative tournament, not a reason to grant models repair calls.

### G. Adjudication: entirely local

`lm_game.py` calls `game.set_orders(power, orders)` and then `game.process()`.
The principal implementation is `diplomacy/engine/game.py`:

1. `set_orders` routes to movement, retreat or adjustment order processing.
2. `process` records phase state/orders/messages and invokes `_process`.
3. `_determine_orders` normalizes orders and supplies missing-order behavior.
4. `_resolve`, `_move_results`, `_resolve_moves`, and `_other_results` resolve
   movement conflicts, support, convoys, retreats and adjustments.
5. `_advance_phase` and `_check_phase` move to the next required phase.
6. `_determine_win` checks center-based victory according to the map/rules.

Topology is supplied by `diplomacy/maps/standard.map` and `engine/map.py`.
There is no referee LLM deciding bounces or whether a support is valid.
`diplomacy/tests/test_game.py` and the `test_datc*.py` files exercise the rules.

### H. Post-movement reflection

Entry: `agent.py:generate_phase_result_diary_entry`.
Template: `prompts_simple/phase_result_diary_prompt.txt`.

Each active power reviews adjudicated orders/results and writes private notes.
The audit repaired a phase mismatch: the engine has already advanced, so press
must be fetched from the completed phase, not the new current phase. Otherwise
reflections incorrectly saw no negotiations.

The separate order-diary call is disabled in `lm_game.py` with `if False`.
Do not count it as a live stage just because `order_diary_prompt.txt` exists.
The main loop does not pass an LLM narrative callback into engine processing;
its phase-summary fallback can be “Summary not generated.”

In gunboat, negotiations and their diary stage are skipped. Movement reflection
still happens, followed by an additional `analyze_phase_and_update_state` call
using `prompts_simple/state_update_prompt.txt`. Gunboat therefore does not mean
only two order calls per model per year.

### I. Draw ballots and saves

`ai_diplomacy/draws.py:collect_draw_votes` constructs an inline private JSON
ballot prompt containing the public board and own diary. The votes are gathered
simultaneously; all surviving powers must say yes. Solo-only skips the calls.
The current ballot helper does not explicitly write individual ballot text to
the response CSV, although the requests are accounted in the usage ledger.

`ai_diplomacy/game_logic.py:save_game_state` writes the engine export, agent
state and history to `lmvsgame.json` at phase boundaries. This is not yet a
durable per-request action journal: interruption within a phase can require
repeating work. The existing load path can also fall back to a new game after
invalid saved data. Do not assume fully safe crash/resume semantics.

## 4. How many API calls does that imply?

For seven surviving powers, three press rounds, planning off, full press:

| Task | First-year calls |
| --- | ---: |
| Initialization | 7 |
| Spring + Fall press | 42 |
| Negotiation diaries | 14 |
| Movement orders | 14 |
| Movement reflections | 14 |
| End-year draw ballots | 7 if enabled |
| Retreat/build orders | Depends on board and eligible powers |
| Older-memory consolidation | 0 in the first year |

That is 98 calls before any retreat/build calls or retries. Planning adds 14.
Later years omit initialization but add consolidation, and eliminations reduce
the number of active powers. The number of sequential barriers is as important
as the total token count: each round waits for its slowest provider path.

## 5. Where to inspect a run

Experiment root: `results/<experiment-id>/`.

- `experiment.json`, `schedule.json`, `manifest.json`: settings and assignments.
- `games/league-0001/metadata.json`: effective roster and experiment settings.
- `general_game.log`: live stage, parsing and engine diagnostics.
- `llm_responses.csv`: logged prompts, responses and parse statuses by stage.
- `calls.jsonl`: audit dispatch/completion events, provider, queue and service
  times, configured output cap and provider finish metadata.
- `lmvsgame.json`: saved engine phases and private agent state after a save.
- `overview.jsonl`, `summary.json`: end-of-run diagnostics and derived outcome.
- `runner.stdout.log`, `runner.stderr.log`: currently captured by the parent
  subprocess runner and written when the process exits, not live streams.
- `status.json`: process-level status, which is not sufficient to prove an
  actual game year has completed.

The shared ledger is `data/frontier_diplomacy_costs.sqlite`. It survives deletion
of a game's directory. Raw provider usage must remain available because token
categories differ: xAI completion tokens exclude its separately reported
reasoning, whereas OpenAI-compatible inclusive totals often contain reasoning.

## 6. What the current frontend and analytics do not yet do

The checked-in `dashboard/src/main.tsx` is a small setup/list UI. It hardcodes
seven games, twenty years, three press rounds and planning off. It fetches on
mount rather than continuously streaming stages. It does not implement the
five-screen live control room in the plan. Server endpoints and UI capabilities
must be assessed separately; an endpoint existing does not make a UI control.

`frontier_diplomacy/analytics.py` formerly included directories with metadata
even when there was no completed summary, substituting zero centers. The audit
changed it to exclude games without a summary or with a non-completed status;
the returned `unfinished_games_excluded` field identifies them.

`ModelProfile` fields do not all propagate to `lm_game.py`: the runner currently
passes model identities but not per-profile reasoning or output limits. The
legacy CLI default of 16,000 output tokens is what the audit actually requests.
The first-year audit measures this code path, not the larger planned harness.
