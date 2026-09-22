# Spring 1901 seven-model efficiency audit

Completed September 22, 2026. Experiment ID:
`efficiency-audit-20260922-d54ea8d8`.

The operator asked to stop after Spring. The engine saved Spring 1901's
adjudicated orders and the seven post-phase reflections. The worker was then
stopped. It had already started Fall press; no Fall orders were submitted or
adjudicated. The experiment is marked **cancelled after Spring**, not a
year-limit result or game outcome.

## Roster and setup

| Power | Model | Route |
| --- | --- | --- |
| Austria | GPT-5.6 Terra | OpenAI direct |
| England | Claude Opus 4.7 | Anthropic direct |
| France | Gemini 3.8 Flash | Google direct |
| Germany | Llama 4 Maverick | OpenRouter |
| Italy | DeepSeek V4.1 Flash | OpenRouter |
| Russia | Grok 4.20 reasoning | **native xAI**, `api.x.ai` |
| Turkey | Kimi K3 | OpenRouter |

Standard map, neutral-v1 prompts, full press, three rounds, no optional
planning, provider-default reasoning settings, 16,000 requested output token
limit, and one shared OpenRouter request at a time. The $5 experiment budget
was enforced before each request. No reasoning, prompt, route, or concurrency
optimization was applied during this baseline.

## What happened on the board

All seven powers supplied a complete set of orders. The engine accepted and
adjudicated them. No movement order bounced; starting supply-center counts
remain unchanged in Spring, as expected before Fall occupation. Examples of
the saved board progression:

- Austria moved BUD → SER and TRI → ALB.
- England moved its fleets into NTH and NWG.
- France moved MAR → SPA and BRE → MAO.
- Germany moved BER → SIL with support from MUN and moved KIE → DEN.
- Italy moved NAP → ION and ROM → APU.
- Russia held SEV while moving STP/SC → BOT, MOS → LVN and WAR → UKR.
- Turkey moved ANK → BLA, CON → BUL and SMY → ANK.

These are engine facts from `games/league-0001/lmvsgame.json`. There is no
winner or draw. `F1901M` in the exported phase list is the *next phase's
starting state*; it has no adjudication results and must not be counted as a
completed Fall phase.

The response CSV shows 7 applied initial states, 21 accepted press responses,
7 applied negotiation diaries, 7 successful order responses, and 7 successful
Spring reflections. Three press replies needed local regex fallback after JSON
parsing failed; the harness did not make a separate repair-model request.

## Time and token measurements

Initialization took approximately **113 seconds**. Spring movement from the
first press round through its checkpoint took **2,414.94 seconds (40.25
minutes)**. Total launch-to-Spring-checkpoint time was roughly **42.1
minutes**. The 49 Spring provider calls are 7 each for initialization, three
press rounds, negotiation diary, orders, and reflection. The local engine's
adjudication was fast; request service time and the barriers dominated.

| Model | Calls | Provider service time across calls | Longest call | Input tokens | Visible output | Reasoning tokens | Spring USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemini 3.8 Flash | 7 | 42 s | 15 s | 18,045 | 1,929 | 4,541* | $0.0378 |
| GPT-5.6 Terra | 7 | 109 s | 28 s | 20,139 | 2,319 | 1,492 | $0.0956 |
| Claude Opus 4.7 | 7 | 96 s | 24 s | 31,484 | 4,260 | unexposed | $0.2639 |
| Grok 4.20 | 7 | 109 s | 26 s | 19,761 | 1,713 | 8,448 | $0.0492 |
| Llama 4 Maverick | 7 | 330 s | 106 s | 17,903 | 2,600 | unexposed | $0.0051 |
| DeepSeek V4.1 Flash | 7 | 273 s | 111 s | 20,233 | 2,213 | 6,397 | $0.0091 |
| Kimi K3 | 7 | **1,924 s** | **684 s** | 22,298 | 4,349 | **37,901** | **$0.4112** |

Provider service sums overlap across powers and must not be added to estimate
wall time. OpenRouter's serial gate additionally made DeepSeek wait a total of
330 seconds and Kimi wait a total of 602 seconds across their Spring calls.
Those queue sums also overlap other model service time. Kimi accounted for
about **47% of Spring cost** and generated about **8.7 reasoning tokens per
visible output token**. One Kimi press request spent 505 seconds producing
13,243 reasoning tokens and 996 visible tokens; another lasted 684 seconds.
The `finish_reason` was `stop`, not a length-limit error. There is no evidence
that the 16,000-token requested output cap truncated a Spring response.

*The deprecated Gemini SDK omitted the explicit thoughts count but supplied
total, prompt and candidate token counts. The displayed thinking tokens are
derived as total − prompt − candidates using Google's documented usage
definition. They are provider-metadata-derived, not a direct thoughts field.
Anthropic and Maverick did not expose a comparable separate reasoning count;
“unexposed” is not zero reasoning.

The longest prompt in the trace was 17,222 UTF-8 bytes. No context-limit error
occurred. The shorter historical context some agents saw comes largely from
the prompt constructor's selection policy; a model's advertised context
window alone does not restore omitted history. OpenRouter endpoint context and
maximum completion limits differ even for the same model. The frozen public
endpoint catalog is saved with the experiment.

## Accounting and cancellation

Spring's accounted model API cost is **$0.8718076025** after audited
adjustments. The current ledger has 28 calculated Spring charges, 21
provider-reported Spring charges and 16 small accounting-adjustment rows
totaling $0.03035970. Corrections were appended rather than rewriting raw
records. They address the previously mislabeled OpenAI Batch price card,
xAI's provider-reported cost ticks and separately counted reasoning, and
Gemini's omitted thoughts category. Future standard OpenAI prices in
`config/labs.yaml` are now correct.

Four Fall press calls settled before cancellation, costing **$0.08603985**.
Total known spend for this experiment is **$0.9578474525**. One interrupted
Fall OpenRouter request has **$0.012337 unresolved reserved exposure**; its
final provider charge is unknown. The exposure remains held in the budget
ledger, not booked as zero or released. Do not include the partial Fall calls
in Spring per-model metrics or any completed-game standings.

The shared cost database is `data/frontier_diplomacy_costs.sqlite`. The
experiment contains `calls.jsonl`, `llm_responses.csv`, `general_game.log`,
`lmvsgame.json`, `cancellation.json`, `efficiency_metrics.json`,
`EFFICIENCY_REPORT.md`, and the endpoint price/context snapshot under
`results/efficiency-audit-20260922-d54ea8d8/`.

## Interpretation

At the observed Spring rate, naively chaining 50 games × 20 years would be
slow, but multiplying 40 minutes by 2,000 movement phases would be a poor
forecast: first-year initialization occurs once per game, later memory and
eliminations change call sizes/counts, and Fall/Winter were not completed.
The principal measured opportunities are reducing default Kimi reasoning for
short tasks as a versioned treatment, choosing a faster eligible endpoint for
the same model, testing more OpenRouter concurrency while preserving press
barriers, and reducing redundant serial model stages. The proposed sequence,
cost comparisons, validation gates and source links are in
`docs/EFFICIENCY_PLAN_FOR_APPROVAL.md`.

The baseline worker loaded code at launch. Source fixes made while it was
running apply to future workers, and historical charges were corrected with
append-only adjustments. No new paid run has been launched to test the
proposed optimizations.
